"""REDE-76: capture with the game's own mouse, player names, minimap files and drawing."""
import json
import os
import struct
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from nrobot.map_navigation import CollisionMap
from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import SessionRelay


def name_request(identity):
    return struct.pack('<H5sI', 0x8c, bytes(5), identity)  # client: mouse on a character


def _relay(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt(patrol=True)
    relay.hunt.start()
    observer = relay.tracker.observer
    observer.player_id = 1
    observer.player = [10, 10]
    observer.player_at = time.monotonic()
    return relay


def _appear(relay, identity, at):
    appearance = {'kind': 'appearance', 'entity_id': identity, 'species_id': 26, 'position': [13, 10],
                  'object_type': 0, 'walk_speed_ms': 150}
    relay.presence.observe([appearance], 1, at)
    relay.track_players([appearance])
    relay.player_first_seen[identity] = at


def test_resting_the_game_mouse_on_a_character_captures_it_with_its_name(tmp_path):
    relay = _relay(tmp_path)
    _appear(relay, 2003137, time.monotonic()-5)
    relay.track_players([{'kind': 'name', 'entity_id': 2003137, 'name': 'Radiance'}])
    relay.inspect_native_frames(name_request(2003137))
    assert relay.captured_player is None  # not armed: hovering is ordinary play
    relay.capture_armed_until = time.monotonic()+20
    relay.inspect_native_frames(name_request(2003137))
    assert relay.captured_player == {'entity_id': 2003137, 'name': 'Radiance', 'origin': 'mouse no jogo'}
    assert relay.hunt.priority_target == 2003137 and relay.capture_armed_until == 0
    assert relay.players_nearby()[0]['name'] == 'Radiance'


def test_names_the_client_asks_for_characters_just_entering_the_view_do_not_capture(tmp_path):
    relay = _relay(tmp_path)
    _appear(relay, 2003140, time.monotonic())
    relay.capture_armed_until = time.monotonic()+20
    relay.inspect_native_frames(name_request(2003140))
    relay.inspect_native_frames(name_request(110830885))  # a monster
    assert relay.captured_player is None and relay.capture_armed_until > 0


def test_minimap_files_hold_ground_trail_and_patrol_plan(tmp_path):
    relay = _relay(tmp_path)
    collision = CollisionMap(60, 60, [1]*3600)
    relay.collision_map = lambda: collision
    relay.tracker.observer.map_name = 'teste.gat'
    action = relay.hunt.plan({'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10],
                              'recent_entities': []}, 0, 150, collision)
    assert action is not None
    relay.write_minimap()
    relay.tracker.observer.player = [16, 12]
    relay.last_route_written = 0
    relay.write_minimap()
    ground = json.loads((tmp_path/'minimapa_chao.json').read_text(encoding='utf-8'))
    route = json.loads((tmp_path/'minimapa_rota.json').read_text(encoding='utf-8'))
    assert (ground['map'], ground['width'], ground['height']) == ('teste.gat', 60, 60)
    assert route['trail'] == [[10, 10], [16, 12]]
    assert route['coverage']['waypoints'] and route['goal'] and route['route']


def test_minimap_draws_and_resizes(tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    relay = _relay(tmp_path)
    collision = CollisionMap(60, 60, [1]*3600)
    relay.collision_map = lambda: collision
    relay.tracker.observer.map_name = 'teste.gat'
    relay.hunt.plan({'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10],
                     'recent_entities': []}, 0, 150, collision)
    relay.write_minimap()
    from nrobot.minimap_overlay import MinimapOverlay
    minimap = MinimapOverlay()
    minimap.update_state({'map_name': 'teste.gat', 'player_position': [10, 10], 'recent_entities': [],
                          'players_nearby': [], 'presence': {'hidden_details': [{'entity_id': 2003139, 'position': [20, 20], 'gm_invisible': True}]}})
    minimap.load(tmp_path)
    assert minimap.ground['image'].width() == 60
    point = minimap.cell_point([0, 59], minimap.view())
    assert point.x() < 10 and point.y() < 30  # north-up: highest y at the top
    minimap.grab()
    from nrobot.minimap_overlay import COORDS
    assert minimap.pinned and minimap.width()+COORDS == minimap.height()  # the game's minimap square + coordinates
    assert minimap.coordinates_text() == 'teste  (10, 10)'

    class Click:
        def __init__(self, label): self.label = label
        def position(self):
            return minimap.buttons()[self.label].center()
    minimap.mousePressEvent(Click('solta'))  # unpinned: header, footer, +/- and dragging
    assert not minimap.pinned and minimap.height() > minimap.width()
    width = minimap.width()
    minimap.mousePressEvent(Click('+'))
    assert minimap.width() > width
    minimap.mousePressEvent(Click('fixar'))
    assert minimap.pinned and minimap.zoom_index == 0
    minimap.close()


def test_own_shadow_is_drawn_on_the_view_centre_without_calibration():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from nrobot.game_overlay import GameOverlay
    overlay = GameOverlay()
    overlay.resize(1280, 800)
    drawn = []
    overlay.draw_shadow = lambda painter, feet, label: drawn.append(((feet.x(), feet.y()), label))
    overlay.update_state({'own_hidden': {'option': 2, 'gm_invisible': False}})
    overlay.grab()
    assert drawn == [((640, 400), 'você (escondido)')]
    overlay.update_state({})
    drawn.clear()
    overlay.grab()
    assert drawn == []
    overlay.close()


def test_minimap_names_npcs_portals_and_showmobs_on_hover():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    from nrobot.minimap_overlay import MinimapOverlay
    app = QApplication.instance() or QApplication([])
    minimap = MinimapOverlay()
    minimap.ground = {'map': 'teste.gat', 'width': 60, 'height': 60, 'image': QImage(60, 60, QImage.Format_RGBA8888)}
    minimap.update_state({'map_name': 'teste.gat', 'player_position': [5, 5],
                          'npcs': [{'position': [10, 10], 'name': 'Médica'}],
                          'portals': [{'position': [30, 30], 'margin': 2, 'to': 'kakashi'}],
                          'viewpoint_marks': [{'position': [50, 50], 'name': 'Deca'}]})
    view = minimap.view()
    assert minimap.hover_text(minimap.cell_point([10, 10], view)) == 'NPC: Médica'
    assert minimap.hover_text(minimap.cell_point([30, 30], view)) == 'Portal → kakashi'
    assert minimap.hover_text(minimap.cell_point([50, 50], view)) == '@showmobs: Deca'
    assert minimap.hover_text(minimap.cell_point([40, 20], view)) is None
    minimap.grab()
    minimap.set_pinned(False)
    assert minimap.height() > minimap.width()
    minimap.grab()
    minimap.close()


def test_showmobs_marks_reach_the_minimap_state_and_are_removed(tmp_path):
    relay = _relay(tmp_path)
    mark = lambda kind, ident, cell: dict(kind='viewpoint', npc_id=1, mark_type=kind, mark_id=ident, position=list(cell))
    relay.observe_viewpoints([mark(1, 1, (10, 20)), mark(1, 2, (11, 21))], 100.0)
    assert sorted(m['position'] for m in relay.current_viewpoint_marks(102.0)) == [[10, 20], [11, 21]]
    relay.observe_viewpoints([mark(2, 1, (10, 20))], 101.0)
    assert [m['position'] for m in relay.current_viewpoint_marks(102.0)] == [[11, 21]]
    relay.observe_viewpoints([dict(kind='map_change', map='outro.gat', position=[1, 1])], 102.0)
    assert relay.current_viewpoint_marks(103.0) == []
    relay.observe_viewpoints([mark(1, 3, (5, 5))], 200.0)
    assert relay.current_viewpoint_marks(200.0+relay.VIEWPOINT_TTL+1) == []  # stale marks expire
