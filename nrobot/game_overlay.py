"""REDE-73/76: shadow on the own character while it is hidden (hide, cloak or @hide).

The game camera always keeps the character at the centre of the game view, so the shadow
needs no calibration. Other hidden characters have last-received-cell markers on the
minimap and a labelled on-screen list, without guessing camera projection. The layer never
receives input: clicks always reach the game.

The own shadow is the character's real body + hair sprite from the game files (class, sex
and hairstyle received on login), facing the walking direction and animated with the walk
frames while the server path runs; until it loads, a generic figure stands in.
"""
import threading
import time

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .radar_overlay import game_client_rect


class GameOverlay(QWidget):
    BODY = .085  # character height relative to the game view height at the default zoom

    def __init__(self):
        super().__init__(None)
        self.state = {}
        self.sprite_key = self.sprite = None
        self.direction = 0  # last walking direction, kept while standing
        self.images = {}
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)

    def follow_game(self):
        rect = game_client_rect()
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1.0
        if rect is None:
            return False
        x, y, width, height = (value/ratio for value in rect)
        self.setGeometry(int(x), int(y), int(width), int(height))
        return True

    def update_state(self, state):
        self.state = state or {}
        self.update()

    def label(self):
        hidden = self.state.get('own_hidden')
        if not hidden:
            return None
        return 'você ('+('@hide' if hidden.get('gm_invisible') else 'escondido')+')'

    def other_hidden(self):
        presence = self.state.get('presence', {})
        # A hider whose cell never arrived is still listed, without a minimap marker.
        return presence.get('shadow_details', presence.get('hidden_details', []))

    def has_content(self):
        return bool(self.label() or self.other_hidden())

    def paintEvent(self, event):
        if not self.has_content():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(QFont('Segoe UI', 9, QFont.DemiBold))
        label = self.label()
        if label:
            feet = QPointF(self.width()/2, self.height()/2)
            if not self.draw_sprite(painter, feet, label):
                self.draw_shadow(painter, feet, label)
        # Camera rotation/zoom are unknown: do not invent a body position on the floor.
        # The minimap marks the last received cell; this panel makes other actors visible too.
        hidden = self.other_hidden()
        if hidden:
            painter.fillRect(QRectF(12,65,440,28+22*min(len(hidden),8)), QColor(15,15,20,185))
            painter.setPen(QColor(255,195,80))
            painter.drawText(QPointF(22,85), 'Ultimos registros de jogadores ocultos/fora de visao')
            for i, entry in enumerate(hidden[:8]):
                name = entry.get('name') or str(entry['entity_id'])
                tag = (f"INVISIVEL ao lado ({entry['invisible_signal']})" if entry.get('invisible_signal') else
                       'sumiu; @hide nao confirmado' if entry.get('possible_hidden') else '@hide' if entry.get('gm_invisible') else 'hide')
                suffix = ' [permitido]' if entry.get('allowed') else ''
                where = f"em {entry['position']}" if entry.get('position') is not None else 'posicao desconhecida'
                painter.drawText(QPointF(22,107+22*i), f"{name}: {tag} {where}{suffix}")

    def draw_shadow(self, painter, feet, label):
        height = self.height()*self.BODY
        width = height*.4
        painter.setPen(QPen(QColor(255, 60, 60, 200), 1.5, Qt.DashLine))
        painter.setBrush(QColor(255, 60, 60, 40))
        painter.drawEllipse(feet, width*.8, width*.35)
        body = QPainterPath()
        body.addEllipse(QPointF(feet.x(), feet.y()-height*.82), width*.3, width*.3)  # head
        body.addRoundedRect(QRectF(feet.x()-width/2, feet.y()-height*.66, width, height*.66), width*.35, width*.35)
        painter.setPen(QPen(QColor(255, 70, 70, 220), 1.5))
        painter.setBrush(QColor(20, 20, 30, 120))
        painter.drawPath(body)
        painter.setPen(QColor(255, 80, 80))
        painter.drawText(QPointF(feet.x()-width*1.5, feet.y()-height-6), label)

    def load_sprite(self, look):
        """Read the sprite files in the background: the game index takes a moment to open."""
        key = (look.get('job'), look.get('sex'), look.get('hair'))
        if key == self.sprite_key or None in key[:2]:
            return
        self.sprite_key, self.sprite, self.images = key, None, {}

        def work():
            try:
                from .character_sprite import CharacterSprite
                from .game_folder import saved
                from .grf import GrfSet
                folder = saved()
                sprite = CharacterSprite.load(GrfSet(str(folder)), *key) if folder else None
            except Exception as error:  # a missing/damaged game file keeps the generic figure
                print(f'Sombra: sprite do personagem indisponivel ({error})')
                sprite = None
            if self.sprite_key == key:
                self.sprite = sprite
        threading.Thread(target=work, daemon=True).start()

    def draw_sprite(self, painter, feet, label):
        from .character_sprite import IDLE, walk_state
        self.load_sprite(self.state.get('own_look') or {})
        sprite = self.sprite
        if sprite is None:
            return False
        action, direction, elapsed = walk_state(self.state.get('own_motion'), time.monotonic())
        if direction is not None:
            self.direction = direction
        count = sprite.frame_count(action, self.direction)
        speed = ((self.state.get('own_motion') or {}).get('speed_ms') or 150)/150
        frame = 0 if action == IDLE or not count else int(elapsed/(sprite.delay(action, self.direction)*speed)) % count
        key = (action, self.direction, frame)
        if key not in self.images:
            shadow = sprite.shadow(*key)
            self.images[key] = None if shadow is None else (
                QImage(shadow[0].tobytes(), shadow[0].shape[1], shadow[0].shape[0], QImage.Format_RGBA8888).copy(),
                shadow[1], shadow[2])
        if self.images[key] is None:
            return False
        image, x, y = self.images[key]
        reference = sprite.shadow(IDLE, 0, 0)
        scale = self.height()*self.BODY*1.15/max(1, reference[0].shape[0]) if reference else 1.0
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.translate(feet)
        painter.scale(scale, scale)
        painter.drawImage(QPointF(-x, -y), image)
        painter.restore()
        painter.setPen(QColor(255, 80, 80))
        painter.drawText(QPointF(feet.x()-40, feet.y()-y*scale-6), label)
        return True
