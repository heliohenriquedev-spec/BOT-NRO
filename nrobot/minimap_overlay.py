"""REDE-76: minimap over the corner of the game: ground, walked route, patrol plan, characters.

Reads the files the relay writes in the session folder: minimapa_chao.json (walkable ground,
once per map) and minimapa_rota.json (walked trail, patrol waypoints done/remaining, current
goal and route). North is up, like the game's own map. The window never takes focus from the
game: "+" / "-" resize it, the mouse wheel zooms around the character, dragging moves it.
"""
import base64
import json
import zlib

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .radar_overlay import game_client_rect

HEADER = 22
FOOTER = 34


def ground_image(width, height, cells):
    """Walkable cells as a north-up RGBA image (row 0 = highest y)."""
    grid = np.frombuffer(cells, dtype=np.uint8).reshape(height, width)[::-1]
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[grid != 0] = (58, 68, 84, 235)
    rgba[grid == 0] = (8, 10, 14, 150)
    image = QImage(rgba.tobytes(), width, height, width*4, QImage.Format_RGBA8888)
    return image.copy()


class MinimapOverlay(QWidget):
    SIDES = (180, 240, 300, 380, 480, 600)
    ZOOMS = (1, 1.5, 2, 3, 4, 6)

    def __init__(self):
        super().__init__(None)
        self.state = {}
        self.ground = None  # {'map', 'width', 'height', 'image'}
        self.route = {}
        self.mtimes = {}
        self.side_index = 2
        self.zoom_index = 0
        self.offset = None  # position relative to the game's client area once dragged
        self.drag = None
        self.on_change = lambda: None  # size, zoom or position changed: the panel saves them
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.apply_size()

    # -- data -------------------------------------------------------------------------
    @property
    def side(self):
        return self.SIDES[self.side_index]

    def apply_size(self):
        self.resize(self.side, self.side+HEADER+FOOTER)
        self.update()

    def update_state(self, state):
        self.state = state or {}
        self.update()

    def load(self, folder):
        """Reload the relay's minimap files when they changed on disk."""
        for name in ('minimapa_chao.json', 'minimapa_rota.json'):
            path = folder/name
            try:
                mtime = path.stat().st_mtime_ns
                if self.mtimes.get(name) == mtime:
                    continue
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            self.mtimes[name] = mtime
            if name == 'minimapa_chao.json':
                cells = zlib.decompress(base64.b64decode(data['cells']))
                self.ground = {'map': data['map'], 'width': data['width'], 'height': data['height'],
                               'image': ground_image(data['width'], data['height'], cells)}
            else:
                self.route = data
        self.update()

    def follow_game(self):
        rect = game_client_rect()
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1
        if rect is None:
            return False
        x, y, width, height = (value/ratio for value in rect)
        if self.offset is None:
            target = (x+width-self.width()-10, y+10)
        else:
            target = (x+self.offset[0], y+self.offset[1])
        if (int(target[0]), int(target[1])) != (self.x(), self.y()):
            self.move(int(target[0]), int(target[1]))
        return True

    # -- geometry -----------------------------------------------------------------------
    def view(self):
        """(x0, y_top, span) in cells for the drawn square."""
        if self.ground is None:
            return None
        width, height = self.ground['width'], self.ground['height']
        span = max(width, height)/self.ZOOMS[self.zoom_index]
        own = self.state.get('player_position')
        if self.zoom_index == 0 or own is None:
            return ((width-span)/2, (height+span)/2, span)
        x0 = min(max(own[0]-span/2, 0), max(width-span, 0))
        top = max(min(own[1]+span/2, height), min(span, height))
        return (x0, top, span)

    def cell_point(self, cell, view):
        x0, top, span = view
        scale = self.side/span
        return QPointF((cell[0]+.5-x0)*scale, HEADER+(top-cell[1]-.5)*scale)

    def map_rect(self):
        return QRectF(0, HEADER, self.side, self.side)

    def buttons(self):
        return {'+': QRectF(self.side-44, 2, 18, 18), '-': QRectF(self.side-22, 2, 18, 18)}

    # -- input --------------------------------------------------------------------------
    def mousePressEvent(self, event):
        point = event.position()
        for label, rect in self.buttons().items():
            if rect.contains(point):
                step = 1 if label == '+' else -1
                self.side_index = max(0, min(len(self.SIDES)-1, self.side_index+step))
                self.apply_size()
                if self.offset is None:
                    self.follow_game()
                self.on_change()
                return
        self.drag = event.globalPosition()-QPointF(self.x(), self.y())

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            target = event.globalPosition()-self.drag
            self.move(int(target.x()), int(target.y()))

    def mouseReleaseEvent(self, event):
        if self.drag is None:
            return
        self.drag = None
        rect = game_client_rect()
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1
        if rect is not None:
            self.offset = (self.x()-rect[0]/ratio, self.y()-rect[1]/ratio)
            self.on_change()

    def wheelEvent(self, event):
        step = 1 if event.angleDelta().y() > 0 else -1
        self.zoom_index = max(0, min(len(self.ZOOMS)-1, self.zoom_index+step))
        self.update()
        self.on_change()

    def layout_state(self):
        return {'side_index': self.side_index, 'zoom_index': self.zoom_index,
                'offset': list(self.offset) if self.offset is not None else None}

    def restore_layout(self, state):
        state = state or {}
        self.side_index = max(0, min(len(self.SIDES)-1, int(state.get('side_index', self.side_index))))
        self.zoom_index = max(0, min(len(self.ZOOMS)-1, int(state.get('zoom_index', self.zoom_index))))
        offset = state.get('offset')
        self.offset = tuple(offset) if offset else None
        self.apply_size()

    # -- drawing ------------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QPen(QColor(110, 120, 135), 1.5))
        painter.setBrush(QColor(12, 14, 20, 210))
        painter.drawRoundedRect(QRectF(.5, .5, self.width()-1, self.height()-1), 8, 8)
        self.draw_header(painter)
        view = self.view()
        map_name = self.state.get('map_name')
        if view is None or (map_name and self.ground['map'] != map_name):
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.map_rect(), Qt.AlignCenter | Qt.TextWordWrap,
                             'Aguardando o mapa de colisão\n(entre no personagem com o bot conectado)')
            return
        painter.save()
        painter.setClipRect(self.map_rect())
        x0, top, span = view
        scale = self.side/span
        source = QRectF(x0, self.ground['height']-top, span, span)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawImage(self.map_rect(), self.ground['image'], source)
        same_map = self.route.get('map') == self.ground['map']
        if same_map:
            self.draw_route(painter, view, scale)
        self.draw_characters(painter, view)
        painter.restore()
        self.draw_footer(painter, same_map)

    def draw_header(self, painter):
        painter.setPen(QColor(225, 225, 225))
        name = (self.ground or {}).get('map') or self.state.get('map_name') or 'minimapa'
        zoom = self.ZOOMS[self.zoom_index]
        painter.drawText(QRectF(8, 2, self.side-60, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         f"{name.replace('.gat', '')}  •  zoom {zoom:g}x (roda do mouse)")
        for label, rect in self.buttons().items():
            painter.setPen(QPen(QColor(150, 160, 175), 1))
            painter.setBrush(QColor(40, 46, 58, 230))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(rect, Qt.AlignCenter, label)

    def draw_route(self, painter, view, scale):
        coverage = self.route.get('coverage') or {}
        waypoints = coverage.get('waypoints') or {}
        done = {tuple(block) for block in coverage.get('done', [])}
        dot = max(1.6, min(4.0, scale*1.6))
        painter.setPen(Qt.NoPen)
        for key, point in waypoints.items():
            block = tuple(int(v) for v in key.split(','))
            if block in done:
                painter.setBrush(QColor(120, 130, 140, 120))  # already passed
                painter.drawEllipse(self.cell_point(point, view), dot*.6, dot*.6)
            else:
                painter.setBrush(QColor(40, 230, 120, 230))  # still to visit: patrol priority
                painter.drawEllipse(self.cell_point(point, view), dot, dot)
        trail = self.route.get('trail') or []
        if len(trail) > 1:
            path = QPainterPath(self.cell_point(trail[0], view))
            for cell in trail[1:]:
                path.lineTo(self.cell_point(cell, view))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(70, 150, 255, 150), max(1.2, scale*.9), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            recent = QPainterPath(self.cell_point(trail[-min(len(trail), 60)], view))
            for cell in trail[-60:]:
                recent.lineTo(self.cell_point(cell, view))
            painter.setPen(QPen(QColor(120, 200, 255, 240), max(1.6, scale*1.2), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(recent)
        route = self.route.get('route') or []
        if len(route) > 1:
            path = QPainterPath(self.cell_point(route[0], view))
            for cell in route[1:]:
                path.lineTo(self.cell_point(cell, view))
            painter.setPen(QPen(QColor(255, 215, 60, 230), max(1.2, scale*.8), Qt.DashLine))
            painter.drawPath(path)
        goal = self.route.get('goal')
        if goal:
            painter.setPen(QPen(QColor(255, 215, 60), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(self.cell_point(goal, view), dot+3, dot+3)

    def draw_characters(self, painter, view):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(200, 200, 200))
        for monster in self.state.get('recent_entities', []):
            painter.drawEllipse(self.cell_point(monster.get('effective_position') or monster['position'], view), 2.2, 2.2)
        for portal in self.state.get('portals', []):
            # Warp and the area the bot never walks into.
            point = self.cell_point(portal['position'], view)
            corner = self.cell_point([portal['position'][0]+portal['margin']+.5, portal['position'][1]+portal['margin']+.5], view)
            half = QPointF(abs(corner.x()-point.x()), abs(corner.y()-point.y()))
            painter.setPen(QPen(QColor(190, 90, 255, 200), 1, Qt.DashLine))
            painter.setBrush(QColor(190, 90, 255, 45))
            painter.drawRect(QRectF(point-half, point+half))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(200, 110, 255))
            painter.drawEllipse(point, 3.5, 3.5)
        presence = self.state.get('presence') or {}
        disguised = set(presence.get('disguised', []))
        captured = (self.state.get('captured_player') or {}).get('entity_id')
        for player in self.state.get('players_nearby', []):
            if player.get('position') is None:
                continue
            point = self.cell_point(player['position'], view)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 140, 0) if player['entity_id'] in disguised else QColor(255, 220, 60))
            painter.drawEllipse(point, 3.5, 3.5)
            if player['entity_id'] == captured:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(230, 60, 230), 2))
                painter.drawEllipse(point, 7, 7)
        for hidden in presence.get('shadow_details', presence.get('hidden_details', [])):
            if hidden.get('position') is None:
                continue
            point = self.cell_point(hidden['position'], view)
            painter.setPen(QPen(QColor(255, 50, 50), 2))
            painter.setBrush(QColor(255, 50, 50, 90))
            painter.drawEllipse(point, 5, 5)
            painter.drawText(point+QPointF(7, -5), ('invisivel' if hidden.get('invisible_signal') else '?' if hidden.get('possible_hidden') else '@hide' if hidden.get('gm_invisible') else 'hide')+' '+(hidden.get('name') or str(hidden['entity_id']))+' (ultimo registro)')
        own = self.state.get('player_position')
        if own is not None:
            point = self.cell_point(own, view)
            painter.setPen(QPen(QColor(0, 0, 0), 1.5))
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(point, 4, 4)

    def draw_footer(self, painter, same_map):
        coverage = (self.route.get('coverage') or {}) if same_map else {}
        total = len(coverage.get('waypoints') or {})
        done = len(coverage.get('done') or [])
        top = HEADER+self.side+2
        painter.setPen(QColor(220, 220, 220))
        text = (f"Ciclo {coverage.get('cycle', 1)}: {done}/{total} pontos ({round(100*done/total)}%)" if total
                else 'Patrulha ainda não iniciada neste mapa')
        painter.drawText(QRectF(8, top, self.side-16, 15), Qt.AlignLeft, text)
        painter.setPen(QColor(170, 175, 185))
        painter.drawText(QRectF(8, top+15, self.side-16, 15), Qt.AlignLeft,
                         'verde falta • azul feito • amarelo rota • vermelho hide')
