"""REDE-79/80: monstros do jogo, alvos do mapa atual e ofensivas na velocidade máxima."""
import json
import os
import struct
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from nrobot import monster_db
from nrobot.combat_rotation import CombatRotation


def profile(identity, interval=5):
    return {'skill_id': identity, 'enabled': True, 'role': 'offensive', 'level': 10, 'interval': interval, 'effect_id': 0}


def state(distance=2):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10], 'player_id': 1,
            'player_sp': 999, 'own_effects': {}, 'own_cast_until': 0,
            'learned_skills': [{'skill_id': 1001, 'level': 10, 'sp_cost': 10, 'range': 3, 'target_flags': 1},
                               {'skill_id': 1002, 'level': 10, 'sp_cost': 10, 'range': 9, 'target_flags': 1}],
            'recent_entities': [{'entity_id': 20, 'position': [10+distance, 10], 'position_age_seconds': .1}]}


def hit(skill):
    return [{'kind': 'skill_damage', 'skill_id': skill, 'source_id': 1, 'target_id': 20, 'level': 10, 'damage_raw': 1}]


def test_fast_mode_ignores_the_manual_interval_and_learns_a_shorter_wait():
    rotation = CombatRotation([profile(1001), profile(1002)], fast=True)
    now = 0
    for expected in (1001, 1002, 1001, 1002):
        action = rotation.plan(state(), now, 20)
        assert action['skill_id'] == expected  # back again long before its 5 s manual interval
        rotation.sent(action, now)
        rotation.observe(hit(expected), 1, now+.01)
        now += rotation.after_skill_delay+.02
    assert rotation.after_skill_delay < CombatRotation.AFTER_SKILL_DELAY
    slow = CombatRotation([profile(1001)], fast=False)
    slow.sent(slow.plan(state(), 0, 20), 0)
    slow.observe(hit(1001), 1, .01)
    assert slow.plan(state(), 1, 20) is None  # without fast mode the 5 s interval still applies


def test_each_skill_is_used_only_when_the_target_is_inside_its_own_range():
    rotation = CombatRotation([profile(1001), profile(1002)], fast=True, priority=[1001, 1002])
    far = rotation.plan(state(distance=6), 0, 20)
    assert far['skill_id'] == 1002  # 1001 reaches 3 cells only: skipped, not sent
    rotation.sent(far, 0)
    rotation.observe(hit(1002), 1, .01)
    near = rotation.plan(state(distance=2), 1, 20)
    assert near['skill_id'] == 1001


def test_monsters_seen_in_the_game_are_recorded_with_their_maps(tmp_path):
    captured = {}
    assert monster_db.record(captured, 21999, 'novo_mapa.gat', name='Boneco Novo', max_hp=900, walk_speed_ms=200,
                             new_entity=True)
    assert not monster_db.record(captured, 21999, 'novo_mapa.gat')  # nothing new learned
    monster_db.save_captured(captured, tmp_path/'capturados.json')
    loaded = monster_db.load_captured(tmp_path/'capturados.json')
    assert loaded[21999]['name'] == 'Boneco Novo' and loaded[21999]['maps'] == {'novo_mapa': 1}
    assert 21999 in monster_db.monsters_of_map('novo_mapa.gat', captured=loaded)
    rows = {row['species_id']: row for row in monster_db.all_monsters(loaded)}
    assert rows[21999]['origin'] == 'visto neste PC' and rows[21999]['max_hp'] == 900
    assert len(rows) > 600  # the client catalog is there too


def test_catalog_monsters_of_a_map_come_from_the_client_navi_list():
    ids = monster_db.monsters_of_map('moc_fild13.gat', captured={})
    names = [monster_db.catalog()[i]['symbol'] for i in ids]
    assert 'MAGNOLIA' in names


def test_relay_records_monsters_and_captures_a_missing_sprite_when_the_mouse_rests_on_it(tmp_path, monkeypatch):
    from nrobot import screen_capture
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(monster_db, 'SPRITES', tmp_path/'sprites')
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.tracker.observer.map_name = 'campo.gat'
    monkeypatch.setattr(relay, 'monsters_seen', {})
    appearance = {'kind': 'appearance', 'entity_id': 110000001, 'species_id': 21999, 'position': [5, 5],
                  'object_type': 5, 'walk_speed_ms': 180}
    relay.inventory.observe([appearance], time.monotonic())
    relay.learn_monsters([appearance])
    assert not relay.monsters_seen
    name = {'kind': 'name', 'entity_id': 110000001, 'name': 'Raro', 'hp': 50, 'max_hp': 50}
    relay.inventory.observe([name], time.monotonic())
    relay.learn_monsters([name])
    assert relay.monsters_seen[21999]['name'] == 'Raro' and relay.monsters_dirty
    shots = []
    monkeypatch.setattr(screen_capture, 'capture_under_cursor', lambda path: shots.append(path) or path.write_bytes(b'png') or True)
    relay.inspect_native_frames(struct.pack('<H5sI', 0x8c, bytes(5), 110000001))
    assert shots == [tmp_path/'sprites'/'21999.png'] and relay.monsters_seen[21999]['captured_sprite']
    relay.inspect_native_frames(struct.pack('<H5sI', 0x8c, bytes(5), 110000001))
    assert len(shots) == 1  # once per monster type


def test_targets_show_only_the_current_map_and_keep_other_maps_choices(monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from nrobot.monster_panel import MapTargets
    monkeypatch.setattr(monster_db, 'load_base', lambda: {})
    monkeypatch.setattr(monster_db, 'load_captured', lambda path=None: {
        1037: {'name': 'Filhote de cobra', 'maps': {'moc_fild13': 1}},
        1034: {'name': 'Girino', 'maps': {'outro_mapa': 1}},
    })
    targets = MapTargets()
    targets.selected = {9999}  # chosen on another map
    targets.show_map('moc_fild13.gat', {1836: {'name': 'Boneco de Treino', 'present': 2}})
    shown = {targets.list.item(i).data(Qt.UserRole) for i in range(targets.list.count())}
    assert shown == {1037, 1836}
    item = next(targets.list.item(i) for i in range(targets.list.count()) if targets.list.item(i).data(Qt.UserRole) == 1836)
    item.setCheckState(Qt.Checked)
    assert targets.selected == {9999, 1836}
    targets.set_all(False)
    assert targets.selected == {9999}
    targets.show_map('moc_fild13.gat')
    assert targets.list.count() == 1
    assert targets.list.item(0).data(Qt.UserRole) == 1037
    targets.close()


def test_monster_tab_lists_the_game_monsters(monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from nrobot.monster_panel import MonsterPanel
    panel = MonsterPanel()
    panel.extracted = True  # no background extraction in the test
    panel.reload()
    assert panel.model.rowCount() > 600
    panel.search.setText('magnolia')
    assert 1 <= panel.model.rowCount() < 10
    panel.close()


def test_publishing_moves_custom_monsters_to_the_shared_base(tmp_path):
    from nrobot.screen_capture import write_png
    import numpy as np
    captured = {}
    monster_db.record(captured, 21999, 'campo.gat', name='Custom', max_hp=500, new_entity=True)
    captured[21999]['captured_sprite'] = True
    monster_db.record(captured, 1138, 'moc_fild13.gat', name='Magnólia', max_hp=80)  # a recorded map should also be shared for catalog monsters
    monster_db.save_captured(captured)
    monster_db.SPRITES.mkdir(parents=True)
    write_png(monster_db.sprite_path(21999), np.zeros((4, 4, 4), dtype=np.uint8))
    assert monster_db.export_base(log=lambda text: None) == (2, 0, 1)
    base = monster_db.load_base()
    assert set(base) == {1138, 21999} and base[21999]['name'] == 'Custom' and base[21999]['maps'] == {'campo': 1}
    assert base[1138]['maps'] == {'moc_fild13': 0}
    assert (monster_db.BASE_SPRITES/'21999.png').is_file()
    # Another PC without that monster sees it through the base.
    monster_db.save_captured({})
    (monster_db.SPRITES/'21999.png').unlink()
    rows = {row['species_id']: row for row in monster_db.all_monsters()}
    assert rows[21999]['origin'] == 'base compartilhada' and rows[21999]['has_sprite']
    assert 21999 in monster_db.monsters_of_map('campo.gat')


def test_custom_monster_sprite_comes_from_the_game_data_by_its_client_identity():
    from nrobot.game_folder import find
    from nrobot.grf import GrfSet
    folder = find()
    if folder is None:
        pytest.skip('jogo não instalado')
    grfs = GrfSet(str(folder))
    custom = [i for i in monster_db.identities() if i not in monster_db.catalog()]
    readable = [i for i in custom[:400] if monster_db.sprite_from_grf(grfs, i) is not None]
    assert readable  # NRO custom monsters outside the Navi catalog still have client sprites
