import math, logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsLineItem,
    QGraphicsTextItem, QGraphicsRectItem, QMenu,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QTimer
from PyQt6.QtGui import QBrush, QColor, QPen, QFont, QTransform
from ..app.theme import C, T, THEMES
from ..app import theme as _theme_mod

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

_log = logging.getLogger(__name__)


class AncestryTreeWidget(QWidget):
    """Interactive model ancestry/lineage tree using QGraphicsScene."""
    model_clicked = pyqtSignal(str)   # emits model stem

    NODE_W = 130; NODE_H = 46; H_GAP = 60; V_GAP = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._models = []
        self._current_stem = None
        self._selecting = False
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._view  = QGraphicsView(self._scene)
        self._view.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._view.setRenderHint(self._view.renderHints().__class__.Antialiasing, True)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.wheelEvent = self._wheel
        v.addWidget(self._view)  # must be here, not in showEvent
        # Connect selection signal exactly once
        self._scene.selectionChanged.connect(self._on_selection)

    def showEvent(self, event):
        """Fit tree into view when tab becomes visible (after _rebuild has run)."""
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_view)

    def _fit_view(self):
        if self._scene.items():
            bounds = self._scene.itemsBoundingRect().adjusted(-20,-20,20,20)
            self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def set_theme(self, bg, fg):
        self._scene.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._view.setBackgroundBrush(QBrush(QColor(C.bg)))
        self._rebuild()  # redraw nodes with new theme colours

    def load(self, models, current_stem=None):
        self._models    = models
        self._current_stem = current_stem
        self._rebuild()

    def _rebuild(self):
        from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem, QGraphicsLineItem, QGraphicsEllipseItem
        from PyQt6.QtGui import QPen, QPainterPath
        from PyQt6.QtWidgets import QGraphicsPathItem

        self._scene.clear()
        if not self._models: return

        # Build stem → model map and adjacency
        by_stem  = {m['stem']: m for m in self._models}
        children = {m['stem']: [] for m in self._models}
        roots    = []
        for m in self._models:
            p = m.get('based_on')
            if p and p in by_stem:
                children[p].append(m['stem'])
            else:
                roots.append(m['stem'])

        if not roots:  # cycle or all have unknown parents — show all as roots
            roots = [m['stem'] for m in self._models]

        # Assign (col, row) positions using BFS level layout
        pos   = {}   # stem → (col, row) where col = depth, row = sibling index
        depth_counts = {}
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
                    queue.append((ch, depth+1))

        # Handle any models not reachable from roots (orphans)
        max_depth = max((v[0] for v in pos.values()), default=0) + 1
        orphan_row = 0
        for m in self._models:
            if m['stem'] not in pos:
                pos[m['stem']] = (max_depth, orphan_row)
                orphan_row += 1

        NW = self.NODE_W; NH = self.NODE_H; HG = self.H_GAP; VG = self.V_GAP

        def node_rect(stem):
            col, row = pos[stem]
            x = col * (NW + HG)
            y = row * (NH + VG)
            return x, y, NW, NH

        # Draw edges first (behind nodes)
        pen_edge = QPen(QColor(C.border)); pen_edge.setWidth(2)
        for stem in pos:
            m = by_stem.get(stem)
            if not m: continue
            parent = m.get('based_on')
            if parent and parent in pos:
                px, py, pw, ph = node_rect(parent)
                cx, cy, cw, ch = node_rect(stem)
                # Elbow connector: right-centre of parent → left-centre of child
                x1 = px + pw; y1 = py + ph/2
                x2 = cx;      y2 = cy + ch/2
                mid_x = (x1 + x2) / 2
                path = QPainterPath()
                path.moveTo(x1, y1)
                path.cubicTo(mid_x, y1, mid_x, y2, x2, y2)
                pi = QGraphicsPathItem(path)
                pi.setPen(pen_edge)
                self._scene.addItem(pi)

        # Draw nodes
        for stem, (col, row) in pos.items():
            m  = by_stem.get(stem, {})
            x, y, w, h = node_rect(stem)
            is_current = (stem == self._current_stem)
            is_ok      = m.get('minimization_successful') is True
            is_fail    = m.get('minimization_successful') is False

            # Background colour
            if is_current:
                fill = QColor(C.blue)
            elif is_ok:
                fill = QColor('#1a3a2a') if _theme_mod._active_theme == 'dark' else QColor('#e6f4ed')
            elif is_fail:
                fill = QColor('#3a1a1a') if _theme_mod._active_theme == 'dark' else QColor('#fce8e8')
            else:
                # Neutral: use BG3 which contrasts against the scene background in both themes
                fill = QColor(C.bg3)

            border_col = QColor(C.blue if is_current else C.border)
            pen_node   = QPen(border_col); pen_node.setWidth(2 if is_current else 1)

            rect = QGraphicsRectItem(x, y, w, h)
            rect.setBrush(QBrush(fill)); rect.setPen(pen_node)
            rect.setData(0, stem)
            rect.setAcceptHoverEvents(True)
            rect.setFlag(rect.GraphicsItemFlag.ItemIsSelectable, True)
            self._scene.addItem(rect)

            # Star
            if m.get('star'):
                star = self._scene.addText('*')
                star.setDefaultTextColor(QColor('#f5c518'))
                star.setPos(x + 4, y + 2)
                f = star.font(); f.setPointSize(9); star.setFont(f)
                sx = 16
            else:
                sx = 4

            # Status dot
            dot_col = QColor(C.green if is_ok else C.red if is_fail else C.fg2)
            dot = QGraphicsEllipseItem(x + w - 12, y + h/2 - 4, 8, 8)
            dot.setBrush(QBrush(dot_col)); dot.setPen(QPen(Qt.PenStyle.NoPen))
            self._scene.addItem(dot)

            # Stem label
            lbl = self._scene.addText(stem)
            lbl.setDefaultTextColor(QColor('#ffffff' if is_current else C.fg))
            lbl.setPos(x + sx, y + 2)
            f = lbl.font(); f.setPointSize(10); f.setBold(is_current); lbl.setFont(f)
            lbl.setTextWidth(w - sx - 16)

            # OFV
            ofv = m.get('ofv')
            if ofv is not None:
                olbl = self._scene.addText(f'{ofv:.2f}')
                olbl.setDefaultTextColor(QColor('#aaaacc' if is_current else C.fg2))
                f2 = olbl.font(); f2.setPointSize(8); olbl.setFont(f2)
                olbl.setPos(x + sx, y + h - 18)

        # Wire click via scene
        self._view.setScene(self._scene)  # ensure view tracks scene after clear
        bounds = self._scene.itemsBoundingRect().adjusted(-20,-20,20,20)
        self._scene.setSceneRect(bounds)
        # fitInView only works when widget is visible
        if self.isVisible():
            self._view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            QTimer.singleShot(50, self._fit_view)

    def _on_selection(self):
        if getattr(self, '_selecting', False): return
        items = self._scene.selectedItems()
        for item in items:
            stem = item.data(0)
            if stem:
                self._selecting = True
                # Defer emit — switching tabs inside selectionChanged causes segfault
                QTimer.singleShot(0, lambda s=stem: self._emit_clicked(s))
                return

    def _emit_clicked(self, stem):
        try:
            self.model_clicked.emit(stem)
        finally:
            self._selecting = False

    def _wheel(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        self._view.scale(factor, factor)

    def set_current(self, stem):
        self._current_stem = stem
        self._rebuild()
