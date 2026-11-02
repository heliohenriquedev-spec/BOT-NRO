import asyncio
import struct
import time

from nrobot.combat_rotation import CombatRotation, skill_category
from nrobot.packet_reader import decode
from nrobot.session_relay import SessionRelay
from nrobot.packet_hunt import PacketHunt
from nrobot.packet_settings import DEFAULTS
from nrobot.network_targets import Entity


def profile(identity, role='offensive', effect=0):
    return {'skill_id': identity, 'enabled': True, 'role': role, 'level': 10, 'interval': .5, 'effect_id': effect}


def state():
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10],
            'player_id': 1, 'player_sp': 100, 'own_effects': {}, 'own_cast_until': 0,
            'learned_skills': [{'skill_id': 524, 'name': 'Kunai', 'level': 10, 'sp_cost': 20, 'range': 6, 'target_flags': 1},
                               {'skill_id': 525, 'name': 'Other', 'level': 10, 'sp_cost': 20, 'range': 6, 'target_flags': 1},
                               {'skill_id': 29, 'name': 'Buff', 'level': 10, 'sp_cost': 10, 'range': 0, 'target_flags': 4}],
            'recent_entities': [{'entity_id': 20, 'position': [12, 10], 'position_age_seconds': .1}]}


def test_offensives_have_independent_cooldowns_reservations_and_no_duplicate_pending():
    rotation = CombatRotation([profile(524), profile(525)])
    first = rotation.plan(state(), 0, 20)
    assert first['skill_id'] == 524
    rotation.sent(first, 0)
    assert rotation.plan(state(), .13, 20) is None  # REDE-76: never two unconfirmed skills
    event = {'kind': 'skill_damage', 'source_id': 1, 'target_id': 20, 'skill_id': 524, 'level': 10, 'damage_raw': 100}
    rotation.observe([{**event, 'source_id': 2}], 1, .01)
    assert rotation.confirmed == 0
    rotation.observe([event], 1, .01)
    assert rotation.confirmed == 1
    assert rotation.plan(state(), .4, 20) is None  # server delay after a confirmed skill
    second = rotation.plan(state(), .57, 20)
    assert second['skill_id'] == 525
    rotation.sent(second, .57)
    assert rotation.plan(state(), .6, 20) is None


def test_pending_skill_reserves_sp_for_following_request():
    rotation = CombatRotation([profile(524), profile(525)])
    snapshot = state()
    snapshot['player_sp'] = 30
    first = rotation.plan(snapshot, 0, 20)
    rotation.sent(first, 0)
    assert rotation.plan(snapshot, .13, 20) is None
    assert 'confirmação' in rotation.reason
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 524, 'source_id': 1, 'target_id': 20,
                       'level': 10, 'damage_raw': 100}], 1, .01)
    snapshot['player_sp'] = 10
    assert rotation.plan(snapshot, .6, 20) is None and 'SP insuficiente' in rotation.reason


def test_fair_rotation_does_not_starve_second_skill_when_first_is_ready_again():
    profiles = [profile(524), profile(525)]
    for entry in profiles: entry['interval'] = .1
    rotation = CombatRotation(profiles)
    first = rotation.plan(state(), 0, 20)
    rotation.sent(first, 0)
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 524, 'source_id': 1, 'target_id': 20,
                       'level': 10, 'damage_raw': 100}], 1, .01)
    assert rotation.plan(state(), .57, 20)['skill_id'] == 525


def test_skill_ignored_right_after_another_lengthens_the_learned_delay():
    rotation = CombatRotation([profile(524), profile(525)])
    rotation.sent(rotation.plan(state(), 0, 20), 0)
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 524, 'source_id': 1, 'target_id': 20,
                       'level': 10, 'damage_raw': 100}], 1, .01)
    second = rotation.plan(state(), .57, 20)
    rotation.sent(second, .57)
    rotation.plan(state(), 2.2, 20)  # no confirmation: the server was still in its delay
    assert rotation.after_skill_delay > CombatRotation.AFTER_SKILL_DELAY


def test_buffs_renew_only_after_effect_ends_and_unconfirmed_buff_is_blocked():
    rotation = CombatRotation([profile(29, 'buff', 12)])
    snapshot = state()
    snapshot['own_effects'] = {12: True}
    assert rotation.plan(snapshot, 0) is None
    snapshot['own_effects'][12] = False
    action = rotation.plan(snapshot, .1)
    assert action['target_id'] == 1
    rotation.sent(action, .1)
    rotation.observe([{'kind': 'status_effect', 'entity_id': 1, 'effect_id': 12, 'active': True}], 1, .2)
    assert rotation.buff_confirmed == 1 and not rotation.pending
    snapshot['own_effects'][12] = True
    assert rotation.plan(snapshot, 2) is None
    snapshot['own_effects'][12] = False
    rotation.sent(rotation.plan(snapshot, 3), 3)
    assert rotation.plan(snapshot, 5) is None
    assert 29 in rotation.blocked_buffs
    assert rotation.plan(snapshot, 100) is None  # do not recast an unconfirmed effect forever


def test_unmapped_buff_ground_passive_and_insufficient_sp_cannot_send():
    rotation = CombatRotation([profile(29, 'buff'), profile(524)])
    snapshot = state()
    snapshot['player_sp'] = 0
    assert rotation.plan(snapshot, 0, 20) is None
    snapshot['player_sp'] = 100
    snapshot['learned_skills'][0]['target_flags'] = 2
    rotation.profiles[1]['skill_id'] = 525
    snapshot['learned_skills'][1]['target_flags'] = 0
    assert rotation.plan(snapshot, 0, 20) is None
    assert 'chão' in skill_category({'target_flags': 2})


def test_server_cast_and_post_delay_extend_wait_without_unnecessary_timeout():
    rotation = CombatRotation([profile(524)])
    action = rotation.plan(state(), 0, 20)
    rotation.sent(action, 0)
    cast = decode(struct.pack('<HII5HI', 0x13e, 1, 20, 0, 0, 524, 0, 0, 3000))
    rotation.observe([cast], 1, .1)
    snapshot = state()
    snapshot['own_cast_until'] = 3.1
    assert rotation.plan(snapshot, 2, 20) is None and 524 in rotation.pending
    rotation.observe([decode(struct.pack('<HHI', 0x43d, 524, 5000))], 1, 3)
    assert rotation.ready[524] == 8


def test_rotation_interleaves_skill_with_pending_basic_attack_and_self_buff(tmp_path):
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = PacketHunt()
        profiles = [profile(524), profile(29, 'buff', 12)]
        relay.apply_settings({**DEFAULTS, 'require_collision': False, 'skill_profiles': profiles})
        relay.hunt.start()
        relay.hunt.target = 20
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
        observer.skills = {s['skill_id']: s for s in state()['learned_skills']}
        observer.sp = 100
        observer.registry.update(Entity(20, 1037, 12, 10, time.monotonic(), 'monster'))
        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        await relay.send_hunt_action({'kind': 'attack', 'target_id': 20}, game_gate=lambda: True)
        assert relay.hunt.pending['kind'] == 'attack'
        action = relay.rotation.plan(relay.status(), time.monotonic(), 20)
        assert action['role'] == 'buff' and action['target_id'] == 1
        assert await relay.send_rotation_action(action, game_gate=lambda: True)
        assert [len(data) for data in relay.upstream.packets] == [19, 25]
        assert relay.hunt.pending['kind'] == 'attack'  # independent confirmation tracking
    asyncio.run(scenario())


def test_character_chakra_feet_buff_full_expiration_and_renewal_cycle():
    """REDE-44: observed character skill 29/level 5 maps to own effect 12."""
    entry = profile(29, 'buff', 12)
    entry['level'] = 5
    rotation = CombatRotation([entry])
    snapshot = state()
    snapshot['learned_skills'][2]['level'] = 5
    snapshot['own_effects'] = {12: True}
    assert rotation.plan(snapshot, 0) is None
    end = {'kind': 'status_effect', 'entity_id': 1, 'effect_id': 12, 'active': False}
    rotation.observe([end], 1, 1)
    snapshot['own_effects'][12] = False
    action = rotation.plan(snapshot, 1)
    assert action['skill_id'] == 29 and action['level'] == 5 and action['target_id'] == 1
    rotation.sent(action, 1)
    assert rotation.plan(snapshot, 1.2) is None
    rotation.observe([{**end, 'active': True}], 1, 1.3)
    snapshot['own_effects'][12] = True
    assert rotation.buff_confirmed == 1
    assert rotation.plan(snapshot, 100) is None
    rotation.observe([end], 1, 101)
    snapshot['own_effects'][12] = False
    assert rotation.plan(snapshot, 101)['skill_id'] == 29


def test_global_delay_and_individual_cd_must_both_expire():
    rotation = CombatRotation([profile(524), profile(525)], global_delay=.7)
    snapshot = state()
    action = rotation.plan(snapshot, 0, 20)
    rotation.sent(action, 0)
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 524, 'source_id': 1,
                       'target_id': 20, 'level': 10, 'damage_raw': 10},
                      {'kind': 'skill_cooldown', 'skill_id': 524, 'duration_ms': 2000}], 1, .1)
    assert rotation.plan(snapshot, .69, 20) is None
    assert rotation.plan(snapshot, .71, 20)['skill_id'] == 525
    rotation.profiles[1]['enabled'] = False
    assert rotation.plan(snapshot, 2, 20) is None
    assert rotation.plan(snapshot, 2.11, 20)['skill_id'] == 524


def test_ranged_spacing_survives_cd_but_never_permits_out_of_range_skill():
    rotation = CombatRotation([profile(524)])
    snapshot = state()
    assert rotation.engagement_range(snapshot) == 6
    snapshot['recent_entities'][0]['position'] = [17, 10]
    assert rotation.plan(snapshot, 0, 20) is None
    snapshot['recent_entities'][0]['position'] = [16, 10]
    action = rotation.plan(snapshot, 0, 20)
    assert action['skill_id'] == 524
    rotation.sent(action, 0)
    assert rotation.engagement_range(snapshot) == 6
    assert rotation.plan(snapshot, .2, 20) is None


def test_own_animation_lock_is_separate_from_individual_cooldown():
    rotation = CombatRotation([profile(524), profile(525)])
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 524, 'source_id': 1,
                      'target_id': 20, 'level': 10, 'damage_raw': 10, 'source_motion_ms': 600}], 1, 0)
    assert rotation.plan(state(), .59, 20) is None
    assert rotation.plan(state(), .61, 20) is not None


def test_observed_zero_second_cooldown_is_not_a_target_failure_or_timeout():
    rotation = CombatRotation([profile(524)])
    action = rotation.plan(state(), 0, 20)
    rotation.sent(action, 0)
    text = b'[Cooldown]: Por favor aguarde mais 0 segundos para este jutsu recarregar.\0'
    notice = decode(struct.pack('<HH', 0x9a, len(text)+4)+text)
    assert notice == {'opcode': '009A', 'kind': 'skill_retry_notice', 'seconds': 0}
    rotation.observe([notice], 1, .05)
    assert not rotation.pending and not rotation.failures
    assert rotation.plan(state(), 1, 20) is None
    action = rotation.plan(state(), 1.06, 20)
    rotation.sent(action, 1.06)
    assert rotation.ready[524] >= 2.1
    ordinary = b'private unrelated text\0'
    assert decode(struct.pack('<HH', 0x8e, len(ordinary)+4)+ordinary) == {'opcode': '008E', 'kind': 'other'}


def test_moving_monster_can_be_hit_mid_transition_without_waiting_for_destination():
    from nrobot.network_targets import Entity
    rotation = CombatRotation([profile(524)])
    snapshot = state()
    actor = Entity(20, 1037, 20, 10, 0, 'monster', destination=(10,10), walk_speed_ms=200)
    positions, predicted = actor.combat_bounds(1)
    assert positions[0] == [15,10] and predicted
    snapshot['recent_entities'] = [{'entity_id':20, 'position':[20,10], 'destination':[10,10],
                                  'effective_position':positions[0], 'attack_positions':positions,
                                  'arrival_estimated':False, 'position_usable':True}]
    assert rotation.plan(snapshot, 1, 20)['skill_id'] == 524
    snapshot['player_position'] = [1,10]
    assert rotation.plan(snapshot, 1, 20) is None


def test_disabled_buff_and_disabled_attack_never_enter_rotation():
    profiles = [profile(29, 'buff', 12), profile(524)]
    for p in profiles: p['enabled'] = False
    assert CombatRotation(profiles).plan(state(), 0, 20) is None


def test_transition_range_is_revalidated_at_actual_packet_send(tmp_path):
    from nrobot.map_navigation import CollisionMap
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = PacketHunt()
        relay.hunt.start()
        relay.rotation = CombatRotation([profile(524)])
        relay.hunt.target = 20
        now = time.monotonic()
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at, observer.sp = 1, [10,10], now, 100
        observer.species = {1037}
        relay.ammo.names={13256:'Kunai de arremeso'}
        relay.ammo.items[2]={'index':2,'item_id':13256,'type':10,'amount':100}
        relay.ammo.equipped=2
        observer.skills[524] = {'skill_id':524,'level':10,'sp_cost':1,'range':6,'target_flags':1}
        observer.registry.update(Entity(20,1037,20,10,now-1,'monster',destination=(10,10),walk_speed_ms=200))
        collision = CollisionMap(30,30,[1]*900)
        relay.collision_map = lambda: collision
        class Writer:
            def __init__(self): self.packets=[]
            def write(self,data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream=Writer()
        action=relay.rotation.plan(relay.status(),time.monotonic(),20)
        assert action is not None
        # Move the player before send: the queued request must be rejected.
        observer.player=[1,10]
        assert not await relay.send_rotation_action(action,game_gate=lambda:True)
        assert not relay.upstream.packets
        observer.player=[10,10]
        assert await relay.send_rotation_action(action,game_gate=lambda:True)
        assert len(relay.upstream.packets)==1
        assert not observer.registry.entities[20].position_bounds(time.monotonic())[1]
    asyncio.run(scenario())


def test_skill_during_acknowledged_walk_uses_current_position_not_future_destination(tmp_path):
    from nrobot.map_navigation import CollisionMap
    async def scenario():
        relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
        relay.hunt=PacketHunt();relay.hunt.start();relay.hunt.target=20
        relay.rotation=CombatRotation([profile(524)])
        observer=relay.tracker.observer
        now=time.monotonic()
        observer.player_id=1;observer.player=[9,10];observer.player_at=now;observer.sp=100
        observer.walk_speed_ms=100;observer.species={1037}
        relay.ammo.names={13256:'Kunai de arremeso'}
        relay.ammo.items[2]={'index':2,'item_id':13256,'type':10,'amount':100}
        relay.ammo.equipped=2
        observer.skills[524]={'skill_id':524,'level':10,'sp_cost':1,'range':6,'target_flags':1}
        observer.apply({'kind':'player_move','position':[1,10],'destination':[9,10]},now-.2)
        assert observer.combat_positions(now)[0]==[3,10]
        observer.registry.update(Entity(20,1037,14,10,now,'monster'))
        assert relay.rotation.plan(relay.status(),now,20) is None  # destination 9 is in range, current 3 is not
        observer.registry.update(Entity(20,1037,8,10,now,'monster'))
        relay.hunt.pending={'kind':'move','movement_acknowledged':False}
        collision=CollisionMap(30,30,[1]*900);relay.collision_map=lambda:collision
        class Writer:
            def __init__(self):self.packets=[]
            def write(self,data):self.packets.append(data)
            async def drain(self):pass
        relay.upstream=Writer()
        action=relay.rotation.plan(relay.status(),now,20)
        assert action is not None
        assert not await relay.send_rotation_action(action,game_gate=lambda:True)
        relay.hunt.pending['movement_acknowledged']=True
        assert await relay.send_rotation_action(action,game_gate=lambda:True)
        assert len(relay.upstream.packets)==1
        observer.apply({'kind':'position','entity_id':1,'position':[4,10]},now+.01)
        assert observer.player_motion is None and observer.combat_positions(now+.02)==[[4,10]]
    asyncio.run(scenario())
