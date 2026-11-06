def test_dialogs_with_a_parent_do_not_block_the_overlays():
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QWidget
    from nrobot.responsive_ui import dialogs_block_only_their_window
    app = QApplication.instance() or QApplication([])
    dialogs_block_only_their_window()
    panel = QWidget()
    panel.show()
    dialog = QDialog(panel)
    seen = []

    def check():
        seen.append(dialog.windowModality())
        dialog.accept()
    QTimer.singleShot(0, check)
    dialog.exec()
    # Window-modal: only the panel is blocked; the minimap and counter (no parent) keep the mouse.
    assert seen == [Qt.WindowModal]
    panel.close()
