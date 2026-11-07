import struct
import time

from nrobot import rcx_settings
from nrobot.immediate_monster_removal import ImmediateMonsterRemoval
from test_bg_entry import relay

ME, FOE = 2003137, 2002335


def unit(source, unit_type, unit_id=500):
    return struct.pack('<HIIHHBB', 0x11f, unit_id, source, 10, 10, unit_type, 1)


def ground_skill(skill, source):
    return struct.pack('<HHIHHHI', 0x117, skill, source, 1, 10, 10, 0)


def test_style_asks_and_rcx_must_draw_it():
    config = rcx_settings.validate({'effects': {'131': dict(hide_native=True, show_enemies=True)}})
    assert rcx_settings.hides_native(config, 131, None, FOE, {'own_id': ME, 'allied_ids': []})
    assert rcx_settings.hides_native(config, None, 70, FOE, {'own_id': ME, 'allied_ids': []})  # Sanctuary's animation
    off = rcx_settings.validate({'effects': {'131': dict(hide_native=True)}})
    assert not rcx_settings.hides_native(off, 131, None, FOE, {})  # RCX would not draw it: the game keeps it
    no_enemies = rcx_settings.validate({'effects': {'131': dict(hide_native=True, show_allies=True)}})
    assert not rcx_settings.hides_native(no_enemies, 131, None, FOE, {'own_id': ME, 'allied_ids': []})
    assert not rcx_settings.hides_native(rcx_settings.validate({'effects': {'131': dict(show_enemies=True)}}), 131, None, FOE, {})  # box unchecked
    # A skill style saved without the field follows its general effect; an explicit one wins.
    general = rcx_settings.validate({'effects': {'134': dict(hide_native=True, show_enemies=True)}, 'skill_styles': {'89': dict(fill='#123456')}})
    assert rcx_settings.hides_native(general, 134, 89, FOE, {})
    own = rcx_settings.validate({'effects': {'134': dict(hide_native=True, show_enemies=True)}, 'skill_styles': {'89': dict(hide_native=False)}})
    assert not rcx_settings.hides_native(own, 134, 89, FOE, {}) and rcx_settings.hides_native(own, 134, 83, FOE, {})


def test_dropped_packets_never_reach_the_client_and_others_pass():
    removal = ImmediateMonsterRemoval(None, lambda i: False, drop=lambda p: bytes(p[:2]) == b'\x1f\x01')
    other = struct.pack('<HI', 0x120, 500)
    assert removal.feed(unit(FOE, 131)+other) == other


def test_relay_hides_only_while_rcx_draws(tmp_path):
    r = relay(tmp_path)
    r.tracker.observer.player_id = ME
    r.rcx_native_config = (None, None)
    from nrobot import rcx_settings as settings
    config = settings.validate({'effects': {'131': dict(hide_native=True, show_allies=True), '146': dict(show_allies=True)}})  # no PvP: FOE counts as allied
    r.rcx_drawing = lambda now: (True, config)
    assert r.hide_native_effect(bytearray(unit(FOE, 131)))
    assert r.hide_native_effect(bytearray(ground_skill(70, FOE)))
    assert not r.hide_native_effect(bytearray(unit(FOE, 146)))  # Venom Dust was not asked
    r.rcx_drawing = lambda now: (False, None)
    assert not r.hide_native_effect(bytearray(unit(FOE, 131)))  # RCX off: the game draws it


def test_heartbeat_file_tells_the_relay_rcx_is_drawing(tmp_path):
    r = relay(tmp_path)
    assert r.rcx_drawing(time.monotonic())[0] is False
    (tmp_path/'rcx_ativo').touch()
    r.rcx_native_cache = None
    assert r.rcx_drawing(time.monotonic())[0] is True


def test_removal_only_on_the_side_rcx_acts():
    # Enemies checked, allies not: an ally's Sanctuary keeps the GRF effect, an enemy's loses it.
    config = rcx_settings.validate({'skill_styles': {'70': dict(show_enemies=True, hide_native=True)}})
    ally = {'own_id': ME, 'allied_ids': [MATE]}
    assert not rcx_settings.hides_native(config, 131, None, MATE, ally)
    assert rcx_settings.hides_native(config, 131, None, FOE, ally)
    assert not rcx_settings.hides_native(config, 131, None, ME, ally)  # own skills are allied


MATE = 2002312


def test_fire_pillar_draws_its_3x3_around_the_received_cell():
    from test_rcx_customization import renderer
    from nrobot.ground_cells import OWN_UNIT_SKILLS
    assert 80 not in OWN_UNIT_SKILLS  # never widened by the cast announcement, like traps
    state = {'ground_cells': {'map': 'test', 'own_id': ME, 'allied_ids': [],
                              'effects': [dict(position=[50, 50], effect_type=135, source_id=FOE)]}}
    r = renderer(state, {'skill_styles': {'80': dict(show_enemies=True)}}, sides=False)
    assert r.shared.count == 9
    assert {(r.shared.cells[i].x, r.shared.cells[i].y) for i in range(9)} == {(x, y) for x in (49, 50, 51) for y in (49, 50, 51)}
    r.close()


def test_closed_game_stops_the_heartbeat_and_the_panel_waits_for_the_new_one(tmp_path):
    import os
    from nrobot.rcx_renderer import RcxRenderer, Shared
    r = RcxRenderer(); r.shared = Shared(); r.enabled = True; r.shared.attached = 1
    r.update({'ground_cells': {'feed_ipc': str(tmp_path/'rcx_terreno.ipc')}})
    r.game_pid = os.getpid()
    r.feed()
    assert (tmp_path/'rcx_ativo').exists()  # game running: the relay may hide effects
    r.game_pid, r.alive_checked_until = 0x7ffffff0, 0  # no such process: the game was closed
    r.feed()
    assert not (tmp_path/'rcx_ativo').exists()
    r.shared = None

    from PySide6.QtWidgets import QApplication
    from nrobot.rcx_panel import RcxPanel
    app = QApplication.instance() or QApplication([])
    panel = RcxPanel()
    starts = []
    class Fake:
        enabled, state = True, {}
        def game_alive(self): return False
        def close(self): self.enabled = False
        def configure(self, value): pass
        def start(self):
            starts.append(1)
            if len(starts) == 1: raise ValueError('Abra o NRO')
            self.enabled = True
        def snapshot(self): return {}
    panel.renderer = Fake()
    assert panel.follow_game() and 'volta sozinho' in panel.status.text()
    panel.renderer.game_alive = lambda: True
    assert panel.follow_game() and 'reconectando' in panel.status.text() and not panel.waiting_game
    assert not panel.follow_game()  # attached to the running game again
    panel.renderer = RcxRenderer(); panel.close()
