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


def _format_ratio(ratio: float) -> str:
    """Compact log-ratio label: '×1.6', '×0.50', '×12'. Cross-OS-safe (Latin-1)."""
    if ratio >= 10:
        return f'×{ratio:.0f}'    # ×12, ×100
    if ratio >= 1:
        return f'×{ratio:.1f}'    # ×1.0, ×1.3, ×9.8
    if ratio >= 0.1:
        return f'×{ratio:.2f}'    # ×0.50, ×0.71
    return f'×{ratio:.0e}'        # ×1e-02 (rare)


def _format_compact(v: float) -> str:
    """Compact numeric for fallback badges. ~5 chars max."""
    if v == 0:
        return '0'
    av = abs(v)
    if av >= 1000:
        return f'{v:.0f}'
    if av >= 1:
        return f'{v:.1f}'
    if av >= 0.01:
        return f'{v:.2f}'
    return f'{v:.0e}'


class InitialVsFinalDelegate(QStyledItemDelegate):
    """Log-scale ratio visualization of initial → final estimate.

    Reads its payload from item.data(_INIT_FINAL_ROLE) as a dict:
        {'initial': float, 'final': float,
         'lower': float|None, 'upper': float|None, 'fixed': bool}

    Rendering (cross-OS safe — pure QPainter primitives + Latin-1 '×'):

      - FIXED: thin full-width grey line, no marker.  Reads visually as
        "frozen — no movement possible."  (The 'FIX' italic on the
        parameter name already conveys the FIX state in words.)

      - Same-sign positive parameters (the normal PK case):
        Track spans 0.1× → 10× initial on a log scale (2 decades).
        Center tick at 1×.  Filled circle at log10(final/initial),
        clamped to ends.  Chevron at the clamp when off-scale (>10× or
        <0.1×).  Inline '×N' numeric label to the right of the bar.

      - Both negative or sign-change: ratio undefined or misleading,
        fall back to a numeric delta badge 'Δ±X' (no bar).

      - initial == 0: ratio undefined, fall back to absolute final badge.

      - No data (initial or final is None): blank cell.

      - At/within 1% of a bound: red marker + red wall-line at the
        track edge corresponding to the bound. This signal is
        independent of the log-ratio scale, so wide bounds no longer
        suppress it.

    Color (driven by |log10(final/initial)|, matching ratio magnitudes):
        < 0.04   (within ~10%)  : subtle grey
        < 0.18   (within ~50%)  : accent blue
        >= 0.18                 : orange
        at bound                : red

    v2.9.21 — replaces the v2.9.18 bullet-bar that collapsed for the
    common NONMEM convention `$THETA (0, init, 1e6)`.
    """

    # Layout constants — log-ratio bar plus an inline numeric label
    _PAD_X         = 6
    _LABEL_W       = 32           # px reserved on right for '×N' text
    _TRACK_H       = 4
    _DEC_RANGE     = 1.0          # ±1 decade (0.1× to 10×)
    _THRESH_SUBTLE = 0.04         # |log10| < this → grey (~10% move)
    _THRESH_MID    = 0.18         # |log10| < this → blue (~50% move)
    _LABEL_FONT_PT = 8

    def paint(self, painter, option, index):
        super().paint(painter, option, index)

        data = index.data(_INIT_FINAL_ROLE)
        if not isinstance(data, dict):
            return
        initial = data.get('initial')
        final   = data.get('final')
        if initial is None or final is None:
            return

        lower = data.get('lower')
        upper = data.get('upper')
        fixed = bool(data.get('fixed', False))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cell = option.rect
        cy   = cell.center().y()
        track_left  = cell.left() + self._PAD_X
        track_right = cell.right() - self._PAD_X - self._LABEL_W
        if track_right <= track_left + 10:
            painter.restore()
            return
        track_top   = cy - self._TRACK_H // 2
        label_rect  = QRect(track_right + 4, cell.top(),
                            self._LABEL_W, cell.height())

        # ── FIXED — quiet full-width line, no marker, no label ──────────
        if fixed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C.bg3))
            painter.drawRoundedRect(
                QRect(track_left, track_top,
                      (track_right + self._LABEL_W) - track_left, self._TRACK_H),
                2, 2,
            )
            painter.restore()
            return

        # ── Fallback for ratio-undefined cases ──────────────────────────
        same_sign_pos = (initial > 0 and final > 0)
        same_sign_neg = (initial < 0 and final < 0)
        if not (same_sign_pos or same_sign_neg):
            # Sign change or zero initial → numeric badge in the cell
            self._draw_fallback_badge(painter, cell, initial, final)
            painter.restore()
            return

        # Use |final| / |initial| so the same-sign-negative case still works
        ratio = (final / initial) if same_sign_pos else (final / initial)
        # (For same-sign-negative, final/initial is mathematically positive.)
        import math
        try:
            log_ratio = math.log10(ratio)
        except (ValueError, ZeroDivisionError):
            self._draw_fallback_badge(painter, cell, initial, final)
            painter.restore()
            return

        # ── Bound proximity (independent of log scale) ──────────────────
        at_upper = (
            upper is not None and abs(upper) > 1e-12
            and final >= upper - abs(upper) * 0.01
        )
        at_lower = (
            lower is not None and abs(lower) > 1e-12
            and final <= lower + abs(lower) * 0.01
        )
        at_bound = at_upper or at_lower

        # ── Marker color from |log_ratio| ───────────────────────────────
        abs_log = abs(log_ratio)
        if at_bound:
            marker_color = QColor(C.red)
        elif abs_log >= self._THRESH_MID:
            marker_color = QColor(C.orange)
        elif abs_log >= self._THRESH_SUBTLE:
            marker_color = QColor(C.blue)
        else:
            marker_color = QColor(C.fg2)

        # ── Track ────────────────────────────────────────────────────────
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C.bg3))
        painter.drawRoundedRect(
            QRect(track_left, track_top, track_right - track_left, self._TRACK_H),
            2, 2,
        )

        # ── Center tick at 1× (initial reference) ───────────────────────
        x_init = (track_left + track_right) // 2
        painter.setPen(QPen(QColor(C.fg3), 1))
        painter.drawLine(x_init, track_top - 3, x_init, track_top + self._TRACK_H + 3)

        # ── Marker (circle, or chevron if off-scale) ────────────────────
        off_scale_right = log_ratio > self._DEC_RANGE
        off_scale_left  = log_ratio < -self._DEC_RANGE
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(marker_color)
        if off_scale_right:
            painter.drawPolygon(QPolygon([
                QPoint(track_right - 5, cy - 4),
                QPoint(track_right,     cy),
                QPoint(track_right - 5, cy + 4),
            ]))
        elif off_scale_left:
            painter.drawPolygon(QPolygon([
                QPoint(track_left + 5, cy - 4),
                QPoint(track_left,     cy),
                QPoint(track_left + 5, cy + 4),
            ]))
        else:
            # Map log_ratio in [-DEC_RANGE, +DEC_RANGE] to track x
            frac = (log_ratio + self._DEC_RANGE) / (2 * self._DEC_RANGE)
            x_mark = int(round(track_left + frac * (track_right - track_left)))
            painter.drawEllipse(QPoint(x_mark, cy), 3, 3)

        # ── At-bound red wall ────────────────────────────────────────────
        if at_bound:
            bound_x = track_right if at_upper else track_left
            painter.setPen(QPen(QColor(C.red), 1))
            painter.drawLine(bound_x, track_top - 4, bound_x, track_top + self._TRACK_H + 4)

        # ── Numeric ratio label ──────────────────────────────────────────
        font = painter.font()
        font.setPointSize(self._LABEL_FONT_PT)
        painter.setFont(font)
        painter.setPen(QColor(C.fg2))
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            _format_ratio(ratio),
        )

        painter.restore()

    def _draw_fallback_badge(self, painter, cell, initial, final):
        """Render a numeric badge for sign-change / zero-initial cases.

        ASCII-only (no →, Δ, or other non-Latin-1 glyphs) for full cross-OS
        font compatibility. The absence of a track/marker IS the signal
        that this is a noteworthy edge case.
        """
        if initial == 0:
            text = _format_compact(final)            # bare final value
        elif final == 0:
            text = '0'
        else:
            delta = final - initial
            sign  = '+' if delta >= 0 else ''
            text  = f'{sign}{_format_compact(delta)}'   # '+0.5' / '-0.3'

        # Color by relative magnitude
        try:
            rel = abs(final - initial) / max(abs(initial), 1e-12)
        except Exception:
            rel = 0.0
        if rel >= 0.5:
            color = QColor(C.orange)
        elif rel >= 0.1:
            color = QColor(C.blue)
        else:
            color = QColor(C.fg2)

        font = painter.font()
        font.setPointSize(self._LABEL_FONT_PT)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(
            cell.adjusted(self._PAD_X, 0, -self._PAD_X, 0),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )


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
        hh.resizeSection(3, 110)  # Init→Final viz column (log-ratio bar + ×N label)
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
