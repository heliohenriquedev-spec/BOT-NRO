"""Optional local integration: updated client files pass both graphics gates without game writes."""
import pytest

from nrobot import game_folder, rcx_client
from nrobot.titan_zoom import ZoomWriter


@pytest.mark.parametrize('name', ['NRO_1Barra.exe', 'NRO_3Barras.exe'])
def test_installed_updated_client_passes_rcx_and_titan_verification(name, monkeypatch):
    folder = game_folder.saved()
    if folder is None or not (folder/name).is_file():
        pytest.skip('updated local game client unavailable')
    exe = folder/name
    closed = []

    class Memory:
        def __init__(self, pid): pass
        def executable(self): return exe
        def u32(self, address): return 0  # loading: RCX must reach the map check
        def close(self): closed.append(True)

    monkeypatch.setattr(rcx_client, 'Reader', Memory)
    with pytest.raises(ValueError, match='Entre no personagem'):
        rcx_client.inspect(123)
    assert closed == [True]
    writer = ZoomWriter(memory_for=Memory, pid_finder=lambda: 123)
    try:
        writer.attach()
        assert writer.memory is not None
    finally:
        writer.detach()
    assert closed == [True, True]
