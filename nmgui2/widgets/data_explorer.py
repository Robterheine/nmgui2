import math
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QCheckBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem,
    QStackedWidget, QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from ..app.theme import C, T
from ..app.format import loess
from ..widgets._icons import _placeholder

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False
    np = None

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    from ..parser import read_table_file
    HAS_PARSER = True
except ImportError:
    HAS_PARSER = False


class FilterRow(QWidget):
    """Single filter row: column  operator  value  [x]"""
    removed = pyqtSignal(object)
    changed = pyqtSignal()
    OPERATORS = ['=', '!=', '<', '<=', '>', '>=', 'contains']

    def __init__(self, columns, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self); h.setContentsMargins(0,0,0,0); h.setSpacing(4)
        self.col_cb = QComboBox(); self.col_cb.setMinimumWidth(100)
        self.col_cb.addItems([''] + columns)
        self.col_cb.currentTextChanged.connect(self._update_vals)
        self.col_cb.currentTextChanged.connect(self.changed)
        self.op_cb  = QComboBox(); self.op_cb.addItems(self.OPERATORS); self.op_cb.setFixedWidth(72)
        self.op_cb.currentTextChanged.connect(self.changed)
        self.val_cb = QComboBox(); self.val_cb.setMinimumWidth(110); self.val_cb.setEditable(True)
        self.val_cb.currentTextChanged.connect(self.changed)
        rem = QPushButton('[x]'); rem.setFixedWidth(36)
        rem.clicked.connect(lambda: self.removed.emit(self))
        h.addWidget(self.col_cb); h.addWidget(self.op_cb)
        h.addWidget(self.val_cb, 1); h.addWidget(rem)
        self._rows = []; self._header = []

    def set_rows(self, rows, header):
        self._rows = rows; self._header = header
        self._update_vals()

    def _update_vals(self):
        col = self.col_cb.currentText()
        self.val_cb.clear(); self.val_cb.addItem('')
        if col and col in self._header:
            ci = self._header.index(col)
            vals = sorted(set(str(r[ci]) for r in self._rows if ci < len(r)))
            self.val_cb.addItems(vals[:300])

    def matches(self, row, header):
        col = self.col_cb.currentText()
        val = self.val_cb.currentText().strip()
        op  = self.op_cb.currentText()
        if not col or not val: return True
        if col not in header: return True
        cell = str(row[header.index(col)])
        if op == 'contains': return val.lower() in cell.lower()
        # Try numeric comparison
        try:
            cv = float(cell); vv = float(val)
            if op == '=':  return cv == vv
            if op == '!=': return cv != vv
            if op == '<':  return cv <  vv
            if op == '<=': return cv <= vv
            if op == '>':  return cv >  vv
            if op == '>=': return cv >= vv
        except ValueError:
            # String fallback
            if op == '=':  return cell == val
            if op == '!=': return cell != val
            if op == '<':  return cell <  val
            if op == '<=': return cell <= val
            if op == '>':  return cell >  val
            if op == '>=': return cell >= val
        return True


class DataExplorerWidget(QWidget):
    """Merged Data Viewer + Custom Plot — file browser, table, and scatter plot."""
    PAGE_SIZE = 200

    def __init__(self, show_browser=True, parent=None):
        super().__init__(parent)
        self._header = []; self._rows = []; self._filtered_rows = []
        self._page = 0; self._model_dir = None; self._filter_rows = []
        self._build_ui(show_browser)

    def _build_ui(self, show_browser=True):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        if show_browser:
            left = QWidget(); left.setFixedWidth(180)
            lv = QVBoxLayout(left); lv.setContentsMargins(6,6,6,6); lv.setSpacing(4)
            lv.addWidget(QLabel('Files:'))
            self.file_list = QListWidget()
            self.file_list.currentItemChanged.connect(self._on_file_select)
            lv.addWidget(self.file_list, 1)
            root.addWidget(left)
            sep = QWidget(); sep.setFixedWidth(1)
            sep.setObjectName('hairlineSep')
            root.addWidget(sep)
        else:
            self.file_list = QListWidget()  # not shown; guards load_model / _refresh_file_list

        # ── Right: pill strip + stacked ──────────────────────────────────────
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(0)

        # Common toolbar / info label
        toolbar = QWidget(); toolbar.setObjectName('pillBar'); toolbar.setFixedHeight(38)
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(8,5,8,5); tl.setSpacing(4)
        self._de_btns = []
        for i, lbl in enumerate(['Table', 'Plot']):
            btn = QPushButton(lbl); btn.setObjectName('pillBtn')
            btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, n=i: self._de_switch(n))
            tl.addWidget(btn); self._de_btns.append(btn)
        tl.addSpacing(12)
        self.info_lbl = QLabel('Load a file from the browser')
        self.info_lbl.setObjectName('mutedSmall')
        tl.addWidget(self.info_lbl, 1)
        # When embedded inside FileExplorerTab the parent toolbar already owns
        # Table/Plot switching — hide the redundant pills here.
        if not show_browser:
            for btn in self._de_btns:
                btn.setVisible(False)
        rv.addWidget(toolbar)

        de_sep = QWidget(); de_sep.setFixedHeight(1); de_sep.setObjectName('hairlineSep')
        rv.addWidget(de_sep)

        self.sub_tabs = QStackedWidget()

        # ── TABLE view ────────────────────────────────────────────────────────
        table_w = QWidget(); tv = QVBoxLayout(table_w); tv.setContentsMargins(4,4,4,4); tv.setSpacing(4)

        filt_row = QHBoxLayout()
        self.tbl_col_cb = QComboBox(); self.tbl_col_cb.setMinimumWidth(100)
        self.tbl_col_cb.currentTextChanged.connect(self._update_tbl_filter_vals)
        self.tbl_val_cb = QComboBox(); self.tbl_val_cb.setMinimumWidth(100); self.tbl_val_cb.setEditable(True)
        apply_btn = QPushButton('Filter'); apply_btn.setFixedWidth(70); apply_btn.clicked.connect(self._apply_tbl_filter)
        clear_btn = QPushButton('Clear');  clear_btn.setFixedWidth(60);  clear_btn.clicked.connect(self._clear_tbl_filter)
        self.prev_btn = QPushButton('<'); self.prev_btn.setFixedWidth(28); self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = QPushButton('>'); self.next_btn.setFixedWidth(28); self.next_btn.clicked.connect(self._next_page)
        self.page_lbl = QLabel(''); self.page_lbl.setFixedWidth(80)
        filt_row.addWidget(QLabel('Filter:')); filt_row.addWidget(self.tbl_col_cb)
        filt_row.addWidget(QLabel('=')); filt_row.addWidget(self.tbl_val_cb)
        filt_row.addWidget(apply_btn); filt_row.addWidget(clear_btn); filt_row.addStretch()
        filt_row.addWidget(self.prev_btn); filt_row.addWidget(self.page_lbl); filt_row.addWidget(self.next_btn)
        tv.addLayout(filt_row)

        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.verticalHeader().setDefaultSectionSize(24)
        self.data_table.setShowGrid(False)
        tv.addWidget(self.data_table, 1)
        self.sub_tabs.addWidget(table_w)

        # ── PLOT view ─────────────────────────────────────────────────────────
        plot_w = QWidget(); pv = QVBoxLayout(plot_w); pv.setContentsMargins(8,8,8,8); pv.setSpacing(8)

        if not HAS_PG or not HAS_NP:
            pv.addWidget(_placeholder('Install pyqtgraph and numpy'))
        else:
            # ── Row 1: X / Y / Colour by ─────────────────────────────────────
            row1 = QHBoxLayout(); row1.setSpacing(12)
            self.x_cb   = QComboBox(); self.x_cb.setMinimumWidth(120)
            self.y_cb   = QComboBox(); self.y_cb.setMinimumWidth(120)
            self.grp_cb = QComboBox(); self.grp_cb.setMinimumWidth(120)
            for label, cb in [('X axis:', self.x_cb), ('Y axis:', self.y_cb), ('Colour by:', self.grp_cb)]:
                lbl = QLabel(label); lbl.setFixedWidth(60)
                row1.addWidget(lbl); row1.addWidget(cb)
                if cb is not self.grp_cb: row1.addSpacing(8)
            row1.addStretch()
            pv.addLayout(row1)

            # ── Row 2: options ────────────────────────────────────────────────
            row2 = QHBoxLayout(); row2.setSpacing(16)
            self.log_x_cb = QCheckBox('Log X')
            self.log_y_cb = QCheckBox('Log Y')
            self.loess_cb = QCheckBox('LOESS');  self.loess_cb.setChecked(True)
            self.ref0_cb  = QCheckBox('Y = 0')
            self.refyx_cb = QCheckBox('Y = X')
            self.mdv_cb   = QCheckBox('Excl. MDV=1'); self.mdv_cb.setChecked(True)
            for cb in (self.log_x_cb, self.log_y_cb, self.loess_cb,
                       self.ref0_cb, self.refyx_cb, self.mdv_cb):
                row2.addWidget(cb)
            row2.addStretch()
            pv.addLayout(row2)

            # ── Row 3: filters ────────────────────────────────────────────────
            filt_grp = QGroupBox('Filters  (all ANDed together)')
            self._fv = QVBoxLayout(filt_grp); self._fv.setSpacing(4)
            add_btn = QPushButton('+ Add filter'); add_btn.setFixedWidth(120)
            add_btn.clicked.connect(self._add_filter)
            self._fv.addWidget(add_btn)
            pv.addWidget(filt_grp)

            # Connect all controls to auto-replot
            for cb in (self.x_cb, self.y_cb, self.grp_cb):
                cb.currentTextChanged.connect(self._plot)
            for cb in (self.log_x_cb, self.log_y_cb, self.loess_cb,
                       self.ref0_cb, self.refyx_cb, self.mdv_cb):
                cb.stateChanged.connect(self._plot)

            self.pw = pg.PlotWidget()
            self.pw.showGrid(x=True, y=True, alpha=0.2)
            self.pw.getAxis('bottom').enableAutoSIPrefix(False)
            self.pw.getAxis('left').enableAutoSIPrefix(False)
            self._legend = self.pw.addLegend()
            pv.addWidget(self.pw, 1)

        self.sub_tabs.addWidget(plot_w)
        rv.addWidget(self.sub_tabs, 1)
        root.addWidget(right, 1)
        # Embedded mode (no browser): always start in Plot — Table is the parent's QTableView.
        self._de_switch(1 if not show_browser else 0)

    def _de_switch(self, index):
        self.sub_tabs.setCurrentIndex(index)
        for i, btn in enumerate(self._de_btns):
            btn.setChecked(i == index)

    # ── File browser ──────────────────────────────────────────────────────────

    def load_model(self, model):
        self._model_dir = str(Path(model['path']).parent)
        self._refresh_file_list()

    def _refresh_file_list(self):
        self.file_list.clear()
        if not self._model_dir: return
        exts = {'.tab','.csv','.dat','.txt'}
        prefixes = ('sdtab','patab','catab','cotab','mutab','wres','cwtab')
        p = Path(self._model_dir)
        for f in sorted(p.iterdir()):
            if f.is_file() and (f.suffix.lower() in exts or
               any(f.name.lower().startswith(px) for px in prefixes)):
                self.file_list.addItem(QListWidgetItem(f.name))
        for sub in sorted(p.iterdir()):
            if sub.is_dir():
                for f in sorted(sub.iterdir()):
                    if f.is_file() and (f.suffix.lower() in exts or
                       any(f.name.lower().startswith(px) for px in prefixes)):
                        item = QListWidgetItem(f'{sub.name}/{f.name}')
                        item.setData(Qt.ItemDataRole.UserRole, str(f))
                        self.file_list.addItem(item)

    def _on_file_select(self, current, _):
        if not current: return
        path = current.data(Qt.ItemDataRole.UserRole)
        if not path: path = str(Path(self._model_dir) / current.text())
        if not HAS_PARSER: return
        MAX_ROWS = 10000
        h, r = read_table_file(path, max_rows=MAX_ROWS)
        if h is None: return
        truncated = len(r) >= MAX_ROWS
        self._load_data(h, r, Path(path).name, truncated)

    def _load_data(self, header, rows, name='', truncated=False):
        self._header = [h.upper() for h in header]; self._rows = rows
        self._filtered_rows = rows; self._page = 0
        # Update table filter combo
        self.tbl_col_cb.clear(); self.tbl_col_cb.addItems([''] + self._header)
        # Update plot column combos
        if HAS_PG and HAS_NP:
            cols = [''] + self._header
            for cb in (self.x_cb, self.y_cb, self.grp_cb):
                cur = cb.currentText(); cb.blockSignals(True); cb.clear()
                cb.addItems(cols); cb.setCurrentIndex(max(0, cb.findText(cur)))
                cb.blockSignals(False)
            for fr in self._filter_rows:
                cur = fr.col_cb.currentText(); fr.col_cb.blockSignals(True); fr.col_cb.clear()
                fr.col_cb.addItems(cols); fr.col_cb.setCurrentIndex(max(0, fr.col_cb.findText(cur)))
                fr.col_cb.blockSignals(False); fr.set_rows(rows, self._header)
            if self.x_cb.currentIndex()==0 and 'PRED' in self._header: self.x_cb.setCurrentText('PRED')
            if self.y_cb.currentIndex()==0  and 'DV'   in self._header: self.y_cb.setCurrentText('DV')
        self._render_table()
        if truncated:
            self.info_lbl.setText(f'{name}  ·  {len(rows):,} rows, {len(header)} columns [TRUNCATED]')
        else:
            self.info_lbl.setText(f'{name}  ·  {len(rows):,} rows, {len(header)} columns')

    # Also accept (header, rows) directly (called from EvaluationTab for sdtab auto-load)
    def load(self, header, rows):
        if header: self._load_data(header, rows)

    # ── Table view ────────────────────────────────────────────────────────────

    def _update_tbl_filter_vals(self):
        col = self.tbl_col_cb.currentText()
        self.tbl_val_cb.clear(); self.tbl_val_cb.addItem('')
        if col and col in self._header:
            ci = self._header.index(col)
            vals = sorted(set(str(r[ci]) for r in self._rows if ci < len(r)))
            self.tbl_val_cb.addItems(vals[:300])

    def _apply_tbl_filter(self):
        col = self.tbl_col_cb.currentText(); val = self.tbl_val_cb.currentText().strip()
        if not col or not val:
            self._filtered_rows = self._rows
        elif col in self._header:
            ci = self._header.index(col)
            self._filtered_rows = [r for r in self._rows if str(r[ci]) == val]
        self._page = 0; self._render_table()

    def _clear_tbl_filter(self):
        self._filtered_rows = self._rows; self._page = 0
        self.tbl_val_cb.setCurrentText(''); self._render_table()

    def _n_pages(self): return max(1, math.ceil(len(self._filtered_rows)/self.PAGE_SIZE))
    def _prev_page(self):
        if self._page > 0: self._page -= 1; self._render_table()
    def _next_page(self):
        if self._page < self._n_pages()-1: self._page += 1; self._render_table()

    def _render_table(self):
        if not self._header: return
        start = self._page * self.PAGE_SIZE
        page_rows = self._filtered_rows[start:start+self.PAGE_SIZE]
        self.data_table.setColumnCount(len(self._header))
        self.data_table.setHorizontalHeaderLabels(self._header)
        self.data_table.setRowCount(len(page_rows))
        for row_i, row in enumerate(page_rows):
            for col_i, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
                self.data_table.setItem(row_i, col_i, item)
        self.data_table.resizeColumnsToContents()
        self.page_lbl.setText(f'{self._page+1}/{self._n_pages()}')
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < self._n_pages()-1)
        n_tot = len(self._filtered_rows); n_all = len(self._rows)
        filt_str = f' (filtered from {n_all})' if n_tot != n_all else ''
        self.info_lbl.setText(
            f'{n_tot} rows{filt_str}, {len(self._header)} cols  ·  '
            f'rows {start+1}–{min(start+self.PAGE_SIZE,n_tot)} of {n_tot}')

    # ── Plot view — filters ───────────────────────────────────────────────────

    def _add_filter(self):
        fr = FilterRow(self._header); fr.set_rows(self._rows, self._header)
        fr.removed.connect(self._remove_filter)
        fr.changed.connect(self._plot)
        self._filter_rows.append(fr)
        self._fv.insertWidget(self._fv.count()-1, fr)

    def _remove_filter(self, fr):
        self._filter_rows.remove(fr); self._fv.removeWidget(fr); fr.deleteLater()

    # ── Plot view — render ────────────────────────────────────────────────────

    def set_theme(self, bg, fg):
        if HAS_PG and hasattr(self, 'pw'): self.pw.setBackground(bg)

    def _plot(self):
        if not HAS_PG or not HAS_NP: return
        xcol = self.x_cb.currentText(); ycol = self.y_cb.currentText()
        if not xcol or not ycol: return
        H = self._header
        if xcol not in H or ycol not in H: return
        self.pw.clear()
        try: self._legend.clear()
        except Exception: pass  # Legend may not exist yet
        xi = H.index(xcol); yi = H.index(ycol)

        def passes(row):
            if self.mdv_cb.isChecked() and 'MDV' in H:
                try:
                    if float(row[H.index('MDV')]) != 0: return False
                except (ValueError, TypeError): pass
            return all(fr.matches(row, H) for fr in self._filter_rows)

        rows_f = [r for r in self._rows if passes(r)]
        if not rows_f: return

        gcol = self.grp_cb.currentText()
        if gcol and gcol in H:
            gi = H.index(gcol); groups = {}
            for row in rows_f:
                k = str(row[gi])
                if k not in groups: groups[k] = []
                groups[k].append(row)
        else: groups = {'All': rows_f}

        pal = ['#569cd6','#4ec994','#ce9178','#dcdcaa','#c586c0',
               '#9cdcfe','#f44747','#6a9955','#4fc1ff','#d7ba7d']

        for gi_, (gname, grows) in enumerate(groups.items()):
            color = pal[gi_ % len(pal)]
            try:
                x = np.array([float(r[xi]) for r in grows])
                y = np.array([float(r[yi]) for r in grows])
            except Exception: continue
            ok = np.isfinite(x) & np.isfinite(y); x,y = x[ok],y[ok]
            if len(x)==0: continue
            lbl = gname if len(groups)>1 else None
            qc = QColor(color)
            self.pw.addItem(pg.ScatterPlotItem(x=x,y=y,pen=None,
                brush=pg.mkBrush(qc.red(),qc.green(),qc.blue(),110),size=6,name=lbl))
            if self.loess_cb.isChecked():
                xlo,ylo = loess(x,y)
                if xlo is not None: self.pw.plot(xlo,ylo,pen=pg.mkPen(color,width=2))

        self.pw.setLogMode(x=self.log_x_cb.isChecked(), y=self.log_y_cb.isChecked())
        self.pw.setLabel('bottom',xcol); self.pw.setLabel('left',ycol)

        if self.ref0_cb.isChecked():
            try:
                ax = np.array([float(r[xi]) for r in rows_f])
                self.pw.plot([ax[np.isfinite(ax)].min(), ax[np.isfinite(ax)].max()],[0,0],
                             pen=pg.mkPen('#aaaaaa',width=1.5,style=Qt.PenStyle.DashLine))
            except Exception: pass  # Reference line is non-critical

        if self.refyx_cb.isChecked():
            try:
                ax=np.array([float(r[xi]) for r in rows_f]); ay=np.array([float(r[yi]) for r in rows_f])
                mn=min(ax[np.isfinite(ax)].min(),ay[np.isfinite(ay)].min())
                mx=max(ax[np.isfinite(ax)].max(),ay[np.isfinite(ay)].max())
                self.pw.plot([mn,mx],[mn,mx],pen=pg.mkPen(C.red,width=1.5))
            except Exception: pass  # Reference line is non-critical

        filt_desc = '  '.join(
            f'[{fr.col_cb.currentText()} {fr.op_cb.currentText()} {fr.val_cb.currentText()}]'
            for fr in self._filter_rows
            if fr.col_cb.currentText() and fr.val_cb.currentText())
        self.pw.setTitle(f'{ycol} vs {xcol}  {filt_desc}')
