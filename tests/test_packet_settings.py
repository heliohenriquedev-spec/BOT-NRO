import json
import time
import pytest

from nrobot.packet_settings import read, save, validate, DEFAULTS
from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import SessionRelay


def test_settings_persist_and_reject_invalid_values(tmp_path):
    path = tmp_path/'config.json'
    assert read(path) == DEFAULTS
    settings = save({**DEFAULTS, 'species': [1212, 1037], 'radius': 40, 'skills': False}, path)
    assert read(path) == settings
    for invalid in ({'species': [], 'auto_map_targets': False}, {'species': [9999]}, {'radius': 0}, {'radius': True},
                    {'patrol_step': 9}, {'patrol': 'true'}, {'skills': 1}):
        with pytest.raises(ValueError): validate(invalid)


def test_apply_settings_keeps_hunting_changes_filters_and_restores_only_recent_sightings(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt(patrol=True)
    relay.hunt.start()
    now = time.monotonic()
    relay.inventory.observe([{'kind': 'appearance', 'entity_id': 100, 'species_id': 1212, 'position': [1, 1]}], now)
    relay.apply_settings({**DEFAULTS, 'species': [1212], 'radius': 40, 'patrol': False, 'skills': False})
    assert relay.hunt.enabled and relay.hunt.SEARCH_RADIUS == 40  # saving never stops the bot
    assert relay.hunt.patrol is None and not relay.hunt.use_skills
    assert relay.tracker.observer.species == {1212}
    assert 100 in relay.tracker.observer.registry.entities


def test_control_acknowledgement_start_guard_and_pause(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    def request(identity, command, gate=True, **extra):
        (tmp_path/'comando.json').write_text(json.dumps({'id': identity, 'command': command, **extra}), encoding='utf-8')
        relay.process_control(lambda: gate)
        assert not (tmp_path/'comando.json').exists()
        return relay.control_result
    assert not request('1', 'start')['ok']  # no map connection
    relay.upstream = object()
    assert not request('2', 'start', gate=False)['ok']
    assert request('3', 'start')['ok'] and relay.hunt.enabled
    assert request('4', 'stop')['ok'] and relay.commands_blocked and not relay.hunt.enabled
    assert request('5', 'start')['ok'] and not relay.commands_blocked
    assert request('6', 'apply', settings={**DEFAULTS, 'species': [1051]})['ok']
    assert relay.hunt.enabled and relay.tracker.observer.species == {1051}  # applied while hunting


def test_old_config_migrates_and_new_combat_values_reach_running_planner(tmp_path):
    path = tmp_path/'old.json'
    path.write_text(json.dumps({'species': [1037], 'radius': 28, 'patrol': True, 'patrol_step': 8, 'skills': True}))
    assert read(path)['skill_interval'] == .5
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt()
    relay.hunt.start()
    config = {**DEFAULTS, 'skill_interval': .3, 'skill_timeout': 2, 'skill_attempts': 2,
              'target_defer': 4, 'switch_distance': 10, 'switch_saving': 2, 'switch_ratio_percent': 50}
    relay.apply_settings(config)
    assert relay.hunt.enabled
    assert relay.hunt.SKILL_INTERVAL == .3 and relay.hunt.SKILL_RESPONSE_TIMEOUT == 2
    assert relay.hunt.SKILL_ATTEMPTS == 2 and relay.hunt.TARGET_DEFER == 4
    assert relay.hunt.SWITCH_DISTANCE == 10 and relay.hunt.SWITCH_SAVING == 2 and relay.hunt.SWITCH_RATIO == .5
    for invalid in ({'skill_interval': float('nan')}, {'skill_timeout': float('inf')},
                    {'skill_interval': True}, {'skill_attempts': 0}, {'target_defer': 100},
                    {'switch_ratio_percent': 100}, {'skill_interval': 3, 'skill_timeout': 1}):
        with pytest.raises(ValueError): validate(invalid)


def test_apply_keeps_visible_actor_movement_when_settings_change(tmp_path):
    from nrobot.network_targets import Entity
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt()
    old = time.monotonic()-30
    relay.inventory.observe([{'kind': 'appearance', 'entity_id': 100, 'species_id': 1037,
                             'position': [1, 1], 'destination': [4, 4], 'walk_speed_ms': 200}], old)
    actor = Entity(100, 1037, 1, 1, old, 'monster', destination=(4, 4), walk_speed_ms=200)
    relay.tracker.observer.registry.update(actor)
    relay.apply_settings(DEFAULTS)
    assert relay.tracker.observer.registry.entities[100] is actor


def test_apply_keeps_patrol_coverage_and_changes_only_step_limit(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt(patrol=True)
    patrol = relay.hunt.patrol
    patrol.reached([20, 20])
    patrol.reached([28, 28], [20, 20])
    visits = dict(patrol.visits)
    relay.apply_settings({**DEFAULTS, 'patrol_step': 6})
    assert relay.hunt.patrol is patrol and dict(patrol.visits) == visits and patrol.max_step == 6


def test_zero_link_restores_learned_mapping_without_enabling_disabled_buff(tmp_path, monkeypatch):
    import nrobot.packet_settings as module
    monkeypatch.setattr(module, 'CONFIG', tmp_path/'config.json')
    (tmp_path/'buffs_aprendidos.json').write_text('{"29": 12}')
    result = module.validate({'skill_profiles': [{'skill_id': 29, 'role': 'buff', 'level': 5, 'enabled': False, 'effect_id': 0}]})
    assert result['skill_profiles'][0]['effect_id'] == 12
    assert not result['skill_profiles'][0]['enabled']
    module.save(result, tmp_path/'config.json')
    assert json.loads((tmp_path/'buffs_aprendidos.json').read_text())['29'] == 12
