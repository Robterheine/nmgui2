import os, re, subprocess, logging, time, shlex
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QMenu, QMessageBox, QFileDialog,
    QApplication, QStyledItemDelegate,
    QStackedWidget, QSizePolicy, QDialog, QInputDialog, QCheckBox,
    QPlainTextEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QModelIndex, QAbstractTableModel, QTimer
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QFont, QAction
from ..app.theme import C, T, THEMES, _active_theme
from ..app.constants import IS_WIN, IS_MAC, HOME
from ..app.config import load_meta, save_meta, get_meta_entry, load_settings, save_settings, load_bookmarks, save_bookmarks, load_runs, save_runs, get_all_tags
from ..app.format import fmt_ofv, fmt_num, fmt_rse
from ..app.tools import find_tool, get_login_env, launch_rstudio
from ..app.run_records import create_run_record, finalize_run_record, load_run_records, save_run_records
from ..app.workers import ScanWorker, RunWorker
from ..app.model_io import _parse_param_names_from_mod, _align_param_names
from ..app.html_report import generate_html_report
from ..app.qc_report import generate_qc_html, open_report_in_browser
from ..widgets.parameter_table import ParameterTable
from ..widgets.highlighter import NMHighlighter
from ..widgets.lst_viewer import LstOutputWidget
from ..dialogs.duplicate import DuplicateDialog
from ..dialogs.comparison import ModelComparisonDialog
from ..dialogs.nmtran import NMTRANPanel
from ..dialogs.run_record import RunRecordDialog
from ..dialogs.lst_viewer_dialog import LstViewerDialog

try:
    from parser import parse_lst, extract_table_files, inject_estimates
    HAS_PARSER = True
except ImportError:
    HAS_PARSER = False
    inject_estimates = None

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Model table
# ══════════════════════════════════════════════════════════════════════════════

COLS = ['*','Name','OFV','dOFV','Status','COV','CN','Method','nInd','nObs','nPar','AIC','Runtime']
(COL_STAR, COL_NAME, COL_OFV, COL_DOFV, COL_STATUS,
 COL_COV, COL_CN, COL_METHOD, COL_NIND, COL_NOBS, COL_NPAR, COL_AIC, COL_RT) = range(13)


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
        self.beginResetModel(); self.endResetModel()

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
            if col == COL_OFV:  return fmt_ofv(m.get('ofv'))
            if col == COL_DOFV:
                ofv = m.get('ofv')
                base, is_ref = self._dofv_base()
                if ofv is None or base is None: return ''
                if is_ref and m['path'] == self._ref_path: return 'REF'
                if not is_ref and abs(ofv - base) < 0.001: return '—'
                d = ofv - base
                return f'+{d:.3f}' if d > 0 else f'{d:.3f}'
            if col == COL_STATUS: return (m.get('minimization_message') or '')[:35]
            if col == COL_COV:
                cv = m.get('covariance_step')
                return '' if cv is None else ('✓' if cv else '✗')
            if col == COL_CN:
                cn = m.get('condition_number')
                if cn is None: return ''
                if cn >= 10000: return f'! {cn:.2e}'
                if cn >= 1000:  return f'! {cn:.0f}'
                return f'{cn:.1f}'
            if col == COL_METHOD: return m.get('estimation_method','')
            if col == COL_NIND:  return str(m['n_individuals']) if m.get('n_individuals') else ''
            if col == COL_NOBS:  return str(m['n_observations']) if m.get('n_observations') else ''
            if col == COL_NPAR:  return str(m['n_estimated_params']) if m.get('n_estimated_params') else ''
            if col == COL_AIC:   return fmt_ofv(m.get('aic'))
            if col == COL_RT:
                rt = m.get('runtime')
                if rt is None: return ''
                return f'{rt:.0f}s' if rt < 3600 else f'{rt/3600:.1f}h'
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STAR: return QBrush(QColor(C.star))
            if col == COL_STATUS:
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
            if col == COL_NAME and m.get('stale'): return QBrush(QColor(C.stale))
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_NAME:
                tip = f"Path: {m['path']}"
                if m.get('problem'): tip += f"\n{m['problem']}"
                if m.get('comment'): tip += f"\n{m['comment']}"
                if m.get('based_on'): tip += f"\nBased on: {m['based_on']}"
                return tip
            if col == COL_STATUS and m.get('cov_failure_reason'): return m['cov_failure_reason']
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
    model_selected = pyqtSignal(dict)
    status_msg     = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory = load_settings().get('working_directory', str(HOME))
        self._meta = load_meta(); self._scan_worker = None
        self._run_worker = None; self._current_model = None
        self._ref_model_path = None   # user-selected reference for dOFV
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
        filter_row.addStretch()
        lv.addLayout(filter_row)

        self.table = _ModelsTable()
        self.table.setColumnCount(len(COLS)); self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_CN, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        # Column header tooltips
        _col_tips = {
            COL_STAR:   '*  Starred / flagged model',
            COL_NAME:   'Model name (stem of .mod file)',
            COL_OFV:    'Objective Function Value',
            COL_DOFV:   'ΔOFV relative to the best model in this directory',
            COL_STATUS: 'Minimization status message',
            COL_COV:    'Covariance step  (✓ successful  ✗ failed)',
            COL_CN:     'Condition number — ratio of largest to smallest eigenvalue '
                        'of the correlation matrix.\nRequires $COV with PRINT=E or '
                        'a NONMEM version that outputs it directly.\nValues > 1000 '
                        'may indicate near-collinearity.',
            COL_METHOD: 'Estimation method  (FO, FOCE, FOCE-I, SAEM, SAEM→IMP, BAYES…)',
            COL_NIND:   'Number of individuals',
            COL_NOBS:   'Number of observation records (MDV=0 rows)',
            COL_NPAR:   'Number of estimated parameters  (non-fixed THETAs + OMEGA/SIGMA elements)',
            COL_AIC:    'Akaike Information Criterion  =  OFV + 2k',
            COL_RT:     'Estimation runtime (seconds or hours)',
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

        sep2 = QWidget(); sep2.setFixedHeight(1); sep2.setStyleSheet(f'background:{C.border};')
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
        self.editor.setFont(QFont('Menlo' if IS_MAC else 'Consolas',12))
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
        rf.addRow('', self.clean_cb); run_v.addLayout(rf)
        run_btn_row = QHBoxLayout(); run_btn_row.setSpacing(8)
        self.run_btn  = QPushButton('Run');  self.run_btn.setObjectName('primary')
        self.run_btn.clicked.connect(self._run_model)
        self.stop_btn = QPushButton('Stop'); self.stop_btn.clicked.connect(self._stop_run)
        self.stop_btn.setEnabled(False)
        nmtran_btn = QPushButton('NMTRAN msgs…'); nmtran_btn.clicked.connect(self._show_nmtran)
        run_btn_row.addWidget(self.run_btn); run_btn_row.addWidget(self.stop_btn)
        run_btn_row.addWidget(nmtran_btn); run_btn_row.addStretch()
        run_v.addLayout(run_btn_row)
        self.console = QPlainTextEdit(); self.console.setReadOnly(True)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas',11))
        self.console.setMaximumBlockCount(5000)
        run_v.addWidget(self.console,1)
        self._detail_stack.addWidget(run_w)

        # 3 — Info
        info_w = QWidget(); info_v = QVBoxLayout(info_w)
        info_v.setContentsMargins(10,10,10,10); info_v.setSpacing(8)

        # Dataset info section
        ds_lbl = QLabel('DATASET')
        ds_lbl.setStyleSheet(f'color:{C.fg2};font-size:10px;font-weight:600;letter-spacing:0.5px;')
        info_v.addWidget(ds_lbl)
        self._ds_info = QLabel('No model selected')
        self._ds_info.setWordWrap(True)
        self._ds_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._ds_info.setStyleSheet(f'color:{C.fg};font-size:11px;background:{C.bg3};padding:6px;border-radius:4px;')
        info_v.addWidget(self._ds_info)

        info_v.addSpacing(8)

        info_v.addWidget(QLabel('Comment'))
        self.comment_edit = QLineEdit(); self.comment_edit.setPlaceholderText('Short label…')
        self.comment_edit.editingFinished.connect(self._save_meta_fields)
        info_v.addWidget(self.comment_edit)

        # Status row
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel('Status:'))
        self.status_tag_combo = QComboBox()
        self.status_tag_combo.addItems(['','base','candidate','final'])
        self.status_tag_combo.currentTextChanged.connect(self._save_meta_fields)
        status_row.addWidget(self.status_tag_combo); status_row.addStretch()
        info_v.addLayout(status_row)

        # Decision row (annotation system)
        decision_row = QHBoxLayout()
        decision_row.addWidget(QLabel('Decision:'))
        self.decision_combo = QComboBox()
        self.decision_combo.addItems(['', 'Include', 'Sensitivity', 'Exploratory', 'Rejected'])
        self.decision_combo.currentTextChanged.connect(self._save_meta_fields)
        self.decision_combo.setToolTip('Categorize model for reporting/submission')
        decision_row.addWidget(self.decision_combo); decision_row.addStretch()
        info_v.addLayout(decision_row)

        # Tags row (annotation system)
        info_v.addWidget(QLabel('Tags'))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText('Comma-separated: pediatric, renal, covariate...')
        self.tags_edit.setToolTip('Add tags for filtering and search')
        self.tags_edit.editingFinished.connect(self._save_meta_fields)
        info_v.addWidget(self.tags_edit)

        info_v.addWidget(QLabel('Notes'))
        self.notes_edit = QTextEdit(); self.notes_edit.setPlaceholderText('Rationale, decisions…')
        self.notes_edit.setMaximumHeight(140)
        orig_focusOut = self.notes_edit.focusOutEvent
        self.notes_edit.focusOutEvent = lambda e: (self._save_meta_fields(), orig_focusOut(e))
        info_v.addWidget(self.notes_edit)
        info_v.addStretch()
        self._detail_stack.addWidget(info_w)

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
        self.table.setSortingEnabled(True); self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        n = len(models); nr = sum(1 for m in models if m['has_run'])
        elapsed = time.time() - t0
        self.status_msg.emit(
            f'{n} model{"s" if n!=1 else ""}, {nr} with results  ·  '
            f'{Path(self._directory).name}  ·  scanned in {elapsed:.1f}s')

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
                # Remove DROP columns
                cols = [c for c in cols if c not in ('DROP', 'SKIP')]
                if cols:
                    ds_parts.append(f'Columns: {", ".join(cols[:10])}{"..." if len(cols) > 10 else ""}')
        except Exception:
            pass

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
        menu.addSeparator()
        menu.addAction('View .lst', self._view_lst)
        menu.addAction('View run record…', self._view_run_record)
        menu.addAction('NMTRAN messages…', self._show_nmtran)
        menu.addSeparator()
        if m.get('has_run'):
            menu.addAction('QC Report…', self._open_qc_report)
            menu.addAction('Run Report…', self._open_run_report)
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
        self.console.clear(); self.console.appendPlainText(f'$ {cmd}\n')
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        if self._run_worker:
            try: self._run_worker.line_out.disconnect()
            except Exception: pass  # Signal may not be connected
            try: self._run_worker.finished.disconnect()
            except Exception: pass  # Signal may not be connected
        self._run_worker = RunWorker(cmd, cwd)
        self._run_worker.line_out.connect(self.console.appendPlainText)
        self._run_worker.finished.connect(self._on_run_done)
        self._run_worker.start()

        # Legacy run history (global)
        runs = load_runs()
        runs.insert(0,{'id':f"{m['stem']}_{int(time.time())}","run_name":m['stem'],
                       "model":model_path,"tool":tool,"command":cmd,"working_dir":cwd,
                       "status":"running","started":datetime.now().isoformat(),"finished":None})
        save_runs(runs[:200])

        # Project-level run record (audit trail)
        self._current_run_record = create_run_record(model_path, cmd, tool)
        self._current_run_model_path = model_path
        records = load_run_records(cwd)
        records.insert(0, self._current_run_record)
        save_run_records(cwd, records[:500])  # Keep last 500 records

    def _on_run_done(self, rc):
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        s = 'finished' if rc == 0 else f'failed (code {rc})'
        self.console.appendPlainText(f'\n[Process {s}]')
        self.status_msg.emit(f'Run {s}')

        # Update legacy run history
        runs = load_runs()
        if runs:
            runs[0]['status']   = 'ok' if rc == 0 else f'failed ({rc})'
            runs[0]['finished'] = datetime.now().isoformat()
            runs[0]['exit_code'] = rc
            save_runs(runs)

        # Finalize project-level run record
        if hasattr(self, '_current_run_record') and self._current_run_record:
            model_path = getattr(self, '_current_run_model_path', None)
            if model_path:
                cwd = str(Path(model_path).parent)
                self._current_run_record = finalize_run_record(
                    self._current_run_record, model_path, rc)
                # Update the record in storage
                records = load_run_records(cwd)
                if records and records[0].get('run_id') == self._current_run_record.get('run_id'):
                    records[0] = self._current_run_record
                    save_run_records(cwd, records)
            self._current_run_record = None
            self._current_run_model_path = None

        QTimer.singleShot(1500, self._scan)

    def _stop_run(self):
        if self._run_worker: self._run_worker.stop()
