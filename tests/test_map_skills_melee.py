"""REDE-83: habilidades após trocar de mapa, arremessos na rajada e ataque básico."""
import math

from nrobot.combat_rotation import CombatRotation
from nrobot.network_observer import Observer
from nrobot.packet_hunt import PacketHunt


SKILLS = [{'skill_id': 179, 'level': 10, 'sp_cost': 10, 'range': 9, 'target_flags': 1},
          {'skill_id': 523, 'level': 10, 'sp_cost': 5, 'range': 9, 'target_flags': 1},
          {'skill_id': 524, 'level': 10, 'sp_cost': 5, 'range': 9, 'target_flags': 1}]


def test_skills_survive_a_map_change_and_a_new_list_still_replaces_them():
    observer = Observer({1037})
    observer.apply({'kind': 'skills_info', 'skills': SKILLS, 'replace': True}, 0)
    observer.apply({'kind': 'player_stat', 'stat_type': 7, 'value': 900}, 0)
    observer.apply({'kind': 'map_change', 'map': 'areia.gat', 'position': [10, 10]}, 1)
    assert sorted(observer.skills) == [179, 523, 524] and observer.sp == 900 and observer.map_name == 'areia.gat'
    observer.apply({'kind': 'map_transfer'}, 2)
    assert sorted(observer.skills) == [179, 523, 524]
    observer.apply({'kind': 'skills_info', 'skills': SKILLS[:1], 'replace': True}, 3)  # e.g. another character
    assert sorted(observer.skills) == [179]


def profile(identity):
    return {'skill_id': identity, 'enabled': True, 'role': 'offensive', 'level': 10, 'interval': 5, 'effect_id': 0}


def state(ammo_ready_524=True, pending=None):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10], 'player_id': 1,
            'player_sp': 999, 'own_effects': {}, 'own_cast_until': 0, 'learned_skills': SKILLS,
            'recent_entities': [{'entity_id': 20, 'position': [14, 10], 'position_age_seconds': .1}],
            'ammo': {'pending': pending, 'options': {523: {'index': 2, 'ready': not ammo_ready_524},
                                                     524: {'index': 3, 'ready': ammo_ready_524}}}}


def test_throws_take_their_turn_in_a_burst_and_the_ammo_is_swapped_in_that_turn():
    rotation = CombatRotation([profile(179), profile(523), profile(524)], burst=True, priority=[179, 'throws'])
    kinds, now = [], 0.0
    for _ in range(12):
        action = rotation.plan(state(), now, 20)
        if action is not None:
            if action['kind'] == 'skill':
                rotation.sent(action, now)
                if action['skill_id'] == 524:
                    rotation.observe([{'kind': 'skill_damage', 'skill_id': 524, 'source_id': 1, 'target_id': 20,
                                       'level': 10, 'damage_raw': 1}], 1, now+.01)
            kinds.append((action['kind'], action['skill_id']))
            if action['kind'] == 'equip':
                break
        now += .05
    assert ('skill', 524) in kinds and ('skill', 179) in kinds
    assert kinds[-1] == ('equip', 523)  # Shuriken's turn: equipped right there, not starved


def hunt_state(player, monster, engagement=6):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': player, 'player_sp': 999,
            'learned_skills': [], 'engagement_range': engagement,
            'recent_entities': [{'entity_id': 20, 'position': monster, 'position_age_seconds': .1}]}


def test_without_basic_attacks_the_bot_keeps_its_skill_distance():
    hunt = PacketHunt()
    hunt.auto_attacks = False
    hunt.start()
    assert hunt.plan(hunt_state([10, 10], [16, 10]), 0) is None  # at the edge of skill range: stays there
    assert 'só habilidades' in hunt.reason
    for monster in ([11, 10], [13, 12]):  # REDE-84: inside the skill distance it runs away
        hunt.target, hunt.pending = None, None
        retreat = hunt.plan(hunt_state([10, 10], monster), 1)
        assert retreat['kind'] == 'move' and retreat['purpose'] == 'keep_distance'
        assert math.dist(retreat['destination'], monster) > math.dist([10, 10], monster)


def test_running_away_goes_around_a_wall():
    from nrobot.map_navigation import CollisionMap
    cells = bytearray([1]*(40*40))
    for y in range(40):
        cells[y*40+8] = 0  # wall right behind the player (x=8)
    collision = CollisionMap(40, 40, cells)
    hunt = PacketHunt()
    hunt.auto_attacks = False
    hunt.start()
    retreat = hunt.plan(hunt_state([10, 20], [12, 20]), 0, collision=collision)
    assert retreat['purpose'] == 'keep_distance' and retreat['destination'][0] > 8
    assert collision.segment([10, 20], retreat['destination'], max_steps=8)
    assert math.dist(retreat['destination'], [12, 20]) > 2


def test_basic_attacks_do_not_override_ranged_spacing():
    hunt = PacketHunt()
    hunt.start()
    assert hunt.plan(hunt_state([10, 10], [15, 10]), 0) is None
    close = hunt.plan(hunt_state([10, 10], [12, 10]), 1)
    assert close['purpose'] == 'keep_distance'
    distance = math.dist(close['destination'], [12, 10])
    assert 2 < distance <= 6


def test_basic_attack_waits_while_a_skill_in_reach_is_about_to_be_ready():
    rotation = CombatRotation([profile(179), profile(523)], priority=[179, 'throws'])
    snapshot = state()
    snapshot['ammo'] = None
    assert rotation.soonest_offensive(snapshot, 10, 20) == 10  # a skill is ready now: no basic attack
    rotation.ready.update({179: 13, 523: 12})
    assert rotation.soonest_offensive(snapshot, 10, 20) == 12  # both waiting: a basic attack fits
    snapshot['recent_entities'][0]['position'] = [30, 10]  # beyond every skill's reach
    import math
    assert rotation.soonest_offensive(snapshot, 10, 20) == math.inf


def test_basic_attacks_take_a_turn_after_each_skill_only_when_enabled(tmp_path):
    from nrobot.packet_settings import DEFAULTS
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    attack = {'kind': 'attack', 'target_id': 20}
    relay.apply_settings({**DEFAULTS, 'species': [1037]})
    assert relay.attack_turn(attack) and not relay.attack_turn({'kind': 'move'})
    relay.apply_settings({**DEFAULTS, 'species': [1037], 'auto_attacks': False})
    assert not relay.attack_turn(attack) and not relay.hunt.auto_attacks


def test_an_unanswered_basic_attack_does_not_hold_the_next_one_for_long():
    hunt = PacketHunt()
    hunt.start()
    action = hunt.plan(hunt_state([10, 10], [11, 10], engagement=2), 0)
    assert action['kind'] == 'attack'
    hunt.sent(action, 0)
    assert hunt.pending['deadline'] <= PacketHunt.ATTACK_RESPONSE_TIMEOUT
