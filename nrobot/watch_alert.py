"""Alert across the screen, above every window: someone from the lista de observação or a
character in @hide was found and the bot stopped.

It never takes the keyboard focus from the game and stays until it is clicked.
"""
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class WatchAlert(QWidget):
    def __init__(self):
        super().__init__(None)
        self.lines = []
        self.title = ''
        self.beeps = 0
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.beep_timer = QTimer(self)
        self.beep_timer.timeout.connect(self.beep)
        self.raise_timer = QTimer(self)  # games in front keep being covered while it shows
        self.raise_timer.timeout.connect(self.raise_)

    def show_alert(self, detections, stopped=None):
        self.title = ('⚠ BOT PARADO ATÉ VOCÊ INICIAR NOVAMENTE' if stopped else
                      '⚠ LISTA DE OBSERVAÇÃO: JOGADOR IDENTIFICADO')
        self.lines = []
        for found in detections[:4]:
            name = found['name'] or 'nome não recebido'
            tag = ('LISTA DE OBSERVAÇÃO' if found.get('watched', True) else 'GM' if found.get('kind') == 'gm' else '@HIDE')
            line = f"[{tag}] {name} (ID {found['entity_id']}) — {found['text']}"
            details = [d for d in (found.get('detail'), f"célula {found['position']}" if found.get('position') else None) if d]
            self.lines.append((line, ' • '.join(details)))
        screen = QGuiApplication.primaryScreen().availableGeometry()
        height = 70+len(self.lines)*58
        self.setGeometry(screen.x()+screen.width()//8, screen.y()+40, screen.width()*3//4, height)
        self.show()
        self.raise_()
        self.beeps = 0
        self.beep()
        self.beep_timer.start(700)
        self.raise_timer.start(500)
        self.update()

    def beep(self):
        self.beeps += 1
        QApplication.beep()
        if self.beeps >= 4:
            self.beep_timer.stop()

    def hideEvent(self, event):
        self.raise_timer.stop()
        self.beep_timer.stop()
        super().hideEvent(event)

    def close_rect(self):
        return QRectF(self.width()-46, 12, 30, 30)

    def mousePressEvent(self, event):
        self.hide()  # anywhere closes it, the X included

    def keyPressEvent(self, event):
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor(255, 230, 230), 3))
        painter.setBrush(QColor(170, 15, 25, 235))
        painter.drawRoundedRect(box, 14, 14)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont('Segoe UI', 17, QFont.Bold))
        painter.drawText(QRectF(box.x()+20, box.y()+10, box.width()-40, 40), Qt.AlignLeft | Qt.AlignVCenter,
                         self.title)
        painter.setPen(QPen(QColor(255, 255, 255), 3))
        x = self.close_rect()
        painter.drawLine(x.topLeft()+QPointF(6, 6), x.bottomRight()-QPointF(6, 6))
        painter.drawLine(x.topRight()+QPointF(-6, 6), x.bottomLeft()+QPointF(6, -6))
        y = box.y()+56
        for line, detail in self.lines:
            painter.setFont(QFont('Segoe UI', 14, QFont.DemiBold))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(box.x()+20, y, box.width()-40, 30), Qt.AlignLeft | Qt.AlignVCenter, line)
            painter.setFont(QFont('Segoe UI', 10))
            painter.setPen(QColor(255, 215, 215))
            painter.drawText(QRectF(box.x()+20, y+28, box.width()-40, 22), Qt.AlignLeft | Qt.AlignVCenter,
                             detail+('   (clique para fechar)' if line == self.lines[-1][0] else ''))
            y += 58
