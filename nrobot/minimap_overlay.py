"""REDE-76: minimap over the corner of the game: ground, walked route, patrol plan, characters.

Reads the files the relay writes in the session folder: minimapa_chao.json (walkable ground,
once per map) and minimapa_rota.json (walked trail, patrol waypoints done/remaining, current
goal and route). North is up, like the game's own map. The window never takes focus from the
game: "+" / "-" resize it, the mouse wheel zooms around the character, dragging moves it.

Pinned (the default): exactly over the game's own minimap, which this client always draws in the
top-right corner of its window, 128 pixels times the minimap zoom it keeps in the registry
(UIRectInfo m_minimapZoomWnd). Only the map square is drawn there, with the character's
coordinates on a strip right below it; a small button unpins it.

NPCs (cyan), monsters found by @showmobs (pink crosses) and portals (purple) show their name or
destination map when the mouse rests on them.
"""
import base64
import json
import zlib

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .radar_overlay import game_client_rect

HEADER = 22
FOOTER = 50
COORDS = 16  # strip under the pinned minimap with the character's coordinates
HOVER = 7  # pixels from a marker that show its name
GAME_MINIMAP = 128  # pixels of the client's minimap at zoom 1
UI_KEY = r'Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\Gravity Soft\Ragnarok\UIRectInfo'


def game_minimap_zoom():
    """The client's minimap window zoom (a float stored as its bits), 1.0 when unknown."""
    try:
        import struct
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UI_KEY) as key:
            raw, _ = winreg.QueryValueEx(key, 'm_minimapZoomWnd')
        zoom = struct.unpack('<f', struct.pack('<I', int(raw) & 0xffffffff))[0]
        return zoom if .5 <= zoom <= 4 else 1.0
    except (OSError, ValueError, ImportError):
        return 1.0


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
        self.pinned = True  # over the game's own minimap, same size and place
        self.pinned_side = GAME_MINIMAP
        self.pin_offset = (0, 0)  # fine adjustment from the game's top-right corner (left, down)
        self.pin_side_adjust = 0  # pixels added to the game-minimap size, set with +/- when pinned
        self.drag = None
        self.on_change = lambda: None  # size, zoom or position changed: the panel saves them
        self.on_hover = lambda inside: None  # cursor over the window: the game's clicks are not sent
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setMouseTracking(True)  # names of NPCs, portals and @showmobs marks under the cursor
        self.apply_size()

    # -- data -------------------------------------------------------------------------
    @property
    def side(self):
        return self.pinned_side if self.pinned else self.SIDES[self.side_index]

    @property
    def header(self):
        return 0 if self.pinned else HEADER

    def apply_size(self):
        if self.pinned:
            screen = QGuiApplication.primaryScreen()
            ratio = screen.devicePixelRatio() if screen else 1
            self.pinned_side = max(32, round(GAME_MINIMAP*game_minimap_zoom()/ratio)+self.pin_side_adjust)
            self.resize(self.side, self.side+COORDS)
        else:
            self.resize(self.side, self.side+HEADER+FOOTER)
        self.update()

    def set_pinned(self, pinned):
        self.pinned = bool(pinned)
        if self.pinned:
            self.zoom_index = 0  # the whole map, like the game's
        self.apply_size()
        self.follow_game()
        self.on_change()

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
        if self.drag is not None:
            return True  # being dragged: the mouse decides where it goes
        rect = game_client_rect()
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1
        if rect is None:
            return False
        x, y, width, height = (value/ratio for value in rect)
        if self.pinned:
            # The game's minimap corner, plus the fine adjustment the user dragged once.
            target = (x+width-self.width()-self.pin_offset[0], y+self.pin_offset[1])
        elif self.offset is None:
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
        return QPointF((cell[0]+.5-x0)*scale, self.header+(top-cell[1]-.5)*scale)

    def map_rect(self):
        return QRectF(0, self.header, self.side, self.side)

    def buttons(self):
        if self.pinned:  # unpin, and nudge the size to match the game's minimap exactly
            return {'solta': QRectF(2, 2, 14, 14), '+': QRectF(self.side-40, 2, 16, 14),
                    '-': QRectF(self.side-20, 2, 16, 14)}
        return {'fixar': QRectF(self.side-84, 2, 36, 18), '+': QRectF(self.side-44, 2, 18, 18),
                '-': QRectF(self.side-22, 2, 18, 18)}

    # -- input --------------------------------------------------------------------------
    def mousePressEvent(self, event):
        point = event.position()
        for label, rect in self.buttons().items():
            if rect.contains(point):
                if label in ('solta', 'fixar'):
                    self.set_pinned(label == 'fixar')
                    return
                step = 1 if label == '+' else -1
                if self.pinned:
                    self.pin_side_adjust = max(-GAME_MINIMAP+32, min(400, self.pin_side_adjust+step*4))
                else:
                    self.side_index = max(0, min(len(self.SIDES)-1, self.side_index+step))
                self.apply_size()
                self.follow_game()
                self.on_change()
                return
        self.drag = event.globalPosition()-QPointF(self.x(), self.y())  # drag to align/move it

    def enterEvent(self, event):
        self.on_hover(True)

    def leaveEvent(self, event):
        QToolTip.hideText()
        if self.drag is None:
            self.on_hover(False)

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            target = event.globalPosition()-self.drag
            self.move(int(target.x()), int(target.y()))
            return
        text = self.hover_text(event.position())
        if text:
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()

    def hover_items(self):
        """[(cell, text)] of the markers that have a name to show."""
        items = []
        for npc in self.state.get('npcs') or []:
            items.append((npc['position'], 'NPC: '+(npc.get('name') or 'sem nome ainda (passe o mouse nele no jogo)')))
        for portal in self.state.get('portals') or []:
            items.append((portal['position'], 'Portal → '+portal['to'] if portal.get('to') else 'Portal (destino ainda não registrado)'))
        for mark in self.state.get('viewpoint_marks') or []:
            items.append((mark['position'], '@showmobs: '+(mark.get('name') or 'monstro')))
        return items

    def hover_text(self, point):
        view = self.view()
        if view is None or not self.map_rect().contains(point):
            return None
        best = None
        for cell, text in self.hover_items():
            spot = self.cell_point(cell, view)
            distance = max(abs(spot.x()-point.x()), abs(spot.y()-point.y()))
            if distance <= HOVER and (best is None or distance < best[0]):
                best = (distance, text)
        return best[1] if best else None

    def mouseReleaseEvent(self, event):
        if self.drag is None:
            return
        self.drag = None
        if not self.underMouse():
            self.on_hover(False)
        rect = game_client_rect()
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1
        if rect is not None:
            x, y, width, height = (value/ratio for value in rect)
            if self.pinned:  # keep the drag as an offset from the game's top-right corner
                self.pin_offset = (round(x+width-self.width()-self.x()), round(self.y()-y))
            else:
                self.offset = (self.x()-x, self.y()-y)
            self.on_change()

    def wheelEvent(self, event):
        if self.pinned:
            return  # the whole map, like the game's minimap under it
        step = 1 if event.angleDelta().y() > 0 else -1
        self.zoom_index = max(0, min(len(self.ZOOMS)-1, self.zoom_index+step))
        self.update()
        self.on_change()

    def layout_state(self):
        return {'side_index': self.side_index, 'zoom_index': self.zoom_index, 'pinned': self.pinned,
                'offset': list(self.offset) if self.offset is not None else None,
                'pin_offset': list(self.pin_offset), 'pin_side_adjust': self.pin_side_adjust}

    def restore_layout(self, state):
        state = state or {}
        self.side_index = max(0, min(len(self.SIDES)-1, int(state.get('side_index', self.side_index))))
        self.zoom_index = max(0, min(len(self.ZOOMS)-1, int(state.get('zoom_index', self.zoom_index))))
        offset = state.get('offset')
        self.offset = tuple(offset) if offset else None
        pin_offset = state.get('pin_offset')
        self.pin_offset = tuple(pin_offset) if pin_offset else (0, 0)
        self.pin_side_adjust = int(state.get('pin_side_adjust', 0))
        self.pinned = bool(state.get('pinned', True))
        if self.pinned:
            self.zoom_index = 0
        self.apply_size()

    # -- drawing ------------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QPen(QColor(110, 120, 135), 1.5))
        painter.setBrush(QColor(12, 14, 20, 210))
        if self.pinned:
            painter.drawRect(QRectF(.5, .5, self.width()-1, self.height()-1))
        else:
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
        if self.pinned:
            self.draw_pin(painter)
            self.draw_coordinates(painter, QRectF(4, self.side, self.side-8, COORDS))
        else:
            self.draw_footer(painter, same_map)

    def draw_header(self, painter):
        painter.setPen(QColor(225, 225, 225))
        name = (self.ground or {}).get('map') or self.state.get('map_name') or 'minimapa'
        zoom = self.ZOOMS[self.zoom_index]
        painter.drawText(QRectF(8, 2, self.side-96, 18), Qt.AlignLeft | Qt.AlignVCenter,
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
        for npc in self.state.get('npcs') or []:
            point = self.cell_point(npc['position'], view)
            painter.setPen(QPen(QColor(10, 40, 50), 1))
            painter.setBrush(QColor(60, 220, 240))
            diamond = QPainterPath()
            diamond.moveTo(point+QPointF(0, -3.5)); diamond.lineTo(point+QPointF(3.5, 0))
            diamond.lineTo(point+QPointF(0, 3.5)); diamond.lineTo(point+QPointF(-3.5, 0)); diamond.closeSubpath()
            painter.drawPath(diamond)
        painter.setPen(QPen(QColor(255, 90, 170), 1.8))
        for mark in self.state.get('viewpoint_marks') or []:
            point = self.cell_point(mark['position'], view)
            painter.drawLine(point+QPointF(-3, -3), point+QPointF(3, 3))
            painter.drawLine(point+QPointF(-3, 3), point+QPointF(3, -3))
        painter.setPen(Qt.NoPen)
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
            painter.drawEllipse(point, 5, 5)  # marker only: no text over the minimap
        own = self.state.get('player_position')
        if own is not None:
            point = self.cell_point(own, view)
            painter.setPen(QPen(QColor(0, 0, 0), 1.5))
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(point, 4, 4)

    def draw_pin(self, painter):
        for label, rect in self.buttons().items():
            painter.setPen(QPen(QColor(150, 160, 175), 1))
            painter.setBrush(QColor(40, 46, 58, 200))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(rect, Qt.AlignCenter, '↗' if label == 'solta' else label)

    def coordinates_text(self):
        own = self.state.get('player_position')
        name = (self.state.get('map_name') or (self.ground or {}).get('map') or '').replace('.gat', '')
        if own is None:
            return name or 'posição desconhecida'
        return f"{name}  ({own[0]}, {own[1]})" if name else f"({own[0]}, {own[1]})"

    def draw_coordinates(self, painter, rect):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(12, 14, 20, 210))
        painter.drawRect(QRectF(0, rect.top(), self.width(), rect.height()))
        painter.setPen(QColor(235, 235, 235))
        painter.drawText(rect, Qt.AlignCenter, self.coordinates_text())

    def draw_footer(self, painter, same_map):
        coverage = (self.route.get('coverage') or {}) if same_map else {}
        total = len(coverage.get('waypoints') or {})
        done = len(coverage.get('done') or [])
        self.draw_coordinates(painter, QRectF(8, self.header+self.side+1, self.side-16, 15))
        top = self.header+self.side+17
        painter.setPen(QColor(220, 220, 220))
        text = (f"Ciclo {coverage.get('cycle', 1)}: {done}/{total} pontos ({round(100*done/total)}%)" if total
                else 'Patrulha ainda não iniciada neste mapa')
        painter.drawText(QRectF(8, top, self.side-16, 15), Qt.AlignLeft, text)
        painter.setPen(QColor(170, 175, 185))
        painter.drawText(QRectF(8, top+15, self.side-16, 15), Qt.AlignLeft,
                         'verde falta • azul feito • amarelo rota • ciano NPC • rosa @showmobs')
