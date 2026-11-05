import ctypes as C
import hashlib
from pathlib import Path
import time

import pytest

from nrobot.rcx_renderer import RcxRenderer, Shared, manifest
from nrobot.rcx_client import map_key


def test_ipc_matches_native_struct_and_packaged_dll_is_verified():
    assert C.sizeof(Shared) == 72820  # _Static_assert in rcx.c
    record, dll = manifest()
    assert record['architecture'] == 'x86' and dll.read_bytes()[:2] == b'MZ'
    assert record['entry'] == 'Run@16'
    source = Path(__file__).resolve().parents[1]/'nrobot/native/rcx.c'
    assert record['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_only_received_cells_are_sent_and_stale_session_clears_them():
    renderer = RcxRenderer()
    renderer.shared = Shared()  # ordinary local buffer; no renderer/game connection in tests
    renderer.enabled = True
    renderer.update({'ground_cells': {'map': 'kakashi.gat', 'cells': [[10, 20], [10, 20], [-1, 10], [11, 20]]}})
    renderer.feed()
    assert renderer.shared.count == 2 and renderer.shared.map_name == b'kakashi'
    assert renderer.shared.sequence % 2 == 0
    renderer.state_at = time.monotonic()-3
    renderer.feed()
    assert renderer.shared.count == 0 and renderer.shared.map_name == b''
    renderer.stop()
    assert renderer.shared.enabled == 0


def test_map_names_are_normalized_without_guessing_camera_coordinates():
    assert map_key('KAKASHI.gat') == 'kakashi'
    assert map_key('data\\kakashi.rsw') == 'kakashi'


def test_unknown_client_is_refused_before_reading_rendering_objects(monkeypatch, tmp_path):
    from nrobot import rcx_client
    exe = tmp_path/'NRO.exe'
    exe.write_bytes(b'unknown executable')
    class Unknown:
        def __init__(self, pid): pass
        def executable(self): return exe
        def close(self): pass
        def u32(self, address): raise AssertionError('must not inspect unknown layout')
    monkeypatch.setattr(rcx_client, 'Reader', Unknown)
    with pytest.raises(ValueError, match='validados'):
        rcx_client.inspect(123)


def test_ground_packet_feed_reaches_rcx_without_general_state_refresh(tmp_path, monkeypatch):
    import json
    from PySide6.QtWidgets import QApplication
    from nrobot.rcx_panel import RcxPanel
    app = QApplication.instance() or QApplication([])
    path = tmp_path/'rcx_terreno.json'
    path.write_text(json.dumps({'map': 'field', 'cells': []}), encoding='utf-8')
    panel = RcxPanel()
    panel.update_state({'ground_cells': {'feed_file': str(path), 'cells': []}})
    monkeypatch.setattr(panel.renderer, 'snapshot', lambda: {'attached': True, 'frames': 1, 'drawn': 1, 'error': 0})
    path.write_text(json.dumps({'map': 'field', 'cells': [[10, 11]]}), encoding='utf-8')
    panel.feed_stamp = None
    panel.refresh_renderer()
    assert panel.renderer.state['ground_cells']['cells'] == [[10, 11]]
    path.write_text(json.dumps({'map': 'field', 'cells': []}), encoding='utf-8')
    panel.feed_stamp = None
    panel.refresh_renderer()
    assert panel.renderer.state['ground_cells']['cells'] == []
    panel.close()
