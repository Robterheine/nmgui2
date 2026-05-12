import math
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox,
    QStyledItemDelegate, QStyle,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygon

from ..app.theme import C, T
from ..app.format import fmt_num, fmt_rse
from ..app.model_io import _align_param_names, _parse_param_names_from_mod
from ..app.html_report import generate_html_report
from ..app.constants import HOME


_SECTION_ROW_KEY  = 'section_header'   # stored in UserRole to identify header rows
_INIT_FINAL_ROLE  = Qt.ItemDataRole.UserRole + 10   # delegate payload


class InitialVsFinalDelegate(QStyledItemDelegate):
    """Paints a small bullet-bar visualization of initial→final estimate.

    Reads its payload from item.data(_INIT_FINAL_ROLE) as a dict:
        {'initial': float, 'final': float,
         'lower': float|None, 'upper': float|None,
         'fixed': bool}

    Rendering:
      - FIXED parameters: small filled diamond, no track.
      - Bounded parameters (lower and upper both present): full track
        from lower→upper with an initial tick and a final marker.
      - Unbounded (typical OMEGA/SIGMA): auto-scaled track from 0 (or
        the minimum if either value is negative) up to 2× max(|init|,|final|).
        Right edge of track drawn dashed to signal "extrapolated".
      - Final marker color is graded by movement magnitude
        (subtle / accent / orange) and goes red when at/beyond a bound.
      - At/beyond bound: a thin red 'wall' line at the bound position.

    No data → blank cell (best-effort degradation when initials are
    missing, e.g. simulation-only runs).
    Cross-OS-safe: all drawing via QPainter primitives, no Unicode glyphs.
    """

    # Colors are pulled live from the theme `C` singleton inside paint()
    # so a theme switch repaints correctly via the table's normal refresh.

    def paint(self, painter, option, index):
        # Background — let the default delegate paint selection / hover state
        super().paint(painter, option, index)

        data = index.data(_INIT_FINAL_ROLE)
        if not isinstance(data, dict):
            return
        initial = data.get('initial')
        final   = data.get('final')
        if initial is None or final is None:
            return  # no data → blank cell

        lower = data.get('lower')
        upper = data.get('upper')
        fixed = bool(data.get('fixed', False))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cell   = option.rect
        cx, cy = cell.center().x(), cell.center().y()

        # ── FIXED: small grey diamond, no movement to show ───────────────
        if fixed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C.fg3))
            painter.drawPolygon(QPolygon([
                QPoint(cx,     cy - 3),
                QPoint(cx + 3, cy),
                QPoint(cx,     cy + 3),
                QPoint(cx - 3, cy),
            ]))
            painter.restore()
            return

        # ── Geometry ─────────────────────────────────────────────────────
        pad_x       = 8
        track_left  = cell.left() + pad_x
        track_right = cell.right() - pad_x
        if track_right <= track_left:
            painter.restore(); return
        track_h     = 4
        track_top   = cy - track_h // 2

        # ── Determine scale (bounded vs auto-scaled) ─────────────────────
        has_lo = lower is not None
        has_hi = upper is not None
        if has_lo and has_hi and upper > lower:
            scale_lo, scale_hi, extrapolated = float(lower), float(upper), False
        else:
            extrapolated = True
            # Use 0 (or min(initial, final) if negative) as the left anchor,
            # 2×max(|init|, |final|) as the right anchor. Guarantees > 0 span.
            vmin = min(initial, final, 0.0)
            vmax = max(initial, final, 0.0)
            scale_lo = float(lower) if has_lo else vmin
            scale_hi = float(upper) if has_hi else max(2.0 * max(abs(initial), abs(final)), 1e-9)
            if scale_hi <= scale_lo:
                scale_hi = scale_lo + max(abs(scale_lo) * 0.5, 1e-9)

        def map_x(v: float) -> int:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return (track_left + track_right) // 2
            if scale_hi == scale_lo:
                return (track_left + track_right) // 2
            x = track_left + (fv - scale_lo) / (scale_hi - scale_lo) * (track_right - track_left)
            # Clamp to track
            return int(round(max(track_left, min(track_right, x))))

        # ── Track ────────────────────────────────────────────────────────
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C.bg3))
        painter.drawRoundedRect(QRect(track_left, track_top,
                                      track_right - track_left, track_h), 2, 2)
        if extrapolated:
            # Dashed overlay on the right portion to signal "extrapolated scale"
            mid = track_left + (track_right - track_left) * 2 // 3
            pen = QPen(QColor(C.fg3), 1, Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.drawLine(mid, cy, track_right, cy)

        # ── Movement magnitude → marker color ────────────────────────────
        if initial == 0:
            abs_move = 0.0 if final == 0 else float('inf')
        else:
            abs_move = abs(final - initial) / abs(initial)

        # At-or-beyond-bound detection (1% tolerance relative to the bound)
        at_upper = (
            has_hi
            and abs(upper) > 1e-12
            and final >= upper - abs(upper) * 0.01
        )
        at_lower = (
            has_lo
            and abs(lower) > 1e-12
            and final <= lower + abs(lower) * 0.01
        )
        at_bound = at_upper or at_lower

        if at_bound:
            marker_color = QColor(C.red)
        elif abs_move >= 0.5:
            marker_color = QColor(C.orange)
        elif abs_move >= 0.1:
            marker_color = QColor(C.blue)
        else:
            marker_color = QColor(C.fg2)

        # ── Initial tick (short vertical line) ────────────────────────────
        x_init = map_x(initial)
        painter.setPen(QPen(QColor(C.fg3), 1))
        painter.drawLine(x_init, track_top - 3, x_init, track_top + track_h + 3)

        # ── Final marker (filled circle) ──────────────────────────────────
        x_final = map_x(final)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(marker_color)
        painter.drawEllipse(QPoint(x_final, cy), 3, 3)

        # ── At-bound wall (red vertical line) ─────────────────────────────
        if at_bound:
            bound_x = track_right if at_upper else track_left
            painter.setPen(QPen(QColor(C.red), 1))
            painter.drawLine(bound_x, track_top - 4, bound_x, track_top + track_h + 4)

        painter.restore()


class ParameterTable(QWidget):
    export_done = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._section_rows = {}   # block_name -> (header_row, [data_rows])
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        # Toolbar
        toolbar = QWidget(); toolbar.setFixedHeight(34)
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(4,4,4,4); tl.setSpacing(6)
        tl.addStretch()
        self.open_report_btn = QPushButton('Open Report')
        self.open_report_btn.setToolTip('Generate run report and open in browser')
        self.open_report_btn.setFixedHeight(26); self.open_report_btn.setEnabled(False)
        self.save_report_btn = QPushButton('Save Report…')
        self.save_report_btn.setToolTip('Save run report as HTML file')
        self.save_report_btn.setFixedHeight(26); self.save_report_btn.setEnabled(False)
        self.csv_btn = QPushButton('Export CSV')
        self.csv_btn.setToolTip('Export parameter table to CSV')
        self.csv_btn.setFixedHeight(26); self.csv_btn.setEnabled(False)
        self.open_report_btn.clicked.connect(self._open_report)
        self.save_report_btn.clicked.connect(self._save_report)
        self.csv_btn.clicked.connect(self._export_csv)
        tl.addWidget(self.open_report_btn); tl.addWidget(self.save_report_btn)
        tl.addWidget(self.csv_btn)
        v.addWidget(toolbar)
        # Column layout (post v2.9.18 — new "Init→Final" viz column at index 3):
        #   0=Param  1=Name  2=Estimate  3=Init→Final  4=SE  5=RSE%
        #   6=Shrink%  7=Etabar  8=Units
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ['Param', 'Name', 'Estimate', 'Init→Final', 'SE', 'RSE%', 'Shrink%', 'Etabar', 'Units'])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(0, 85)
        hh.resizeSection(1, 140)
        hh.resizeSection(2, 85)
        hh.resizeSection(3, 70)   # new — Init→Final viz column
        hh.resizeSection(4, 65)
        hh.resizeSection(5, 55)
        hh.resizeSection(6, 55)
        hh.resizeSection(7, 55)
        hh.resizeSection(8, 50)
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(40)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.itemClicked.connect(self._on_item_clicked)
        # Attach the Init→Final visualization delegate to column 3
        self._init_final_delegate = InitialVsFinalDelegate(self.table)
        self.table.setItemDelegateForColumn(3, self._init_final_delegate)
        v.addWidget(self.table)

    def _on_item_clicked(self, item):
        if item and item.data(Qt.ItemDataRole.UserRole) == _SECTION_ROW_KEY:
            block = item.data(Qt.ItemDataRole.UserRole + 1)
            self._toggle_section(block)

    def _toggle_section(self, block):
        if block not in self._section_rows:
            return
        header_row, data_rows = self._section_rows[block]
        # Detect current state from first data row visibility
        currently_hidden = data_rows and self.table.isRowHidden(data_rows[0])
        arrow = '\u25bc' if currently_hidden else '\u25b6'
        label = f'  {arrow}  {block}  ({len(data_rows)})'
        hdr_item = self.table.item(header_row, 0)
        if hdr_item:
            hdr_item.setText(label)
        for r in data_rows:
            self.table.setRowHidden(r, not currently_hidden)

    def _open_report(self):
        if not self._model: return
        import tempfile, webbrowser
        html = generate_html_report(_align_param_names(self._model))
        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8')
        tmp.write(html); tmp.flush(); tmp_name = tmp.name; tmp.close()
        webbrowser.open(f'file://{tmp_name}')
        # Schedule cleanup after browser has had time to read the file
        QTimer.singleShot(30000, lambda: Path(tmp_name).unlink(missing_ok=True))

    def _save_report(self):
        if not self._model: return
        stem = self._model.get('stem','report')
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save report', str(HOME / f'{stem}_report.html'),
            'HTML files (*.html)')
        if not dst: return
        Path(dst).write_text(generate_html_report(_align_param_names(self._model)), encoding='utf-8')
        if QMessageBox.question(self,'Saved',f'Report saved.\nOpen in browser?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            import webbrowser; webbrowser.open(f'file://{dst}')

    def _export_csv(self):
        if not self._model: return
        stem = self._model.get('stem','model')
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Export parameters', str(HOME / f'{stem}_params.csv'),
            'CSV files (*.csv)')
        if not dst: return
        import csv as _csv
        rows = []
        for block, ests, ses, names, units, fixed in [
            ('THETA', self._model.get('thetas',[]), self._model.get('theta_ses',[]),
             self._model.get('theta_names',[]), self._model.get('theta_units',[]),
             self._model.get('theta_fixed',[])),
            ('OMEGA', self._model.get('omegas',[]), self._model.get('omega_ses',[]),
             self._model.get('omega_names',[]), self._model.get('omega_units',[]),
             self._model.get('omega_fixed',[])),
            ('SIGMA', self._model.get('sigmas',[]), self._model.get('sigma_ses',[]),
             self._model.get('sigma_names',[]), self._model.get('sigma_units',[]),
             self._model.get('sigma_fixed',[])),
        ]:
            for i, est in enumerate(ests):
                se  = ses[i]   if i < len(ses)   else None
                nm  = names[i] if i < len(names) else ''
                un  = units[i] if i < len(units) else ''
                fx  = fixed[i] if i < len(fixed) else False
                rse = f'{abs(se/est)*100:.2f}' if se and est and abs(est)>1e-12 else ''
                rows.append([f'{block}({i+1})', nm,
                              fmt_num(est), fmt_num(se) if se is not None else '',
                              rse, un, 'FIXED' if fx else ''])
        with open(dst, 'w', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            w.writerow(['Parameter','Name','Estimate','SE','RSE_pct','Units','Fixed'])
            w.writerows(rows)
        self.export_done.emit(f'Parameters exported: {Path(dst).name}')

    def load(self, model, parent_model=None):
        self._model = model if model.get('has_run') else None
        has = self._model is not None
        self.open_report_btn.setEnabled(has)
        self.save_report_btn.setEnabled(has)
        self.csv_btn.setEnabled(has)
        self.table.setRowCount(0)

        # Get shrinkage and etabar arrays
        eta_shr = model.get('eta_shrinkage', [])
        eps_shr = model.get('eps_shrinkage', [])
        etabar_pval = model.get('etabar_pval', [])

        # Build parent parameter lookup for comparison
        parent_params = {}
        if parent_model and parent_model.get('has_run'):
            for block, key in [('THETA', 'thetas'), ('OMEGA', 'omegas'), ('SIGMA', 'sigmas')]:
                for i, val in enumerate(parent_model.get(key, [])):
                    parent_params[f'{block}({i+1})'] = val

        # Initial estimates and bounds (parsed from the .lst echo block).
        # Empty lists when the model has never been run or the .lst lacks the echo.
        theta_inits  = model.get('theta_initials', [])
        theta_lowers = model.get('theta_lowers',   [])
        theta_uppers = model.get('theta_uppers',   [])
        omega_inits  = model.get('omega_initials', [])
        sigma_inits  = model.get('sigma_initials', [])

        blocks = [
            ('THETA', model.get('thetas',[]), model.get('theta_ses',[]),
             model.get('theta_names',[]), model.get('theta_units',[]), model.get('theta_fixed',[]), [], [],
             theta_inits, theta_lowers, theta_uppers),
            ('OMEGA', model.get('omegas',[]), model.get('omega_ses',[]),
             model.get('omega_names',[]), model.get('omega_units',[]), model.get('omega_fixed',[]), eta_shr, etabar_pval,
             omega_inits, [], []),
            ('SIGMA', model.get('sigmas',[]), model.get('sigma_ses',[]),
             model.get('sigma_names',[]), model.get('sigma_units',[]), model.get('sigma_fixed',[]), eps_shr, [],
             sigma_inits, [], []),
        ]

        # Build flat list with section header sentinels
        row_specs = []   # each entry: ('header', block) or ('data', block, ...)
        for block, ests, ses, names, units, fixed, shrinkage, etabar, inits, lowers, uppers in blocks:
            if not ests:
                continue
            row_specs.append(('header', block, len(ests)))
            for i, est in enumerate(ests):
                se  = ses[i]   if i < len(ses)   else None
                nm  = names[i] if i < len(names) else ''
                un  = units[i] if i < len(units) else ''
                fx  = fixed[i] if i < len(fixed) else False
                shr = shrinkage[i] if i < len(shrinkage) else None
                ebp = etabar[i]    if i < len(etabar)    else None
                init  = inits[i]  if i < len(inits)  else None
                lower = lowers[i] if i < len(lowers) else None
                upper = uppers[i] if i < len(uppers) else None
                pk  = f'{block}({i+1})'
                row_specs.append(('data', block, pk, nm, est,
                                  fmt_num(est), fmt_num(se) if se is not None else '...',
                                  fmt_rse(est, se), shr, ebp, un, fx,
                                  parent_params.get(pk),
                                  init, lower, upper))

        self._section_rows = {}
        self.table.setRowCount(len(row_specs))
        R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        L = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter
        grey = QBrush(QColor(C.fg2))
        changed_color = QColor(C.blue)

        # First pass: insert section header rows
        for ri, spec in enumerate(row_specs):
            if spec[0] != 'header':
                continue
            _, block, count = spec
            label = f'  \u25bc  {block}  ({count})'
            hdr_item = QTableWidgetItem(label)
            hdr_item.setData(Qt.ItemDataRole.UserRole, _SECTION_ROW_KEY)
            hdr_item.setData(Qt.ItemDataRole.UserRole + 1, block)
            hdr_item.setBackground(QBrush(QColor(C.bg3)))
            hdr_item.setForeground(QBrush(QColor(C.blue)))
            f = hdr_item.font(); f.setBold(True); f.setPointSize(10); hdr_item.setFont(f)
            self.table.setItem(ri, 0, hdr_item)
            self.table.setSpan(ri, 0, 1, 9)
            self.table.setRowHeight(ri, 24)
            self._section_rows[block] = (ri, [])

        # Second pass: fill data rows, register with section, set items
        for ri, spec in enumerate(row_specs):
            if spec[0] != 'data':
                continue
            _, block, lbl, nm, est_raw, est, se, rse, shr, ebp, un, fx, parent_val, init, lower, upper = spec
            self._section_rows[block][1].append(ri)

            changed_from_parent = False
            parent_tooltip = None
            if parent_val is not None and est_raw is not None:
                if abs(est_raw) > 1e-10:
                    changed_from_parent = abs(est_raw - parent_val) / abs(est_raw) * 100 > 0.1
                else:
                    changed_from_parent = abs(est_raw - parent_val) > 1e-6
                if changed_from_parent:
                    parent_tooltip = f'Changed from {fmt_num(parent_val)} in parent model'

            if shr is not None:
                shr_txt = f'{shr:.1f}'
                shr_color = QColor(C.green if shr < 20 else C.orange if shr < 30 else C.red)
            else:
                shr_txt = ''; shr_color = None

            if ebp is not None:
                ebp_txt = f'{ebp:.3f}' if ebp >= 0.001 else '<.001'
                ebp_color = QColor(C.red if ebp < 0.01 else C.orange if ebp < 0.05 else C.fg)
            else:
                ebp_txt = ''; ebp_color = None

            # Column 3 is the Init→Final viz column; populated separately below
            # with an empty item carrying _INIT_FINAL_ROLE payload (the delegate
            # paints from that role, ignoring the item's text).
            col_layout = [
                (lbl, L),        # 0 Param
                (nm,  L),        # 1 Name
                (est, R),        # 2 Estimate
                ('',  R),        # 3 Init→Final (painted by delegate)
                (se,  R),        # 4 SE
                (rse, R),        # 5 RSE%
                (shr_txt, R),    # 6 Shrink%
                (ebp_txt, R),    # 7 Etabar
                (un,  L),        # 8 Units
            ]
            for col, (txt, align) in enumerate(col_layout):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align)
                if col == 3:
                    # Init→Final viz cell — attach payload for the delegate.
                    # initial / final are floats; lower / upper may be None.
                    item.setData(_INIT_FINAL_ROLE, {
                        'initial': init,
                        'final':   est_raw,
                        'lower':   lower,
                        'upper':   upper,
                        'fixed':   fx,
                    })
                    # Tooltip with numeric detail
                    if init is not None and est_raw is not None:
                        try:
                            delta_pct = ((est_raw - init) / init * 100) if init else 0.0
                            delta_str = f'  ({delta_pct:+.1f}%)' if init else ''
                        except (TypeError, ZeroDivisionError):
                            delta_str = ''
                        bounds_str = (
                            f'[{fmt_num(lower)}, {fmt_num(upper)}]'
                            if (lower is not None and upper is not None)
                            else '(no upper bound)'
                            if (lower is None or upper is None)
                            else '—'
                        )
                        if fx:
                            item.setToolTip(f'FIXED at {fmt_num(init)}')
                        else:
                            item.setToolTip(
                                f'Initial: {fmt_num(init)}\n'
                                f'Final:   {fmt_num(est_raw)}{delta_str}\n'
                                f'Bounds:  {bounds_str}'
                            )
                    elif fx:
                        item.setToolTip('FIXED')
                    self.table.setItem(ri, col, item)
                    continue
                if fx:
                    item.setForeground(grey)
                    item.setToolTip('FIXED')
                # Highlight changed estimate (col 2 = Estimate)
                elif col == 2 and changed_from_parent:
                    item.setText(f'* {est}')
                    item.setForeground(QBrush(changed_color))
                    item.setToolTip(parent_tooltip)
                # Apply shrinkage color (Shrink% is now at column 6 after viz insertion)
                elif col == 6 and shr_color:
                    item.setForeground(QBrush(shr_color))
                    if shr is not None and shr >= 30:
                        item.setToolTip(f'High shrinkage ({shr:.1f}%) — parameter poorly estimated')
                    elif shr is not None and shr >= 20:
                        item.setToolTip(f'Moderate shrinkage ({shr:.1f}%)')
                # Apply etabar color (Etabar is now at column 7 after viz insertion)
                elif col == 7 and ebp is not None:
                    if ebp_color:
                        item.setForeground(QBrush(ebp_color))
                    if ebp < 0.01:
                        item.setToolTip(f'Significant etabar (p={ebp:.4f}) — systematic bias in random effect')
                    elif ebp < 0.05:
                        item.setToolTip(f'Marginally significant etabar (p={ebp:.3f})')
                self.table.setItem(ri, col, item)
