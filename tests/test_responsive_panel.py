"""Layout changes must preserve configuration and access to controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QFormLayout
from nrobot.packet_panel import PacketPanel


@pytest.fixture
def panel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = PacketPanel()
    monkeypatch.setattr(panel.update_panel, 'run', lambda *args: None)
    monkeypatch.setattr(panel, 'save_ui', lambda: None)
    panel.show()
    yield panel, app
    panel.save_timer.stop()
    panel.close()


def test_resize_preserves_settings_and_accessible_pages(panel):
    p, app = panel
    before = p.settings()
    for width, height in [(1920,1080),(820,640),(1366,768),(1024,768),(1440,900)]:
        p.resize(width,height)
        for _ in range(4): app.processEvents()
        assert p.settings() == before
        layout = p.responsive_layout
        assert layout.nav.isVisible() == (width >= 1120)
        assert (layout.settings_tabs.indexOf(layout.species) >= 0) == (width < 1120)
        for index in range(p.tabs.count()):
            p.tabs.setCurrentIndex(index)
            app.processEvents()
            assert p.tabs.currentWidget().isVisible()


def test_navigation_and_form_labels_remain_available(panel):
    p, app = panel
    p.resize(1440,900)
    app.processEvents()
    layout = p.responsive_layout
    layout.nav.setCurrentRow(2)
    assert p.tabs.currentIndex() == 2
    p.tabs.setCurrentIndex(0)
    app.processEvents()
    for form in p.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            item = form.itemAt(row,QFormLayout.LabelRole)
            if item and item.widget() and item.widget().isVisible():
                assert item.widget().width() > 20
                assert item.widget().height() >= item.widget().fontMetrics().height()
