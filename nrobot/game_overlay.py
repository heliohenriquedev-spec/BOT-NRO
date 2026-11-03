"""REDE-73/76: shadow on the own character while it is hidden (hide, cloak or @hide).

The game camera always keeps the character at the centre of the game view, so the shadow
needs no calibration. Other hidden characters have last-received-cell markers on the
minimap and a labelled on-screen list, without guessing camera projection. The layer never
receives input: clicks always reach the game.
"""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .radar_overlay import game_client_rect


class GameOverlay(QWidget):
    BODY = .085  # character height relative to the game view height at the default zoom

    def __init__(self):
        super().__init__(None)
        self.state = {}
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
        return [e for e in presence.get('shadow_details', presence.get('hidden_details', [])) if e.get('position') is not None]

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
            self.draw_shadow(painter, QPointF(self.width()/2, self.height()/2), label)
        # Camera rotation/zoom are unknown: do not invent a body position on the floor.
        # The minimap marks the last received cell; this panel makes other actors visible too.
        hidden = self.other_hidden()
        if hidden:
            painter.fillRect(QRectF(12,65,440,28+22*min(len(hidden),8)), QColor(15,15,20,185))
            painter.setPen(QColor(255,195,80))
            painter.drawText(QPointF(22,85), 'Ultimos registros de jogadores ocultos/fora de visao')
            for i, entry in enumerate(hidden[:8]):
                name = entry.get('name') or str(entry['entity_id'])
                tag = 'sumiu; @hide nao confirmado' if entry.get('possible_hidden') else '@hide' if entry.get('gm_invisible') else 'hide'
                suffix = ' [permitido]' if entry.get('allowed') else ''
                painter.drawText(QPointF(22,107+22*i), f"{name}: {tag} em {entry['position']}{suffix}")

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
