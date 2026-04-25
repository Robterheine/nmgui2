import math, logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsPathItem, QMenu, QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QBrush, QColor, QPen, QFont, QImage, QPainter
from ..app.theme import C, T, THEMES
from ..app import theme as _theme_mod

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

_log = logging.getLogger(__name__)


def _build_node_tooltip(m: dict) -> str:
    """Info-tab style tooltip from model dict fields."""
    lines = []

    # Header
    header = m.get('stem', '?')
    if m.get('status_tag'): header += f"  [{m['status_tag']}]"
    if m.get('star'):       header += '  ★'
    lines.append(header)
    if m.get('comment'):
        lines.append(m['comment'])
    lines.append('─' * 32)

    # Dataset
    if m.get('data_file'):
        lines.append(f"File:     {m['data_file']}")
    ni = m.get('n_individuals'); no = m.get('n_observations'); npa = m.get('n_estimated_params')
    if ni or no:
        seg = f"Ind: {ni}  Obs: {no}" if ni and no else (f"Ind: {ni}" if ni else f"Obs: {no}")
        if npa: seg += f"  Params: {npa}"
        lines.append(seg)
    elif npa:
        lines.append(f"Params:   {npa}")

    # Run results
    ofv = m.get('ofv'); aic = m.get('aic')
    if ofv is not None:
        seg = f"OFV:      {ofv:.3f}"
        if aic is not None: seg += f"   AIC: {aic:.3f}"
        lines.append(seg)

    meth = m.get('estimation_method')
    cov  = m.get('covariance_step')
    cn   = m.get('condition_number')
    rp = []
    if meth:            rp.append(f"Method: {meth}")
    if cov is not None: rp.append(f"COV: {'✓' if cov else '✗'}")
    if cn  is not None: rp.append(f"CN: {cn:.0f}")
    if rp: lines.append('  │  '.join(rp))

    rt = m.get('runtime')
    if rt is not None:
        lines.append(f"Runtime:  {rt:.0f}s" if rt < 3600 else f"Runtime:  {rt/3600:.1f}h")

    # Lineage / status
    if m.get('based_on'):
        lines.append(f"Based on: {m['based_on']}")
    msg = (m.get('minimization_message') or '').strip()
    if msg: lines.append(f"Status:   {msg}")

    # Notes
    notes = (m.get('notes') or '').strip()
    if notes:
        lines.append('─' * 32)
        if len(notes) > 220: notes = notes[:217] + '…'
        lines.append(notes)

    return '\n'.join(lines)


class AncestryTreeWidget(QWidget):
    """Interactive model ancestry/lineage tree using QGraphicsScene."""
    model_clicked = pyqtSignal(str)   # emits model stem

    NODE_W = 140; NODE_H = 54; H_GAP = 72; V_GAP = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._models = []
        self._current_stem = None
        self._selecting = False

        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QWidget(); toolbar.setFixedHeight(32); toolbar.setObjectName('pillBar')
        tb = QHBoxLayout(toolbar); tb.setContentsMargins(8, 4, 8, 4); tb.setSpacing(4)

        for color, label in [(C.green, 'Converged'), (C.red, 'Failed'), (C.fg2, 'Not run')]:
            dot = QLabel('●'); dot.setStyleSheet(f'color: {color}; font-size: 11px;')
            lbl = QLabel(label); lbl.setObjectName('muted')
            tb.addWidget(dot); tb.addWidget(lbl); tb.addSpacing(8)

        stale_dot = QLabel('!'); stale_dot.setStyleSheet(
            f'color: {C.orange}; font-weight: bold; font-size: 12px;')
        stale_lbl = QLabel('Stale'); stale_lbl.setObjectName('muted')
        tb.addWidget(stale_dot); tb.addWidget(stale_lbl)

        tb.addStretch()

        fit_btn = QPushButton('⊞ Fit'); fit_btn.setFixedHeight(24); fit_btn.setFixedWidth(58)
        fit_btn.setToolTip('Fit entire tree into view\n(or double-click the canvas background)')
        fit_btn.clicked.connect(self._fit_view)
        export_btn = QPushButton('Export PNG…'); export_btn.setFixedHeight(24)
        export_btn.setToolTip('Save the tree as a PNG image')
        export_btn.clicked.connect(self._export_png)
        tb.addWidget(fit_btn); tb.addWidget(export_btn)
        v.addWidget(toolbar)

        # ── Scene / view ──────────────────────────────────────────────────────
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._view  = QGraphicsView(self._scene)
        self._view.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._view.setRenderHint(self._view.renderHints().__class__.Antialiasing, True)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.wheelEvent = self._wheel
        self._view.mouseDoubleClickEvent = self._view_dbl_click
        v.addWidget(self._view)

        self._scene.selectionChanged.connect(self._on_selection)

    # ── Interaction helpers ───────────────────────────────────────────────────

    def _view_dbl_click(self, event):
        """Double-click on empty canvas background resets zoom to fit."""
        if self._view.itemAt(event.pos()) is None:
            self._fit_view()
        else:
            QGraphicsView.mouseDoubleClickEvent(self._view, event)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_view)

    def _fit_view(self):
        if self._scene.items():
            bounds = self._scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
            self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def _wheel(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._view.scale(factor, factor)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_theme(self, bg, fg):
        self._scene.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._view.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._rebuild()

    def load(self, models, current_stem=None):
        self._models       = models
        self._current_stem = current_stem
        self._rebuild()

    def set_current(self, stem):
        self._current_stem = stem
        self._rebuild()

    # ── Layout & drawing ─────────────────────────────────────────────────────

    def _rebuild(self):
        from PyQt6.QtGui import QPainterPath

        self._scene.clear()
        if not self._models:
            return

        # Global best OFV (for Δbest labels on nodes)
        ofvs     = [m['ofv'] for m in self._models if m.get('ofv') is not None]
        best_ofv = min(ofvs) if ofvs else None

        # ── Adjacency ─────────────────────────────────────────────────────────
        by_stem  = {m['stem']: m for m in self._models}
        children = {m['stem']: [] for m in self._models}
        roots    = []
        for m in self._models:
            p = m.get('based_on')
            if p and p in by_stem:
                children[p].append(m['stem'])
            else:
                roots.append(m['stem'])
        if not roots:
            roots = [m['stem'] for m in self._models]

        # ── BFS layout (col = depth, row = sibling index) ─────────────────────
        pos = {}; depth_counts = {}
        queue = [(r, 0) for r in sorted(roots)]
        visited = set()
        while queue:
            stem, depth = queue.pop(0)
            if stem in visited: continue
            visited.add(stem)
            row = depth_counts.get(depth, 0)
            depth_counts[depth] = row + 1
            pos[stem] = (depth, row)
            for ch in sorted(children.get(stem, [])):
                if ch not in visited:
                    queue.append((ch, depth + 1))

        # Orphans (unreachable from roots)
        max_depth = max((v[0] for v in pos.values()), default=0) + 1
        orphan_row = 0
        for m in self._models:
            if m['stem'] not in pos:
                pos[m['stem']] = (max_depth, orphan_row); orphan_row += 1

        NW = self.NODE_W; NH = self.NODE_H; HG = self.H_GAP; VG = self.V_GAP

        def node_rect(stem):
            col, row = pos[stem]
            return col * (NW + HG), row * (NH + VG), NW, NH

        # ── Generation labels (above each column) ─────────────────────────────
        for depth in sorted(set(c for c, _ in pos.values())):
            label = 'Base' if depth == 0 else f'Gen {depth}'
            gen_lbl = self._scene.addText(label)
            gen_lbl.setDefaultTextColor(QColor(C.fg2))
            gf = gen_lbl.font(); gf.setPointSize(7); gen_lbl.setFont(gf)
            gen_lbl.setPos(depth * (NW + HG), -22)

        # ── Edges + dOFV labels ───────────────────────────────────────────────
        pen_edge = QPen(QColor(C.border)); pen_edge.setWidth(2)
        for stem in pos:
            m = by_stem.get(stem)
            if not m: continue
            parent = m.get('based_on')
            if not (parent and parent in pos): continue

            px, py, pw, ph = node_rect(parent)
            cx, cy, cw, ch = node_rect(stem)
            x1 = px + pw;  y1 = py + ph / 2
            x2 = cx;       y2 = cy + ch / 2
            mid_x = (x1 + x2) / 2

            # Bezier connector
            path = QPainterPath()
            path.moveTo(x1, y1)
            path.cubicTo(mid_x, y1, mid_x, y2, x2, y2)
            pi = QGraphicsPathItem(path)
            pi.setPen(pen_edge)
            self._scene.addItem(pi)

            # dOFV label at bezier midpoint (mid_x, midY)
            c_ofv = m.get('ofv')
            p_ofv = by_stem.get(parent, {}).get('ofv')
            if c_ofv is not None and p_ofv is not None:
                delta  = c_ofv - p_ofv
                d_txt  = f'{delta:+.1f}'
                if   delta < -0.5: d_col = QColor(C.green)
                elif delta >  0.5: d_col = QColor(C.orange)
                else:              d_col = QColor(C.fg2)

                lx = mid_x; ly = (y1 + y2) / 2
                # Build text item first (not yet in scene) to measure width
                t = QGraphicsTextItem(d_txt)
                tf = t.font(); tf.setPointSize(7); tf.setBold(True); t.setFont(tf)
                t.setDefaultTextColor(d_col)
                tw = t.boundingRect().width(); th = t.boundingRect().height()
                # Background pill — add before text so text renders on top
                bg = QGraphicsRectItem(lx - tw/2 - 2, ly - th/2 - 1, tw + 4, th + 2)
                bg.setBrush(QBrush(QColor(C.bg))); bg.setPen(QPen(QColor(C.border)))
                self._scene.addItem(bg)
                t.setPos(lx - tw/2, ly - th/2)
                self._scene.addItem(t)

        # ── Nodes ─────────────────────────────────────────────────────────────
        for stem, (col, row) in pos.items():
            m        = by_stem.get(stem, {})
            x, y, w, h = node_rect(stem)
            is_current = (stem == self._current_stem)
            is_ok      = m.get('minimization_successful') is True
            is_fail    = m.get('minimization_successful') is False
            has_run    = bool(m.get('has_run'))
            is_stale   = bool(m.get('stale'))

            tooltip = _build_node_tooltip(m)

            # Background fill
            if is_current:
                fill = QColor(C.blue)
            elif is_ok:
                fill = QColor('#1a3a2a') if _theme_mod._active_theme == 'dark' else QColor('#e6f4ed')
            elif is_fail:
                fill = QColor('#3a1a1a') if _theme_mod._active_theme == 'dark' else QColor('#fce8e8')
            else:
                fill = QColor(C.bg3)

            border_col = QColor(C.blue if is_current else C.border)
            pen_node   = QPen(border_col)
            pen_node.setWidth(2 if is_current else 1)
            if not has_run:                          # dashed outline = not yet run
                pen_node.setStyle(Qt.PenStyle.DashLine)

            rect = QGraphicsRectItem(x, y, w, h)
            rect.setBrush(QBrush(fill)); rect.setPen(pen_node)
            rect.setData(0, stem)
            rect.setAcceptHoverEvents(True)
            rect.setFlag(rect.GraphicsItemFlag.ItemIsSelectable, True)
            rect.setToolTip(tooltip)
            self._scene.addItem(rect)

            # Star (top-left)
            sx = 4
            if m.get('star'):
                star = self._scene.addText('★')
                star.setDefaultTextColor(QColor('#f5c518'))
                sf = star.font(); sf.setPointSize(8); star.setFont(sf)
                star.setPos(x + 3, y + 1)
                star.setToolTip(tooltip)
                sx = 16

            # Status dot (top-right)
            dot_col = QColor(C.green if is_ok else C.red if is_fail else C.fg2)
            dot = QGraphicsEllipseItem(x + w - 12, y + 6, 8, 8)
            dot.setBrush(QBrush(dot_col)); dot.setPen(QPen(Qt.PenStyle.NoPen))
            dot.setToolTip(tooltip)
            self._scene.addItem(dot)

            # Stale badge — orange ! just left of status dot
            if is_stale:
                si = self._scene.addText('!')
                si.setDefaultTextColor(QColor(C.orange))
                sf2 = si.font(); sf2.setPointSize(8); sf2.setBold(True); si.setFont(sf2)
                si.setPos(x + w - 24, y + 1)
                si.setToolTip(tooltip)

            # Row 1 — stem name
            name_lbl = self._scene.addText(stem)
            name_lbl.setDefaultTextColor(QColor('#ffffff' if is_current else C.fg))
            nf = name_lbl.font(); nf.setPointSize(10); nf.setBold(is_current); name_lbl.setFont(nf)
            name_lbl.setPos(x + sx, y + 2)
            name_lbl.setTextWidth(w - sx - 20)
            name_lbl.setToolTip(tooltip)

            # Row 2 — OFV + Δ from global best
            ofv = m.get('ofv')
            if ofv is not None:
                ofv_str = f'{ofv:.2f}'
                if best_ofv is not None:
                    d = ofv - best_ofv
                    ofv_str += ('  ★' if abs(d) < 0.01 else f'  Δ{d:+.1f}')
                olbl = self._scene.addText(ofv_str)
                olbl.setDefaultTextColor(QColor('#aaaacc' if is_current else C.fg2))
                of2 = olbl.font(); of2.setPointSize(8); olbl.setFont(of2)
                olbl.setPos(x + sx, y + 21)
                olbl.setTextWidth(w - sx - 4)
                olbl.setToolTip(tooltip)

            # Row 3 — method (left) + COV ✓/✗ (right, coloured)
            meth = m.get('estimation_method', '')
            cov  = m.get('covariance_step')
            muted = '#ccccee' if is_current else C.fg2

            if meth:
                m_lbl = self._scene.addText(meth[:9])
                m_lbl.setDefaultTextColor(QColor(muted))
                mf = m_lbl.font(); mf.setPointSize(7); m_lbl.setFont(mf)
                m_lbl.setPos(x + sx, y + 38)
                m_lbl.setToolTip(tooltip)

            if cov is not None:
                c_lbl = self._scene.addText('✓' if cov else '✗')
                c_lbl.setDefaultTextColor(QColor(C.green if cov else C.red))
                cf = c_lbl.font(); cf.setPointSize(9); c_lbl.setFont(cf)
                c_lbl.setPos(x + w - 20, y + 36)
                c_lbl.setToolTip(tooltip)

        # ── Finalise ──────────────────────────────────────────────────────────
        self._view.setScene(self._scene)
        bounds = self._scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        self._scene.setSceneRect(bounds)
        if self.isVisible():
            self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            QTimer.singleShot(50, self._fit_view)

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_selection(self):
        if getattr(self, '_selecting', False): return
        for item in self._scene.selectedItems():
            stem = item.data(0)
            if stem:
                self._selecting = True
                QTimer.singleShot(0, lambda s=stem: self._emit_clicked(s))
                return

    def _emit_clicked(self, stem):
        try:
            self.model_clicked.emit(stem)
        finally:
            self._selecting = False

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export model tree as PNG', 'model_tree.png', 'PNG (*.png)')
        if not path:
            return
        bounds = self._scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        img = QImage(int(bounds.width()), int(bounds.height()),
                     QImage.Format.Format_ARGB32)
        img.fill(QColor(C.bg))
        p = QPainter(img)
        self._scene.render(p, source=bounds)
        p.end()
        img.save(path)
