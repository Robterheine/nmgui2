import os, re, subprocess, logging, time, shlex
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QMenu, QMessageBox, QFileDialog,
    QApplication, QStyledItemDelegate,
    QStackedWidget, QSizePolicy, QDialog, QInputDialog, QCheckBox,
    QPlainTextEdit, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QModelIndex, QAbstractTableModel, QTimer
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QFont, QAction, QPalette
from ..app.theme import C, T, THEMES, _active_theme, monospace_font
from ..app.constants import IS_WIN, IS_MAC, HOME
from ..app.config import load_meta, save_meta, get_meta_entry, load_settings, save_settings, load_bookmarks, save_bookmarks, get_all_tags
from ..app.format import fmt_ofv, fmt_num, fmt_rse
from ..app.tools import find_tool, get_login_env, launch_rstudio
from ..app.run_records import load_run_records
from ..app.workers import ScanWorker
from ..app import detached_runs as _dr
from ..dialogs.run_popup import RunPopup, WatchLogPopup
from ..app.model_io import _parse_param_names_from_mod, _align_param_names
from ..app.html_report import generate_html_report
from ..app.qc_report import generate_qc_html, open_report_in_browser
from ..widgets.parameter_table import ParameterTable
from ..widgets.highlighter import NMHighlighter
from ..widgets.lst_viewer import LstOutputWidget
from ..dialogs.duplicate import DuplicateDialog
from ..dialogs.comparison import ModelComparisonDialog
from ..dialogs.workbench import ModelWorkbenchDialog
from ..dialogs.new_model import NewModelDialog
from ..widgets.collapsible import CollapsibleCard
from ..dialogs.nmtran import NMTRANPanel
from ..dialogs.run_record import RunRecordDialog
from ..dialogs.lst_viewer_dialog import LstViewerDialog
from ..app.model_templates import render as render_template

try:
    from ..parser import parse_lst, extract_table_files, inject_estimates
    HAS_PARSER = True
except ImportError:
    HAS_PARSER = False
    inject_estimates = None

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Model table
# ══════════════════════════════════════════════════════════════════════════════

COLS = ['*', 'Name', 'Description', 'OFV', 'dOFV', 'COV', 'AIC', 'CN', 'Method', 'Ind/Obs']
(COL_STAR, COL_NAME, COL_DESC, COL_OFV, COL_DOFV, COL_COV,
 COL_AIC, COL_CN, COL_METHOD, COL_INDOBS) = range(10)


class ModelTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._models = []; self._best_ofv = None; self._ref_path = None; self._ref_ofv = None

    def load(self, models):
        self.beginResetModel(); self._models = models
        ofvs = [m['ofv'] for m in models if m.get('ofv') is not None]
        self._best_ofv = min(ofvs) if ofvs else None
        # Refresh ref OFV in case model was re-run
        if self._ref_path:
            ref = next((m for m in models if m['path'] == self._ref_path), None)
            self._ref_ofv = ref['ofv'] if ref and ref.get('ofv') is not None else None
        self.endResetModel()

    def set_reference(self, model_path):
        """Set reference model for dOFV calculation. Pass None to revert to best model."""
        self._ref_path = model_path
        if model_path:
            ref = next((m for m in self._models if m['path'] == model_path), None)
            self._ref_ofv = ref['ofv'] if ref and ref.get('ofv') is not None else None
        else:
            self._ref_ofv = None
        # Only COL_NAME (REF suffix) and COL_DOFV change; emit dataChanged for
        # those columns instead of a full model reset. Note: this model is not
        # currently attached to a view via setModel() — _refresh_table_display()
        # in ModelsTab handles the actual table repaint — so the signal is
        # informational for any future view that may attach.
        n_rows = self.rowCount()
        if n_rows > 0:
            roles = [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.BackgroundRole,
                Qt.ItemDataRole.ForegroundRole,
            ]
            self.dataChanged.emit(
                self.index(0, COL_NAME),
                self.index(n_rows - 1, COL_NAME),
                roles,
            )
            self.dataChanged.emit(
                self.index(0, COL_DOFV),
                self.index(n_rows - 1, COL_DOFV),
                roles,
            )

    def _dofv_base(self):
        """Return (ofv_base, is_reference) for dOFV calculation."""
        if self._ref_path and self._ref_ofv is not None:
            return self._ref_ofv, True
        return self._best_ofv, False

    def rowCount(self, _=QModelIndex()): return len(self._models)
    def columnCount(self, _=QModelIndex()): return len(COLS)

    def headerData(self, s, o, role=Qt.ItemDataRole.DisplayRole):
        if o == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLS[s]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        m = self._models[index.row()]; col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_STAR:   return '*' if m.get('star') else ''
            if col == COL_NAME:
                s = m['stem']
                if m.get('stale'): s += ' !'
                if m.get('status_tag'): s += f" [{m['status_tag']}]"
                if m['path'] == self._ref_path: s += ' [REF]'
                return s
            if col == COL_DESC:   return m.get('comment', '')
            if col == COL_OFV:    return fmt_ofv(m.get('ofv'))
            if col == COL_COV:
                cv = m.get('covariance_step')
                return '' if cv is None else ('✓' if cv else '✗')
            if col == COL_DOFV:
                ofv = m.get('ofv')
                base, is_ref = self._dofv_base()
                if ofv is None or base is None: return ''
                if is_ref and m['path'] == self._ref_path: return 'REF'
                if not is_ref and abs(ofv - base) < 0.001: return '—'
                d = ofv - base
                return f'+{d:.3f}' if d > 0 else f'{d:.3f}'
            if col == COL_AIC:    return fmt_ofv(m.get('aic'))
            if col == COL_CN:
                cn = m.get('condition_number')
                if cn is None: return ''
                if cn >= 10000: return f'! {cn:.2e}'
                if cn >= 1000:  return f'! {cn:.0f}'
                return f'{cn:.1f}'
            if col == COL_METHOD: return m.get('estimation_method', '')
            if col == COL_INDOBS:
                ni = m.get('n_individuals')
                no = m.get('n_observations')
                if ni and no:  return f'{ni}/{no}'
                if ni:         return f'{ni}/—'
                if no:         return f'—/{no}'
                return ''
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STAR: return QBrush(QColor(C.star))
            if col == COL_NAME:
                if m.get('stale'): return QBrush(QColor(C.stale))
                msg = m.get('minimization_message') or ''
                if 'SUCCESSFUL' in msg or 'COMPLETED' in msg: return QBrush(QColor(C.green))
                if m.get('minimization_successful') is False: return QBrush(QColor(C.red))
                if m.get('boundary'): return QBrush(QColor(C.orange))
            if col == COL_COV:
                cv = m.get('covariance_step')
                if cv is True:  return QBrush(QColor(C.green))
                if cv is False: return QBrush(QColor(C.red))
            if col == COL_CN:
                cn = m.get('condition_number')
                if cn is None: return QBrush(QColor(C.fg2))
                if cn > 1000:  return QBrush(QColor(C.orange))
                return None
            if col == COL_DOFV:
                ofv = m.get('ofv')
                base, is_ref = self._dofv_base()
                if ofv is not None and base is not None:
                    if is_ref and m['path'] == self._ref_path:
                        return QBrush(QColor(C.blue))
                    if not is_ref and abs(ofv - base) < 0.001:
                        return QBrush(QColor(C.green))
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_NAME:
                tip = f"Path: {m['path']}"
                if m.get('problem'): tip += f"\n{m['problem']}"
                if m.get('based_on'): tip += f"\nBased on: {m['based_on']}"
                msg = m.get('minimization_message') or ''
                if msg: tip += f"\nStatus: {msg}"
                return tip
            if col == COL_COV and m.get('cov_failure_reason'): return m['cov_failure_reason']
            if col == COL_CN:
                cn = m.get('condition_number')
                if cn is None:
                    return 'Condition number not available.\nRequires successful $COV step with PRINT=E, or NONMEM versions that output it directly.'
                if cn > 1000:
                    return f'Condition number: {cn:.1f}\nWarning: CN > 1000 may indicate near-collinearity in the parameter space.'
                return f'Condition number: {cn:.1f}'
        return None

    def model_at(self, row): return self._models[row] if 0 <= row < len(self._models) else None


# ══════════════════════════════════════════════════════════════════════════════
# Models Tab
# ══════════════════════════════════════════════════════════════════════════════

class _ModelsTable(QTableWidget):
    """QTableWidget subclass — overrides contextMenuEvent so right-click
    is guaranteed to work via C++ virtual dispatch on all platforms."""
    right_clicked = pyqtSignal(int)   # emits row index in content coordinates

    def contextMenuEvent(self, event):
        # event.pos() is in viewport coordinates for QAbstractScrollArea subclasses.
        # QTableWidget.rowAt() accounts for the scroll offset internally.
        row = self.rowAt(event.pos().y())
        if row >= 0:
            self.right_clicked.emit(row)
        event.accept()   # prevent propagation


class ModelsTab(QWidget):
    model_selected     = pyqtSignal(dict)
    status_msg         = pyqtSignal(str)
    directory_changed  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory = load_settings().get('working_directory', str(HOME))
        self._meta = load_meta(); self._scan_worker = None
        self._run_popups: list[RunPopup] = []
        self._watch_popups: list[WatchLogPopup] = []   # WatchLogPopup tracker for theme refresh
        self._detached_runs: list[dict] = []   # live detached run descriptors
        self._run_records_cache: list = []     # per-folder history from nmgui_run_records.json
        self._last_detach_check = 0.0          # epoch of last is_alive check
        self._is_ssh = bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_CLIENT'))
        self._current_model = None
        self._ref_model_path = None     # user-selected reference for dOFV
        self._pending_select_path = None  # set by _new_model(); consumed in _on_scan
        self._table_model = ModelTableModel()
        self._all_models  = []
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(4,4,4,4); v.setSpacing(4)
        # Dir bar
        top = QHBoxLayout()
        self.dir_edit = QLineEdit(self._directory); self.dir_edit.returnPressed.connect(self._scan)
        browse = QPushButton('Browse…'); browse.clicked.connect(self._browse)
        scan   = QPushButton('Rescan'); scan.clicked.connect(self._scan)
        top.addWidget(QLabel('Directory:')); top.addWidget(self.dir_edit,1)
        top.addWidget(browse); top.addWidget(scan)
        v.addLayout(top)
        # Bookmark bar
        bm = QHBoxLayout()
        self.bm_combo = QComboBox(); self.bm_combo.setMinimumWidth(200)
        self.bm_combo.activated.connect(self._go_bookmark)
        add_bm = QPushButton('+ Bookmark'); add_bm.clicked.connect(self._add_bookmark)
        bm.addWidget(QLabel('Bookmarks:')); bm.addWidget(self.bm_combo); bm.addWidget(add_bm); bm.addStretch()
        v.addLayout(bm); self._refresh_bookmarks()
        # Splitter
        spl = QSplitter(Qt.Orientation.Horizontal)
        # Left: table
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(4)
        left.setMinimumWidth(320)

        # Filter row: search + buttons
        filter_row = QHBoxLayout(); filter_row.setSpacing(6)

        # Search field
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText('Filter models...')
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedHeight(24)
        self._search_edit.setFixedWidth(150)
        self._search_edit.setAccessibleName('Filter models by name')
        self._search_edit.textChanged.connect(self._on_search_changed)
        self._search_text = ''
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_filter_and_search)
        filter_row.addWidget(self._search_edit)

        # Filter buttons
        self._filter_btns = []
        for label, filter_val in [('All', 'all'), ('Completed', 'completed'), ('Failed', 'failed')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setObjectName('filterBtn')
            btn.clicked.connect(lambda checked, f=filter_val: self._apply_filter(f))
            filter_row.addWidget(btn)
            self._filter_btns.append((btn, filter_val))
        self._filter_btns[0][0].setChecked(True)  # 'All' selected by default
        self._current_filter = 'all'
        new_model_btn = QPushButton('New model…')
        new_model_btn.setFixedHeight(24)
        new_model_btn.setToolTip('Create a new blank NONMEM model file from a template (Ctrl+N / ⌘N)')
        new_model_btn.clicked.connect(self._new_model)
        workbench_btn = QPushButton('Workbench…')
        workbench_btn.setFixedHeight(24)
        workbench_btn.setToolTip('Multi-model comparison workbench (all completed models)')
        workbench_btn.clicked.connect(self._open_workbench)
        filter_row.addStretch()
        filter_row.addWidget(new_model_btn)
        filter_row.addWidget(workbench_btn)
        lv.addLayout(filter_row)

        self.table = _ModelsTable()
        self.table.setColumnCount(len(COLS)); self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_DESC, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_CN, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        # Column header tooltips
        _col_tips = {
            COL_STAR:   '*  Starred / flagged model',
            COL_NAME:   'Model name (stem of .mod file) — colour indicates minimization status',
            COL_DESC:   'Short description / comment from the Annotation panel',
            COL_OFV:    'Objective Function Value',
            COL_COV:    'Covariance step  (✓ successful  ✗ failed)',
            COL_DOFV:   'ΔOFV relative to the best model in this directory',
            COL_AIC:    'Akaike Information Criterion  =  OFV + 2k',
            COL_CN:     'Condition number — ratio of largest to smallest eigenvalue '
                        'of the correlation matrix.\nRequires $COV with PRINT=E or '
                        'a NONMEM version that outputs it directly.\nValues > 1000 '
                        'may indicate near-collinearity.',
            COL_METHOD: 'Estimation method  (FO, FOCE, FOCE-I, SAEM, SAEM→IMP, BAYES…)',
            COL_INDOBS: 'Number of individuals / observations',
        }
        for col, tip in _col_tips.items():
            item = self.table.horizontalHeaderItem(col)
            if item: item.setToolTip(tip)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        # Right-click handled by _ModelsTable.contextMenuEvent via C++ virtual dispatch
        self.table.right_clicked.connect(self._on_right_click)
        # Keyboard navigation only — no viewport filter needed
        self.table.installEventFilter(self)
        # Ctrl+N / ⌘N — only fires when this tab widget is visible
        from PyQt6.QtGui import QShortcut
        _sc = QShortcut(QKeySequence.StandardKey.New, self)
        _sc.activated.connect(self._new_model)
        lv.addWidget(self.table); spl.addWidget(left)
        # Prevent right panel from expanding at expense of model list

        # Right: detail panel with pill navigation
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(0)
        # Ignored = splitter ignores this widget's size hint completely.
        # Without this, loading content into the parameter table changes the size hint
        # and Qt silently adjusts the splitter — squashing the model list.
        right.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        # Pill strip
        detail_pill_bar = QWidget(); detail_pill_bar.setObjectName('pillBar')
        detail_pill_bar.setFixedHeight(38)
        dpl = QHBoxLayout(detail_pill_bar); dpl.setContentsMargins(8,5,8,5); dpl.setSpacing(4)
        self._detail_btns = []
        for i, lbl in enumerate(['Parameters','Editor','Run','Info','Output']):
            btn = QPushButton(lbl); btn.setObjectName('pillBtn')
            btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, n=i: self._detail_switch(n))
            dpl.addWidget(btn); self._detail_btns.append(btn)
        dpl.addStretch()
        rv.addWidget(detail_pill_bar)

        sep2 = QWidget(); sep2.setFixedHeight(1); sep2.setObjectName('hairlineSep')
        rv.addWidget(sep2)

        self._detail_stack = QStackedWidget()

        # 0 — Parameters
        self.param_table = ParameterTable()
        self._detail_stack.addWidget(self.param_table)

        # 1 — Editor
        ed_w = QWidget(); ed_v = QVBoxLayout(ed_w); ed_v.setContentsMargins(0,0,0,0)
        ed_top = QHBoxLayout(); ed_top.setContentsMargins(4,4,4,0)
        self.save_btn = QPushButton('Save'); self.save_btn.setObjectName('primary')
        self.save_btn.clicked.connect(self._save_model)
        self.lst_btn  = QPushButton('View .lst'); self.lst_btn.clicked.connect(self._view_lst)
        ed_top.addWidget(self.save_btn); ed_top.addWidget(self.lst_btn); ed_top.addStretch()
        self.editor = QPlainTextEdit()
        self.editor.setFont(monospace_font(11))
        self._apply_editor_palette()
        self._hl = NMHighlighter(self.editor.document())
        ed_v.addLayout(ed_top); ed_v.addWidget(self.editor)
        self._detail_stack.addWidget(ed_w)

        # 2 — Run
        run_w = QWidget(); run_v = QVBoxLayout(run_w); run_v.setContentsMargins(8,8,8,8)
        from PyQt6.QtWidgets import QFormLayout
        rf = QFormLayout(); rf.setVerticalSpacing(6); rf.setHorizontalSpacing(12)
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(['execute','vpc','bootstrap','scm','sir','cdd','npc','sse'])
        self.args_edit = QLineEdit(); self.args_edit.setPlaceholderText('-threads=4  -seed=12345')
        self.clean_cb  = QCheckBox('Clean previous run directory first'); self.clean_cb.setChecked(True)
        rf.addRow('PsN tool:', self.tool_combo); rf.addRow('Extra args:', self.args_edit)
        rf.addRow('', self.clean_cb)

        # Detach checkbox — POSIX only (Linux + macOS)
        if not IS_WIN:
            self.detach_cb = QCheckBox('Run detached  (survives SSH disconnect / NMGUI2 close)')
            self.detach_cb.setToolTip(
                'Runs nohup in a new session so the job keeps going if you\n'
                'close MobaXterm, disconnect SSH, or quit NMGUI2.\n'
                'Output is written to a .nmgui.log file in the project folder.\n'
                'Recommended for long runs (bootstrap, SCM, SIR) over SSH.'
            )
            # Always default to unchecked; user must opt in explicitly
            rf.addRow('', self.detach_cb)
        else:
            self.detach_cb = None

        run_v.addLayout(rf)

        # SSH info strip — shown when SSH session detected
        if self._is_ssh and not IS_WIN:
            ssh_strip = QLabel(
                'ℹ  SSH session detected — check "Run detached" to keep runs '
                'alive after disconnect.'
            )
            ssh_strip.setWordWrap(True)
            ssh_strip.setObjectName('muted')
            ssh_strip.setContentsMargins(0, 4, 0, 0)
            run_v.addWidget(ssh_strip)

        run_btn_row = QHBoxLayout(); run_btn_row.setSpacing(8)
        self.run_btn  = QPushButton('Run');  self.run_btn.setObjectName('primary')
        self.run_btn.clicked.connect(self._run_model)
        nmtran_btn = QPushButton('NMTRAN msgs…'); nmtran_btn.clicked.connect(self._show_nmtran)
        run_btn_row.addWidget(self.run_btn)
        run_btn_row.addWidget(nmtran_btn); run_btn_row.addStretch()
        run_v.addLayout(run_btn_row)

        # ── Active / recent runs table ────────────────────────────────────────
        _runs_lbl = QLabel('Active & recent runs')
        _runs_lbl.setObjectName('section')
        run_v.addSpacing(10)
        run_v.addWidget(_runs_lbl)

        self._run_list = QTableWidget(0, 4)
        self._run_list.setHorizontalHeaderLabels(['Model', 'Tool', 'Status', 'Time'])
        hh = self._run_list.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)           # Model
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Tool
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Status
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed);  hh.resizeSection(3, 52)  # Time
        self._run_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._run_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._run_list.verticalHeader().setVisible(False)
        self._run_list.setCornerButtonEnabled(False)
        self._run_list.setShowGrid(False)
        self._run_list.setAlternatingRowColors(False)
        self._run_list.setStyleSheet(
            'QTableWidget { border-radius: 0; }'
            'QHeaderView::section { border-radius: 0; }'
        )
        self._run_list.clicked.connect(self._raise_run_popup)
        run_v.addWidget(self._run_list, 1)

        _hint = QLabel('Click a live or detached row to view its output.')
        _hint.setObjectName('muted')
        run_v.addWidget(_hint)

        self._run_list.setVisible(False)   # hidden until first run starts

        self._run_list_timer = QTimer(self)
        self._run_list_timer.timeout.connect(self._refresh_run_list)
        self._run_list_timer.start(1000)

        self._detail_stack.addWidget(run_w)

        # 3 — Info  (collapsible cards inside a scroll area)
        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setFrameShape(info_scroll.Shape.NoFrame)
        info_inner = QWidget()
        info_v = QVBoxLayout(info_inner)
        info_v.setContentsMargins(8, 8, 8, 8)
        info_v.setSpacing(4)

        # ── Dataset card ──────────────────────────────────────────────────────
        self._card_dataset = CollapsibleCard('Dataset', expanded=True)
        self._ds_info = QLabel('No model selected')
        self._ds_info.setWordWrap(True)
        self._ds_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._card_dataset.add_widget(self._ds_info)
        info_v.addWidget(self._card_dataset)

        # ── Annotation card ───────────────────────────────────────────────────
        self._card_annot = CollapsibleCard('Annotation', expanded=True)

        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText('Comment / short label…')
        self.comment_edit.editingFinished.connect(self._save_meta_fields)
        self._card_annot.add_widget(self.comment_edit)

        combos_row = QHBoxLayout(); combos_row.setSpacing(8)
        self.status_tag_combo = QComboBox()
        self.status_tag_combo.addItems(['', 'base', 'candidate', 'final'])
        self.status_tag_combo.setToolTip('Status')
        self.status_tag_combo.setMinimumWidth(110)
        self.status_tag_combo.currentTextChanged.connect(self._save_meta_fields)
        self.decision_combo = QComboBox()
        self.decision_combo.addItems(['', 'Include', 'Sensitivity', 'Exploratory', 'Rejected'])
        self.decision_combo.setToolTip('Decision — categorize model for reporting/submission')
        self.decision_combo.setMinimumWidth(130)
        self.decision_combo.currentTextChanged.connect(self._save_meta_fields)
        st_lbl = QLabel('Status:'); st_lbl.setObjectName('muted')
        de_lbl = QLabel('Decision:'); de_lbl.setObjectName('muted')
        combos_row.addWidget(st_lbl); combos_row.addWidget(self.status_tag_combo)
        combos_row.addSpacing(12)
        combos_row.addWidget(de_lbl); combos_row.addWidget(self.decision_combo)
        combos_row.addStretch()
        self._card_annot.add_layout(combos_row)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText('Tags (comma-separated): pediatric, renal, covariate…')
        self.tags_edit.setToolTip('Add tags for filtering and search')
        self.tags_edit.editingFinished.connect(self._save_meta_fields)
        self._card_annot.add_widget(self.tags_edit)
        info_v.addWidget(self._card_annot)

        # ── Notes card ────────────────────────────────────────────────────────
        self._card_notes = CollapsibleCard('Notes', expanded=True)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText('Rationale, decisions…')
        self.notes_edit.setFixedHeight(120)
        self._apply_notes_palette()
        orig_focusOut = self.notes_edit.focusOutEvent
        self.notes_edit.focusOutEvent = lambda e: (self._save_meta_fields(), orig_focusOut(e))
        self._card_notes.add_widget(self.notes_edit)
        info_v.addWidget(self._card_notes)

        info_v.addStretch()
        info_scroll.setWidget(info_inner)
        self._detail_stack.addWidget(info_scroll)

        # 4 — Output (.lst viewer)
        self.lst_output = LstOutputWidget()
        self._detail_stack.addWidget(self.lst_output)

        rv.addWidget(self._detail_stack, 1)
        spl.addWidget(right)
        spl.setSizes([620, 380])
        spl.setStretchFactor(0, 1)   # left grows with window
        spl.setStretchFactor(1, 0)   # right stays fixed
        spl.setCollapsible(0, False)  # left never collapses
        v.addWidget(spl,1)
        self._detail_switch(0)
        QTimer.singleShot(200, self._scan)

    def _detail_switch(self, index):
        self._detail_stack.setCurrentIndex(index)
        for i, btn in enumerate(self._detail_btns):
            btn.setChecked(i == index)

    # ── Theme ─────────────────────────────────────────────────────────────────
    def _apply_editor_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, QColor(T('bg2')))
        pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        self.editor.setPalette(pal)

    def _apply_notes_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, QColor(T('bg2')))
        pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        self.notes_edit.setPalette(pal)

    def refresh_theme(self):
        """Re-apply theme-dependent palettes after a global theme switch.
        Called from MainWindow._apply_theme()."""
        self._apply_editor_palette()
        self._apply_notes_palette()

    # ── Bookmarks ──────────────────────────────────────────────────────────────
    def _refresh_bookmarks(self):
        self.bm_combo.clear(); self.bm_combo.addItem('— jump to bookmark —')
        for b in load_bookmarks(): self.bm_combo.addItem(b.get('name',''), b.get('path',''))
    def _go_bookmark(self, idx):
        if idx == 0: return
        path = self.bm_combo.itemData(idx)
        if path: self.dir_edit.setText(path); self._scan()
    def _add_bookmark(self):
        path = self.dir_edit.text().strip()
        if not Path(path).is_dir(): QMessageBox.warning(self,'Invalid','Directory does not exist.'); return
        name, ok = QInputDialog.getText(self,'Bookmark','Name:', text=Path(path).name)
        if not ok or not name: return
        bms = [b for b in load_bookmarks() if b.get('path') != path]
        bms.append({'path':path,'name':name,'description':''})
        save_bookmarks(bms); self._refresh_bookmarks()

    # ── Scan ──────────────────────────────────────────────────────────────────
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self,'Select directory', self._directory)
        if d: self.dir_edit.setText(d); self._scan()
    def _scan(self):
        d = self.dir_edit.text().strip()
        if not Path(d).is_dir(): self.status_msg.emit(f'Not a directory: {d}'); return
        # New directory — reset state
        if d != self._directory:
            self._ref_model_path = None
        self._directory = d; s = load_settings(); s['working_directory'] = d; save_settings(s)
        self.directory_changed.emit(d)
        self._run_records_cache = load_run_records(d)[:30]
        # Reconcile detached runs from previous sessions; reload live descriptors
        if not IS_WIN:
            try:
                still_running, just_finished = _dr.reconcile(d)
                # Merge still_running into _detached_runs (avoid duplicates by run_id)
                known_ids = {x['run_id'] for x in self._detached_runs}
                for desc in still_running:
                    if desc['run_id'] not in known_ids:
                        self._detached_runs.append(desc)
                        known_ids.add(desc['run_id'])
                if just_finished:
                    self._run_records_cache = load_run_records(d)[:30]
                    n = len(just_finished)
                    self.status_msg.emit(
                        f'Reconciled {n} detached run{"s" if n > 1 else ""} '
                        f'that finished since last session.'
                    )
                    QTimer.singleShot(1500, self._scan)
            except Exception as e:
                _log.debug('Detached run reconciliation error: %s', e)
        self._refresh_run_list()
        self._meta = load_meta(); self.status_msg.emit('Scanning…'); self.table.setRowCount(0)
        # Reset right panel
        self._current_model = None
        self.param_table.table.setRowCount(0)
        self.editor.clear()
        self.comment_edit.clear()
        self.notes_edit.clear()
        self.lst_output._browser.clear()
        self.lst_output._status_lbl.setText('No model selected')
        self.lst_output._browser_btn.setEnabled(False)
        # Terminate any in-flight scan before starting a new one
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.result.disconnect()
            self._scan_worker.cancel()  # Cooperative cancellation
            self._scan_worker.wait(500)  # Wait up to 500ms
        w = ScanWorker(d, self._meta)
        w.result.connect(self._on_scan)
        w.error.connect(lambda e: self.status_msg.emit(f'Scan error: {e}'))
        self._scan_worker = w; w.start()

    def _on_scan(self, models):
        t0 = time.time()
        self._all_models = models; self._table_model.load(models)
        self.table.setRowCount(len(models)); self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        try:
            for row, m in enumerate(models):
                for col in range(len(COLS)):
                    idx = self._table_model.index(row, col)
                    txt = self._table_model.data(idx, Qt.ItemDataRole.DisplayRole) or ''
                    fg  = self._table_model.data(idx, Qt.ItemDataRole.ForegroundRole)
                    tip = self._table_model.data(idx, Qt.ItemDataRole.ToolTipRole)
                    item = QTableWidgetItem(txt)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                        (Qt.AlignmentFlag.AlignRight if col >= COL_OFV else Qt.AlignmentFlag.AlignLeft))
                    if fg:  item.setForeground(fg)
                    if tip: item.setToolTip(tip)
                    if col == 0: item.setData(Qt.ItemDataRole.UserRole, row)
                    self.table.setItem(row, col, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True); self.table.resizeColumnsToContents()
        hh = self.table.horizontalHeader()
        for c in range(len(COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        if self.table.columnWidth(COL_DESC) < 120:
            self.table.setColumnWidth(COL_DESC, 120)
        n = len(models); nr = sum(1 for m in models if m['has_run'])
        elapsed = time.time() - t0
        self.status_msg.emit(
            f'{n} model{"s" if n!=1 else ""}, {nr} with results  ·  '
            f'{Path(self._directory).name}  ·  scanned in {elapsed:.1f}s')

        # Auto-select a newly created model (set by _new_model())
        if self._pending_select_path:
            target = self._pending_select_path
            self._pending_select_path = None
            # Make sure 'All' filter is active so the new (unrun) model is visible
            self._apply_filter('all')
            for row in range(self.table.rowCount()):
                item0 = self.table.item(row, 0)
                if item0 is None:
                    continue
                model_row = item0.data(Qt.ItemDataRole.UserRole)
                m = self._table_model.model_at(model_row) if model_row is not None else None
                if m and m.get('path') == target:
                    self.table.setCurrentCell(row, 0)
                    self._on_select()
                    self._detail_switch(1)   # 1 = Editor tab — user can start editing immediately
                    break

    def _on_search_changed(self, text):
        """Handle search text changes with debounce."""
        self._search_text = text.strip().lower()
        self._search_timer.start(80)  # 80ms debounce

    def _apply_filter_and_search(self):
        """Apply both status filter and search filter."""
        self._apply_filter(self._current_filter)

    def _apply_filter(self, filter_type):
        """Filter the model list by status and search text."""
        self._current_filter = filter_type
        # Update button states
        for btn, val in self._filter_btns:
            btn.setChecked(val == filter_type)

        # Filter by status
        if filter_type == 'all':
            filtered = self._all_models
        elif filter_type == 'completed':
            filtered = [m for m in self._all_models if m.get('minimization_successful') is True]
        elif filter_type == 'failed':
            filtered = [m for m in self._all_models if m.get('minimization_successful') is False
                       or (m.get('has_run') and m.get('minimization_successful') is None)]
        else:
            filtered = self._all_models

        # Filter by search text (searches stem, comment, tags, decision, notes)
        if self._search_text:
            def matches_search(m):
                search = self._search_text
                if search in m.get('stem', '').lower():
                    return True
                # Search in meta fields
                meta_e = get_meta_entry(self._meta, m.get('path', ''))
                if search in meta_e.get('comment', '').lower():
                    return True
                if search in meta_e.get('decision', '').lower():
                    return True
                if search in meta_e.get('notes', '').lower():
                    return True
                for tag in meta_e.get('tags', []):
                    if search in tag.lower():
                        return True
                return False
            filtered = [m for m in filtered if matches_search(m)]

        # Repopulate table
        self._table_model.load(filtered)
        self.table.setRowCount(len(filtered)); self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        try:
            for row, m in enumerate(filtered):
                for col in range(len(COLS)):
                    idx = self._table_model.index(row, col)
                    txt = self._table_model.data(idx, Qt.ItemDataRole.DisplayRole) or ''
                    fg  = self._table_model.data(idx, Qt.ItemDataRole.ForegroundRole)
                    tip = self._table_model.data(idx, Qt.ItemDataRole.ToolTipRole)
                    item = QTableWidgetItem(txt)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                        (Qt.AlignmentFlag.AlignRight if col >= COL_OFV else Qt.AlignmentFlag.AlignLeft))
                    if fg:  item.setForeground(fg)
                    if tip: item.setToolTip(tip)
                    if col == 0: item.setData(Qt.ItemDataRole.UserRole, row)
                    self.table.setItem(row, col, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)

        # Update status bar
        n_total = len(self._all_models)
        n_shown = len(filtered)
        if self._search_text:
            self.status_msg.emit(f'{n_shown} model{"s" if n_shown!=1 else ""} matching "{self._search_text}"')
        elif filter_type == 'all':
            self.status_msg.emit(f'{n_shown} model{"s" if n_shown!=1 else ""}')
        else:
            self.status_msg.emit(f'{n_shown} of {n_total} models ({filter_type})')

    # ── Selection ─────────────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        """Keyboard navigation on the models table."""
        from PyQt6.QtCore import QEvent
        if obj is self.table and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            row = self.table.currentRow()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._detail_switch(4); return True
            elif key == Qt.Key.Key_Space:
                self._toggle_star(); return True
            elif key == Qt.Key.Key_Up:
                if row > 0:
                    self.table.setCurrentCell(row - 1, self.table.currentColumn())
                return True
            elif key == Qt.Key.Key_Down:
                if row < self.table.rowCount() - 1:
                    self.table.setCurrentCell(row + 1, self.table.currentColumn())
                return True
        return super().eventFilter(obj, event)

    def _on_double_click(self, item):
        """Open the .lst file in the system default application."""
        row = item.row()
        item0 = self.table.item(row, 0)
        if item0 is None: return
        model_row = item0.data(Qt.ItemDataRole.UserRole)
        if model_row is None: model_row = row
        m = self._table_model.model_at(model_row)
        if not m: return

        # Try .lst file first, fall back to .mod
        lst_path = m.get('lst_path')
        if lst_path and Path(lst_path).exists():
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(lst_path)))
            self.status_msg.emit(f'Opened: {Path(lst_path).name}')
        elif m.get('path') and Path(m['path']).exists():
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(m['path'])))
            self.status_msg.emit(f'Opened: {Path(m["path"]).name} (no .lst file)')
        else:
            self.status_msg.emit('No output file available')

    def _on_right_click(self, row):
        """Called by _ModelsTable.contextMenuEvent via C++ virtual dispatch."""
        item0 = self.table.item(row, 0)
        if item0 is None: return
        model_row = item0.data(Qt.ItemDataRole.UserRole)
        if model_row is None: model_row = row
        m = self._table_model.model_at(model_row)
        if not m: return
        self.table.selectRow(row)
        self._current_model = m
        self._ctx_menu()

    def _on_select(self):
        row = self.table.currentRow()
        if row < 0: return
        item0 = self.table.item(row, 0)
        if item0 is None: return
        model_row = item0.data(Qt.ItemDataRole.UserRole)
        if model_row is None: model_row = row
        m = self._table_model.model_at(model_row)
        if m is None: return
        self._current_model = m; self._load_detail(m); self.model_selected.emit(m)
        # Feed the Output panel whenever a model is selected
        self.lst_output.load_model(m)

    def _load_detail(self, m):
        m = _align_param_names(m)  # fix misaligned omega/sigma names from SAME blocks

        # Find parent model if based_on is specified
        parent_model = None
        based_on = m.get('based_on')
        if based_on:
            # Search for parent model in _all_models by stem
            parent_stem = based_on.replace('.mod', '').replace('.ctl', '')
            for candidate in self._all_models:
                if candidate.get('stem') == parent_stem:
                    parent_model = _align_param_names(candidate)
                    break

        self.param_table.load(m, parent_model)
        try: self.editor.setPlainText(Path(m['path']).read_text('utf-8', errors='replace'))
        except Exception: self.editor.setPlainText('')
        meta_e = get_meta_entry(self._meta, m['path'])
        self.comment_edit.setText(meta_e['comment'])
        self.notes_edit.setPlainText(meta_e['notes'])
        idx = self.status_tag_combo.findText(meta_e['status'])
        self.status_tag_combo.setCurrentIndex(max(0, idx))
        # Load annotation fields
        decision_idx = self.decision_combo.findText(meta_e.get('decision', ''))
        self.decision_combo.setCurrentIndex(max(0, decision_idx))
        tags = meta_e.get('tags', [])
        self.tags_edit.setText(', '.join(tags) if tags else '')

        # Dataset info
        data_file = m.get('data_file', '')
        n_ind = m.get('n_individuals')
        n_obs = m.get('n_observations')

        ds_parts = []
        if data_file:
            ds_parts.append(f'File: {data_file}')
        if n_ind:
            ds_parts.append(f'Individuals: {n_ind:,}')
        if n_obs:
            ds_parts.append(f'Observations: {n_obs:,}')
        if based_on:
            ds_parts.append(f'Based on: {based_on}')

        # Get $INPUT columns if available
        try:
            content = Path(m['path']).read_text('utf-8', errors='replace')
            input_match = re.search(r'\$INPUT\s+(.+?)(?:\$|;|\n\s*\n)', content, re.DOTALL | re.IGNORECASE)
            if input_match:
                cols = re.findall(r'([A-Z][A-Z0-9_]*)', input_match.group(1).upper())
                cols = [c for c in cols if c not in ('DROP', 'SKIP')]
                if cols:
                    ds_parts.append(f'Columns: {", ".join(cols[:10])}{"..." if len(cols) > 10 else ""}')
        except Exception:
            pass

        # Dataset integrity report (Phase 3)
        dr = m.get('dataset_report')
        if dr is not None:
            if dr.found and dr.readable and dr.n_rows:
                ds_parts.append(
                    f'Rows: {dr.n_rows:,}{"+" if dr.truncated else ""}  '
                    f'IDs: {dr.n_ids:,}  '
                    f'Obs: {dr.n_obs:,}  '
                    f'Doses: {dr.n_doses:,}'
                    + (f'  BLQ: {dr.n_blq:,}' if dr.n_blq else ''))
            _level_prefix = {'fail': '[X]', 'warn': '[!]', 'info': '[i]', 'pass': '[OK]'}
            for issue in dr.issues:
                pfx = _level_prefix.get(issue.level, '[?]')
                cnt = f' ({issue.count:,} rows)' if issue.count else ''
                ds_parts.append(f'{pfx} {issue.message}{cnt}')

        if ds_parts:
            self._ds_info.setText('\n'.join(ds_parts))
        else:
            self._ds_info.setText('No dataset information available')

    # ── Context menu ──────────────────────────────────────────────────────────
    def _ctx_menu(self):
        from PyQt6.QtGui import QCursor
        m = self._current_model
        if not m: return
        menu = QMenu(self)
        menu.addAction('Run', self._run_model)
        menu.addSeparator()
        menu.addAction('* Toggle star', self._toggle_star)
        menu.addAction('Duplicate…', self._duplicate)
        menu.addSeparator()
        is_ref = (m['path'] == self._ref_model_path)
        if is_ref:
            menu.addAction('[x] Clear reference model', self._clear_reference)
        else:
            menu.addAction('( ) Set as reference model', self._set_reference)
        if len(self._all_models) > 1:
            comp_menu = menu.addMenu('Compare with…')
            for other in self._all_models:
                if other['path'] != m['path'] and other.get('has_run'):
                    act = comp_menu.addAction(other['stem'])
                    act.triggered.connect(lambda _, o=other: self._compare(m, o))
        menu.addSeparator()
        menu.addAction('Copy .mod path', self._copy_mod_path)
        menu.addAction('Copy folder path', self._copy_folder_path)
        menu.addAction('Open folder', self._open_folder)
        menu.addSeparator()
        menu.addAction('View .lst', self._view_lst)
        if m.get('has_run'):
            menu.addAction('View .ext', self._view_ext)
        menu.addAction('View run record…', self._view_run_record)
        menu.addAction('NMTRAN messages…', self._show_nmtran)
        menu.addSeparator()
        if m.get('has_run'):
            menu.addAction('QC Report…', self._open_qc_report)
            menu.addAction('Run Report…', self._open_run_report)
        if len([x for x in self._all_models if x.get('has_run')]) > 1:
            menu.addSeparator()
            menu.addAction('Workbench…', self._open_workbench)
        menu.addSeparator()
        menu.addAction('Delete…', self._delete_model)
        menu.exec(QCursor.pos())

    def _copy_mod_path(self):
        m = self._current_model
        if not m or not m.get('path'): return
        QApplication.clipboard().setText(str(m['path']))
        self.status_msg.emit(f'Copied: {m["path"]}')

    def _copy_folder_path(self):
        m = self._current_model
        if not m or not m.get('path'): return
        folder = str(Path(m['path']).parent)
        QApplication.clipboard().setText(folder)
        self.status_msg.emit(f'Copied: {folder}')

    def _open_folder(self):
        m = self._current_model
        if not m or not m.get('path'): return
        folder = str(Path(m['path']).parent)
        try:
            if IS_WIN:
                import os; os.startfile(folder)
            elif IS_MAC:
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except Exception as e:
            QMessageBox.warning(self, 'Open folder', str(e))

    def _set_reference(self):
        m = self._current_model
        if not m: return
        self._ref_model_path = m['path']
        self._table_model.set_reference(m['path'])
        self._refresh_table_display()
        self.status_msg.emit(f'Reference model: {m["stem"]}  — dOFV now relative to this model')

    def _clear_reference(self):
        self._ref_model_path = None
        self._table_model.set_reference(None)
        self._refresh_table_display()
        self.status_msg.emit('Reference cleared — dOFV relative to best model')

    def _compare(self, model_a, model_b):
        model_a = _align_param_names(model_a)
        model_b = _align_param_names(model_b)
        dlg = ModelComparisonDialog(model_a, model_b, self)
        dlg.exec()

    def _open_workbench(self):
        completed = [m for m in self._all_models if m.get('has_run')]
        if len(completed) < 2:
            QMessageBox.information(self, 'Workbench',
                'At least two completed models are needed for the workbench.')
            return
        ref = self._current_model if self._current_model else None
        dlg = ModelWorkbenchDialog(completed, ref_path=ref.get('path') if ref else None, parent=self)
        dlg.exec()

    def _open_qc_report(self):
        m = self._current_model
        if not m: return
        try:
            html = generate_qc_html(m)
            open_report_in_browser(html, stem=m.get('stem', 'model'), prefix='nmgui_qc')
            self.status_msg.emit(f'QC report opened: {m["stem"]}')
        except Exception as e:
            QMessageBox.warning(self, 'QC Report', f'Could not generate report:\n{e}')

    def _open_run_report(self):
        m = self._current_model
        if not m: return
        try:
            html = generate_html_report(m)
            open_report_in_browser(html, stem=m.get('stem', 'model'), prefix='nmgui_run')
            self.status_msg.emit(f'Run report opened: {m["stem"]}')
        except Exception as e:
            QMessageBox.warning(self, 'Run Report', f'Could not generate report:\n{e}')

    def _refresh_table_display(self):
        """Refresh Name and dOFV columns in the table without a full rescan."""
        self.table.setSortingEnabled(False)
        for row in range(self.table.rowCount()):
            item0 = self.table.item(row, 0)
            if item0 is None: continue
            model_row = item0.data(Qt.ItemDataRole.UserRole)
            if model_row is None: continue  # item not properly initialised, skip
            for col in (COL_NAME, COL_DOFV):
                idx = self._table_model.index(model_row, col)
                txt = self._table_model.data(idx, Qt.ItemDataRole.DisplayRole) or ''
                fg  = self._table_model.data(idx, Qt.ItemDataRole.ForegroundRole)
                item = self.table.item(row, col)
                if item:
                    item.setText(txt)
                    if fg: item.setForeground(fg)
        self.table.setSortingEnabled(True)

    def _toggle_star(self):
        m = self._current_model
        if not m: return
        self._meta = load_meta(); e = get_meta_entry(self._meta, m['path'])
        e['star'] = not e['star']; self._meta[m['path']] = e
        save_meta(self._meta); self._scan()

    def _view_lst(self):
        m = self._current_model
        if not m or not m.get('lst_path'): return
        try:
            text = Path(m['lst_path']).read_text('utf-8', errors='replace')
        except Exception as e:
            QMessageBox.warning(self, 'Error', str(e)); return
        dlg = LstViewerDialog(m['stem'], text, self)
        dlg.show()  # non-modal so user can keep working

    def _view_ext(self):
        m = self._current_model
        if not m: return
        ext_path = Path(m['path']).with_suffix('.ext')
        if not ext_path.is_file():
            sub = Path(m['path']).parent / m['stem'] / (m['stem'] + '.ext')
            if sub.is_file():
                ext_path = sub
            else:
                QMessageBox.information(self, 'View .ext', f'No .ext file found for {m["stem"]}.')
                return
        try:
            text = ext_path.read_text('utf-8', errors='replace')
        except Exception as e:
            QMessageBox.warning(self, 'Error', str(e)); return
        dlg = LstViewerDialog(f'{m["stem"]}.ext', text, self)
        dlg.show()

    def _view_run_record(self):
        m = self._current_model
        if not m: return
        cwd = str(Path(m['path']).parent)
        records = load_run_records(cwd)
        # Find most recent record for this model
        model_stem = m.get('stem', '')
        matching = [r for r in records if r.get('model_stem') == model_stem]
        if not matching:
            QMessageBox.information(self, 'No Record',
                f'No run record found for {model_stem}.\n\n'
                'Run records are created when you execute a model through NMGUI.')
            return
        # Show the most recent record
        dlg = RunRecordDialog(matching[0], self)
        dlg.exec()

    def current_directory(self):
        return self._directory

    def _show_nmtran(self):
        m = self._current_model
        if not m: return
        dlg = NMTRANPanel(m, self); dlg.exec()

    def _delete_model(self):
        import shutil
        m = self._current_model
        if not m: return
        stem = m['stem']
        mod_path = Path(m['path'])
        folder = mod_path.parent

        # Parse $DATA to identify the dataset — never delete it
        dataset_path = None
        try:
            content = mod_path.read_text('utf-8', errors='replace')
            ds_match = re.search(r'^\s*\$DATA\s+(\S+)', content, re.MULTILINE | re.IGNORECASE)
            if ds_match:
                raw = ds_match.group(1)
                dp = Path(raw) if Path(raw).is_absolute() else (folder / raw).resolve()
                if dp.is_file():
                    dataset_path = dp.resolve()
        except Exception:
            pass

        to_delete = [
            f for f in folder.iterdir()
            if f.is_file() and f.stem == stem
            and (dataset_path is None or f.resolve() != dataset_path)
        ]
        sub_dir = folder / stem

        names = sorted(f.name for f in to_delete)
        if sub_dir.is_dir():
            names.append(f'{stem}/ (directory)')
        if not names:
            QMessageBox.information(self, 'Delete', 'No files found to delete.')
            return

        detail = '\n'.join(names)
        if dataset_path:
            detail += '\n\n(Dataset file excluded)'
        reply = QMessageBox.question(
            self, 'Confirm Delete',
            f'Delete {stem} and all associated files?\n\n{detail}',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes: return

        errors = []
        for f in to_delete:
            try: f.unlink()
            except Exception as e: errors.append(f'{f.name}: {e}')
        if sub_dir.is_dir():
            try: shutil.rmtree(sub_dir)
            except Exception as e: errors.append(f'{stem}/: {e}')

        if errors:
            QMessageBox.warning(self, 'Delete', 'Some files could not be deleted:\n' + '\n'.join(errors))
        else:
            self.status_msg.emit(f'Deleted {stem}')
        self._current_model = None
        self._scan()

    # ── Save / duplicate ──────────────────────────────────────────────────────
    def _save_model(self):
        m = self._current_model
        if not m: return
        try: Path(m['path']).write_text(self.editor.toPlainText(), 'utf-8'); self.status_msg.emit(f"Saved {m['name']}")
        except Exception as e: QMessageBox.critical(self,'Error',str(e))

    def _save_meta_fields(self):
        m = self._current_model
        if not m: return
        self._meta = load_meta(); e = get_meta_entry(self._meta, m['path'])
        e['comment'] = self.comment_edit.text().strip()
        e['notes']   = self.notes_edit.toPlainText().strip()
        e['status']  = self.status_tag_combo.currentText()
        # Annotation fields
        e['decision'] = self.decision_combo.currentText()
        tags_text = self.tags_edit.text().strip()
        e['tags'] = [t.strip() for t in tags_text.split(',') if t.strip()] if tags_text else []
        self._meta[m['path']] = e; save_meta(self._meta)

    def _new_model(self):
        """Create a new blank NONMEM model file from a template."""
        if not self._directory or not Path(self._directory).is_dir():
            self.status_msg.emit('Set a working directory before creating a new model.')
            return
        dlg = NewModelDialog(self._directory, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        stem      = dlg.stem()
        text      = render_template(dlg.template(), stem, dlg.data_path())
        out_path  = Path(self._directory) / f'{stem}.mod'
        if out_path.exists():
            reply = QMessageBox.question(
                self, 'File already exists',
                f'{stem}.mod already exists in this directory.\nOverwrite it?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            out_path.write_text(text, encoding='utf-8')
        except OSError as e:
            QMessageBox.warning(self, 'Could not create file', str(e))
            return
        self.status_msg.emit(f'Created {stem}.mod — rescanning…')
        # Store path so _on_scan() can auto-select and open the editor
        self._pending_select_path = str(out_path)
        self._scan()

    def _duplicate(self):
        m = self._current_model
        if not m: return
        dlg = DuplicateDialog(m['stem'], self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        new_name = dlg.name_edit.text().strip()
        if not new_name.endswith(('.mod','.ctl')): new_name += '.mod'
        dst = Path(m['path']).parent / new_name
        if dst.exists(): QMessageBox.warning(self,'Exists',f'{new_name} already exists.'); return
        try:
            content = Path(m['path']).read_text('utf-8', errors='replace')
            if dlg.use_est.isChecked() and m.get('lst_path') and inject_estimates is not None:
                content = inject_estimates(content, m['lst_path'], jitter=dlg.jitter_sb.value())
            dst.write_text(content, 'utf-8')
            meta_e = get_meta_entry(self._meta, dst)
            meta_e['based_on'] = m['stem']; self._meta[str(dst)] = meta_e; save_meta(self._meta)
            self.status_msg.emit(f'Created {new_name}'); self._scan()
        except Exception as e: QMessageBox.critical(self,'Error',str(e))

    # ── Run ──────────────────────────────────────────────────────────────────
    def _run_model(self):
        m = self._current_model
        if not m: return
        tool = self.tool_combo.currentText(); tool_path = find_tool(tool)
        if not tool_path: QMessageBox.warning(self,'Not found',f'"{tool}" not found. Is PsN on PATH?'); return
        model_path = m['path']; cwd = str(Path(model_path).parent)
        q = shlex.quote; cmd = f'{q(tool_path)} {q(model_path)}'
        if tool == 'execute': cmd += f' -directory={m["stem"]}'
        extra = self.args_edit.text().strip()
        if extra: cmd += ' ' + extra
        if self.clean_cb.isChecked():
            import shutil; rd = Path(cwd)/m['stem']
            if rd.is_dir():
                try: shutil.rmtree(rd)
                except Exception as e: QMessageBox.warning(self,'Clean failed',str(e)); return

        if self.detach_cb is not None and self.detach_cb.isChecked():
            # ── Detached path ─────────────────────────────────────────────────
            try:
                descriptor = _dr.start_detached(cmd, cwd, m['stem'], tool, model_path)
            except Exception as e:
                QMessageBox.critical(self, 'Launch failed', str(e)); return
            self._detached_runs.append(descriptor)
            self._run_records_cache = load_run_records(cwd)[:30]
            self._refresh_run_list()
            log_name = Path(descriptor['log_file']).name
            self.status_msg.emit(f'{m["stem"]}: detached run started  ·  log: {log_name}')
        else:
            # ── Live popup path ───────────────────────────────────────────────
            popup = RunPopup(m['stem'], tool, cmd, cwd, model_path, parent=None)
            popup.run_completed.connect(self._on_popup_done)
            self._run_popups.append(popup)
            popup.destroyed.connect(lambda p=popup: self._run_popups.remove(p) if p in self._run_popups else None)
            popup.destroyed.connect(self._refresh_run_list)
            popup.show()
            self._refresh_run_list()

    def _on_popup_done(self, stem: str, cwd: str, rc: int):
        s = 'finished' if rc == 0 else f'failed (code {rc})'
        self.status_msg.emit(f'{stem}: run {s}')
        self._run_records_cache = load_run_records(cwd)[:30]
        self._refresh_run_list()
        QTimer.singleShot(1500, self._scan)

    def _refresh_run_list(self):
        R  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
        C_ = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

        def _item(text, fg=None, align=None):
            it = QTableWidgetItem(text)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if fg:    it.setForeground(QBrush(QColor(fg)))
            if align: it.setTextAlignment(align)
            return it

        def _fmt_secs(secs):
            if secs is None: return ''
            m2, s = divmod(int(secs), 60); h, m2 = divmod(m2, 60)
            return f'{h}:{m2:02d}:{s:02d}' if h else f'{m2}:{s:02d}'

        # Periodically prune finished detached runs (every ~30s)
        now = time.time()
        if not IS_WIN and (now - self._last_detach_check) > 30:
            self._last_detach_check = now
            alive = []
            any_done = False
            for d in self._detached_runs:
                if _dr.is_alive(d['pid'], d.get('started_epoch')):
                    alive.append(d)
                else:
                    any_done = True
            self._detached_runs = alive
            if any_done:
                self._run_records_cache = load_run_records(self._directory)[:30]

        # Sets used to de-duplicate historical rows
        live_ids     = {getattr(p, '_run_record', {}).get('run_id')
                        for p in self._run_popups if getattr(p, '_run_record', None)}
        detached_ids = {d['run_id'] for d in self._detached_runs}
        all_live_ids = live_ids | detached_ids

        historical = [r for r in self._run_records_cache
                      if r.get('run_id') not in all_live_ids]

        n_live     = len(self._run_popups)
        n_detached = len(self._detached_runs)
        total      = n_live + n_detached + len(historical)
        self._run_list.setRowCount(total)

        # ── Live popup rows ───────────────────────────────────────────────────
        for row, popup in enumerate(self._run_popups):
            finished = getattr(popup, '_finished', False)
            elapsed  = getattr(popup, '_elapsed', 0)
            if finished:
                ok = getattr(popup._status_lbl, 'text', lambda: '')().startswith('✓')
                status_txt, status_col = ('✓  Done', C.green) if ok else ('✗  Failed', C.red)
            else:
                status_txt, status_col = '●  Running', T('accent')
            self._run_list.setItem(row, 0, _item(popup.stem))
            self._run_list.setItem(row, 1, _item(popup.tool,        fg=T('fg2'), align=C_))
            self._run_list.setItem(row, 2, _item(status_txt,        fg=status_col))
            self._run_list.setItem(row, 3, _item(_fmt_secs(elapsed), fg=T('fg2'), align=R))

        # ── Live detached rows ────────────────────────────────────────────────
        for i, desc in enumerate(self._detached_runs):
            row = n_live + i
            elapsed = int(now) - desc.get('started_epoch', int(now))
            self._run_list.setItem(row, 0, _item(desc['stem']))
            self._run_list.setItem(row, 1, _item(desc['tool'],           fg=T('fg2'), align=C_))
            self._run_list.setItem(row, 2, _item('◌  Running (detached)', fg=T('accent')))
            self._run_list.setItem(row, 3, _item(_fmt_secs(elapsed),      fg=T('fg2'), align=R))

        # ── Historical record rows ────────────────────────────────────────────
        for i, rec in enumerate(historical):
            row = n_live + n_detached + i
            st  = rec.get('status', '')
            if st == 'completed':
                status_txt, status_col = '✓  Done',        C.green
            elif st in ('running', 'detached'):
                status_txt, status_col = '?  Interrupted', T('orange')
            elif st == 'interrupted':
                status_txt, status_col = '?  Interrupted', T('orange')
            else:
                status_txt, status_col = '✗  Failed',      C.red
            fg_dim = T('fg2')
            self._run_list.setItem(row, 0, _item(rec.get('model_stem', ''), fg=fg_dim))
            self._run_list.setItem(row, 1, _item(rec.get('tool', ''),       fg=fg_dim, align=C_))
            self._run_list.setItem(row, 2, _item(status_txt, fg=status_col))
            self._run_list.setItem(row, 3, _item(_fmt_secs(rec.get('duration_seconds')),
                                                  fg=fg_dim, align=R))

        self._run_list.setVisible(bool(total))

    def _raise_run_popup(self, index):
        row = index.row()
        n_live = len(self._run_popups)
        n_det  = len(self._detached_runs)
        if row < n_live:
            p = self._run_popups[row]
            p.show(); p.raise_(); p.activateWindow()
        elif row < n_live + n_det:
            desc = self._detached_runs[row - n_live]
            dlg = WatchLogPopup(desc, parent=None)
            self._watch_popups.append(dlg)
            dlg.destroyed.connect(
                lambda _, d=dlg: self._watch_popups.remove(d) if d in self._watch_popups else None)
            dlg.show(); dlg.raise_(); dlg.activateWindow()

    def refresh_open_popup_themes(self):
        """Re-apply theme to any open RunPopup / WatchLogPopup dialogs.
        Called from MainWindow._apply_theme().  Each popup's _apply_theme()
        is wrapped to tolerate already-deleted C++ objects."""
        for popup in list(self._run_popups) + list(self._watch_popups):
            try:
                popup._apply_theme()
            except RuntimeError:
                # Wrapped C++ object deleted (popup destroyed mid-iteration)
                pass
