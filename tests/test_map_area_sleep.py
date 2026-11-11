"""yuno_fild07: Coelho x3 -> server Fukai Kemuri, silence everything, lowest HP first."""
import json
from pathlib import Path
import pytest
from nrobot.map_behavior import validate
from nrobot.map_combat import MapCombat, settings_for
from nrobot.combat_rotation import CombatRotation

PROFILE = Path('exemplos/comportamentos/yuno_fild07.json')


@pytest.fixture
def config():
    return validate(json.loads(PROFILE.read_text(encoding='utf-8')))['combat']


def learned():
    rows = [dict(skill_id=i, level=5, sp_cost=1, range=r, target_flags=1)
            for i, r in [(179, 9), (182, 9), (76, 5), (524, 6), (523, 6), (1016, 2)]]
    return rows+[dict(skill_id=500, level=1, sp_cost=2, range=0, target_flags=4)]


def state(entities, **extra):
    return dict(state='tracking', player_id=1, player_position=[20, 20], player_position_recent=True, player_sp=1000,
                learned_skills=learned(), recent_entities=entities, own_effects={}, **extra)


def mob(identity, species=1057, x=21, y=20, body=0, health=0, **extra):
    return dict(entity_id=identity, species_id=species, kind='monster', position=[x, y], body_state=body,
                health_state=health, position_usable=True, **extra)


def rotation(config):
    from nrobot.packet_settings import DEFAULTS
    s = settings_for(config, DEFAULTS, learned())
    return CombatRotation(s['skill_profiles'], fast=True, priority=s['skill_priority'])


def seal_ack(player=1, success=True):
    return dict(kind='skill_no_damage', skill_id=500, source_id=player, target_id=player, success=success)


def test_profile_imports_with_its_rules(config):
    assert [r['skill_id'] for r in config['skills']['offensives']] == [524, 523, 1016]
    assert config['passive_species'] == []
    assert config['area_sleep']['prepare_casts'] == 3 and config['focus']['lowest_hp']


def test_two_others_awake_get_three_seals_then_the_server_kemuri(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, x=24), mob(12, x=23)])
    intent = c.decide(s, r, 100)
    assert intent['mode'] == 'area_sleep'
    for i in range(3):
        action = c.plan(s, r, 100+i)
        assert action['skill_id'] == 500 and action['target_id'] == 1 and action['area_sleep_stage'] == 'prepare'
        r.sent(action, 100+i); c.sent(action, 100+i)
        assert c.plan(s, r, 100+i+.05) is None  # one seal in flight at a time
        events = [seal_ack()]
        r.observe(events, 1, 100+i+.1); c.observe(events, 1, 100+i+.1)
    assert c.decide(s, r, 102.2)['phase'] == 'area' and c.plan(s, r, 102.2) is None
    # The server answers the third seal with Kemuri itself; the bot never casts 668.
    c.observe([dict(kind='skill_no_damage', skill_id=668, source_id=1, target_id=1, success=True),
               dict(kind='skill_damage', skill_id=668, level=1, source_id=1, target_id=10, damage_raw=4294937296)], 1, 102.3)
    assert c.area.fired == 1 and c.damage.get(10, 0) == 0  # the -30000 marker is not damage
    for row in s['recent_entities']:
        row['body_state'] = 4
    intent = c.decide(s, r, 102.4)
    assert intent['target_id'] == 10 and intent['skill_id'] == 76  # the one to kill: silence first, even asleep
    s['recent_entities'][0]['health_state'] = 4
    assert c.decide(s, r, 102.5)['mode'] == 'kill'  # silenced: damage; the others stay asleep, untouched


def test_one_monster_alone_is_stunned_not_sealed(config):
    c = MapCombat(config); r = rotation(config)
    assert c.decide(state([mob(10)]), r, 100)['skill_id'] == 179


def test_a_single_other_awake_gets_fukai_yasumi_two_get_kemuri(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, x=24)])
    intent = c.decide(s, r, 100)
    assert intent['target_id'] == 11 and intent['skill_id'] == 182  # the other one: Fukai Yasumi
    s = state([mob(10), mob(11, x=24), mob(12, x=23)])
    assert c.decide(s, r, 101)['mode'] == 'area_sleep'  # two others awake: Kemuri


def test_unanswered_seal_falls_back_to_normal_combat(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, x=24), mob(12, x=23)])
    c.decide(s, r, 100)
    for at in (100, 101.2, 102.4):
        assert c.decide(s, r, at)['mode'] == 'area_sleep'  # unanswered: sent again (twice)
        c.area.sent(dict(area_sleep_stage='prepare'), at)
    assert c.decide(s, r, 103.6)['mode'] == 'control'  # third time without answer: stun as usual
    assert 'sem resposta' in c.area.reason
    assert c.decide(s, r, 106)['mode'] == 'control'  # a short pause before new seals
    assert c.decide(s, r, 109)['mode'] == 'area_sleep'


def test_first_seal_waits_for_the_previous_skill(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, x=24), mob(12, x=23)])
    assert c.decide(s, r, 100)['mode'] == 'area_sleep'
    r.pending[523] = dict(role='offensive', sp_cost=1, deadline=101.5, target_id=10, level=5)
    assert c.plan(s, r, 100) is None  # a Shuriken still unanswered
    r.pending.clear(); r.last_sent[357] = 99.9
    assert c.plan(s, r, 100) is None  # a buff 100 ms ago
    assert c.plan(s, r, 100.4)['skill_id'] == 500


def test_seals_without_kemuri_mean_recharge(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, x=24), mob(12, x=23)])
    c.decide(s, r, 100)
    c.area.phase, c.area.area_since = 'area', 100
    assert c.decide(s, r, 101.5)['mode'] != 'area_sleep'
    assert c.decide(s, r, 103)['mode'] != 'area_sleep'  # still recharging
    assert c.decide(s, r, 104.6)['mode'] == 'area_sleep'  # rearmed


def test_kills_the_lowest_hp_first_and_sticks_to_it(config):
    c = MapCombat(config); r = rotation(config)
    far, near = mob(10, x=26, body=4, species_max_hp=1000), mob(11, x=21, body=4, species_max_hp=1000)  # slept by Kemuri
    s = state([far, near])
    assert c.decide(s, r, 100)['target_id'] == 11  # both full: the closest
    c.observe([dict(kind='skill_damage', skill_id=524, level=5, source_id=1, target_id=10, damage_raw=300)], 1, 100)
    assert c.decide(s, r, 100.1)['target_id'] == 10
    c.observe([dict(kind='name', entity_id=11, hp=500, max_hp=1000)], 1, 100.2)
    assert c.decide(s, r, 100.3)['target_id'] == 11  # 50% beats 70%
    c.observe([dict(kind='skill_damage', skill_id=524, level=5, source_id=1, target_id=11, damage_raw=100)], 1, 100.4)
    assert c.decide(s, r, 100.5, current=11)['target_id'] == 11


def test_kemuri_only_with_monsters_within_four_cells(config):
    c = MapCombat(config); r = rotation(config)
    assert c.decide(state([mob(10, x=21), mob(11, x=25), mob(12, x=23)]), r, 100)['mode'] == 'control'  # one 5 cells away
    assert c.decide(state([mob(10, x=21), mob(11, x=24), mob(12, x=23)]), r, 100.1)['mode'] == 'area_sleep'


def test_after_kemuri_the_target_gets_silence_before_damage(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, x=22, body=4), mob(12, x=23, body=4)])
    c.area.fired_at = 100
    intent = c.decide(s, r, 101)
    assert intent['target_id'] == 10 and intent['skill_id'] == 76  # silence only, no stun/sleep
    r.ready[76] = 105
    assert c.decide(s, r, 102)['mode'] == 'control'  # silence recharging: waits, no unsilenced hit


def test_failing_control_is_given_up_for_damage(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10)])
    assert c.decide(s, r, 100)['mode'] == 'control'
    assert c.decide(s, r, 105.5)['mode'] == 'control'  # still trying the silence
    assert c.decide(s, r, 110.5)['mode'] == 'kill'  # 10 s without silence: attack it anyway
    assert c.decide(s, r, 126)['mode'] == 'control'  # later the control is tried again


def test_own_single_sleep_still_gets_silence(config):
    c = MapCombat(config); r = rotation(config)
    c.history[10] = {'sleep': 99.0}
    assert c.decide(state([mob(10, body=4)]), r, 100)['skill_id'] == 76


def test_profile_keeps_buffs_and_goes_melee(config):
    assert [b['skill_id'] for b in config['skills']['buffs']] == [29, 357, 532, 775]
    assert config['focus']['melee'] and config['area_sleep']['radius'] == 4


def test_melee_with_skills_walks_up_instead_of_holding_kunai_range():
    from nrobot.packet_hunt import PacketHunt
    from nrobot.map_navigation import CollisionMap
    collision = CollisionMap(30, 30, bytes([1])*900)
    kunai = [dict(skill_id=524, level=20, range=6, sp_cost=1, target_flags=1)]
    s = dict(state='tracking', player_position_recent=True, player_position=[10, 10], player_sp=100, engagement_range=6,
             learned_skills=kunai, recent_entities=[dict(entity_id=20, position=[14, 10], position_age_seconds=.1)])
    hunt = PacketHunt(use_skills=True); hunt.start()
    assert hunt.plan(dict(s), 0, collision=collision)['kind'] != 'move'  # Kunai mode: holds its range
    hunt = PacketHunt(use_skills=True); hunt.start()
    action = hunt.plan({**s, 'melee_with_skills': True}, 0, collision=collision)
    assert action['kind'] == 'move' and action['destination'] == [13, 10]  # goes in for basic attacks
    s['player_position'] = [13, 10]
    assert hunt.plan({**s, 'melee_with_skills': True}, 1, collision=collision) == dict(kind='attack', target_id=20)


def test_keeps_the_others_asleep_while_killing_one(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10, health=4), mob(11, x=22, body=4), mob(12, x=23, body=4)])
    c.area.fired_at = 90
    assert c.decide(s, r, 100, current=10)['mode'] == 'kill'  # only the target is awake
    s['recent_entities'][2]['body_state'] = 0
    s['recent_entities'][2]['health_state'] = 4  # silenced but awake: still has to sleep
    intent = c.decide(s, r, 100.1, current=10)
    assert intent['target_id'] == 12 and intent['skill_id'] == 182  # a single one: Fukai Yasumi
    s['recent_entities'][1]['body_state'] = 0
    assert c.decide(s, r, 100.2, current=10)['mode'] == 'area_sleep'  # two awake: Kemuri


def test_baru_gets_no_control_and_dies_last(config):
    c = MapCombat(config); r = rotation(config)
    baru = mob(10, species=1032, x=21, species_max_hp=1000)
    enma = mob(11, x=26, body=4, health=4, species_max_hp=1000)
    s = state([baru, enma])
    c.observe([dict(kind='skill_damage', skill_id=524, level=5, source_id=1, target_id=10, damage_raw=900)], 1, 100)
    intent = c.decide(s, r, 100)
    assert intent['mode'] == 'kill' and intent['target_id'] == 11  # Baru closer and nearly dead, still last
    s = state([mob(10, species=1032), mob(12, species=1032, x=22), mob(13, species=1032, x=23)])
    intent = c.decide(s, r, 101)
    assert intent['mode'] == 'kill' and intent['target_id'] == 10  # only Baru: no Kemuri, no stun


def test_two_monsters_hitting_the_player_call_the_kemuri(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, species=1032, x=22)])  # the target and a Baru, both hitting
    c.observe([dict(kind='normal_attack', source_id=10, target_id=1, damage_raw=5),
               dict(kind='normal_attack', source_id=11, target_id=1, damage_raw=5)], 1, 100)
    assert c.decide(s, r, 100.1)['mode'] == 'area_sleep'


def test_order_is_everything_then_baru_then_anbu_without_control(config):
    c = MapCombat(config); r = rotation(config)
    anbu, baru = mob(10, species=1635, x=21, body=4), mob(11, species=1032, x=22, body=4)
    assert c.decide(state([anbu, baru]), r, 100)['target_id'] == 11
    assert c.decide(state([anbu]), r, 101)['target_id'] == 10  # alone: it is the one (silence first)


def summon_learned():
    return learned()+[dict(skill_id=729, level=4, sp_cost=150, range=4, target_flags=2)]


def test_below_60_percent_the_namekuji_goes_before_damage(config):
    from nrobot.packet_settings import DEFAULTS
    c = MapCombat(config)
    s = settings_for(config, DEFAULTS, summon_learned())
    r = CombatRotation(s['skill_profiles'], fast=True, priority=s['skill_priority'])
    st = state([mob(10, body=4, health=4)], player_hp=50, player_max_hp=100)
    st['learned_skills'] = summon_learned()
    intent = c.decide(st, r, 100)
    assert intent['mode'] == 'summon'
    action = c.plan(st, r, 100)
    assert action['skill_id'] == 729 and action['role'] == 'summon'
    st['player_hp'] = 70
    assert c.decide(st, r, 100)['mode'] == 'kill'


def test_below_20_percent_it_recovers_until_60(config):
    from nrobot.packet_settings import DEFAULTS
    c = MapCombat(config)
    s = settings_for(config, DEFAULTS, summon_learned())
    r = CombatRotation(s['skill_profiles'], fast=True, priority=s['skill_priority'])
    r.ready[729] = 200  # summon recharging
    st = state([mob(10, body=4, health=4)], player_hp=15, player_max_hp=100)
    st['learned_skills'] = summon_learned()
    assert c.decide(st, r, 100)['mode'] == 'kill'  # a monster close by: no sitting in the middle of it
    st['recent_entities'] = [mob(10, x=35, body=4, health=4)]
    assert c.decide(st, r, 100.5)['mode'] == 'recover'  # nobody near: sit, no damage
    st['player_hp'] = 45
    assert c.decide(st, r, 101)['mode'] == 'recover'  # still below 60
    st['player_hp'] = 60
    assert c.decide(st, r, 102)['mode'] == 'kill'


def test_kemuri_comes_before_the_low_hp_summon(config):
    from nrobot.packet_settings import DEFAULTS
    c = MapCombat(config)
    s = settings_for(config, DEFAULTS, summon_learned())
    r = CombatRotation(s['skill_profiles'], fast=True, priority=s['skill_priority'])
    st = state([mob(10), mob(11, x=24), mob(12, x=23)], player_hp=40, player_max_hp=100)
    st['learned_skills'] = summon_learned()
    assert c.decide(st, r, 100)['mode'] == 'area_sleep'
    st = state([mob(10), mob(11, x=24)], player_hp=40, player_max_hp=100)
    st['learned_skills'] = summon_learned()
    assert MapCombat(config).decide(st, r, 100)['skill_id'] == 182  # Yasumi on the other one first
    for row in st['recent_entities']:
        row['body_state'] = 4
    assert MapCombat(config).decide(st, r, 100)['mode'] == 'summon'  # all asleep: now the Namekuji


def test_relay_sits_while_recovering_and_stands_to_summon():
    import asyncio
    from types import SimpleNamespace
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_encoder import SIT, STAND
    sent, mode = [], ['recover']

    async def body(action):
        sent.append(action); return True
    stub = SimpleNamespace(
        active_map_combat=lambda: SimpleNamespace(config={'idle_summon': {'skill_id': 729}}, recovering=True),
        rotation=SimpleNamespace(next_send=0), tracker=SimpleNamespace(observer=SimpleNamespace(player_alive=True, hp=10, max_hp=100)),
        status=lambda: {'player_position': [1, 1]}, map_combat_intent=lambda c, s, n: {'mode': mode[0]},
        recover_sitting=False, sitting=False, walking_now=lambda: False, send_body_action=body,
        hunt=SimpleNamespace(pending=None, reason='', ready_at=0), record_hunt=lambda e: None)
    run = lambda now: asyncio.run(SessionRelay.update_low_hp_sit(stub, now))
    assert run(1) is True and sent == [SIT]
    assert run(2) is True and sent == [SIT]  # stays seated, sends nothing more
    mode[0] = 'summon'
    assert run(3) is True and sent == [SIT, STAND] and stub.rotation.next_send >= 3.6
    assert run(4) is False  # standing: the rotation casts the Namekuji


def test_a_buff_that_went_off_is_renewed_between_controls(config):
    from nrobot.packet_settings import DEFAULTS
    skills = learned()+[dict(skill_id=357, level=3, sp_cost=1, range=0, target_flags=4),
                        dict(skill_id=29, level=5, sp_cost=1, range=0, target_flags=4)]
    s = settings_for(config, DEFAULTS, skills)
    r = CombatRotation(s['skill_profiles'], fast=True, priority=s['skill_priority'])
    c = MapCombat(config)
    st = state([mob(10)]); st['own_effects'] = {12: True}  # Dai Senkou (effect 105) went off
    st['learned_skills'] = skills
    assert c.decide(st, r, 100)['mode'] == 'control'
    action = c.plan(st, r, 100)
    assert action['skill_id'] == 357 and action['target_id'] == 1
    st['own_effects'] = {12: True, 105: True}
    assert c.plan(st, r, 101)['skill_id'] == 179  # back to the stun


def test_go_hunt_button_builds_an_endless_database_hunt_on_the_profile_map():
    from nrobot.map_behavior_panel import hunt_request
    from nrobot.database_hunt import database_hunt_route, ENDLESS
    profile = validate(json.loads(PROFILE.read_text(encoding='utf-8')))
    request = hunt_request(profile)
    assert request['target_map'] == 'yuno_fild07' and 1032 in request['species'] and 1635 in request['species']
    route = database_hunt_route(request, [dict(id='r', name='Nuvem 7', target_map='yuno_fild07.gat', steps=[])])
    assert route['target_map'] == 'yuno_fild07.gat' and route['kills'] == ENDLESS


def test_an_attacker_whose_control_was_given_up_still_gets_silence_tries(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10, species=1381)])
    assert c.decide(s, r, 100)['mode'] == 'control'
    c.observe([dict(kind='normal_attack', source_id=10, target_id=1, damage_raw=5)], 1, 110.4)
    intent = c.decide(s, r, 110.5)  # 10 s without control, but it is hitting the player
    assert intent['skill_id'] == 76
    c.history[10] = {'silence': 110.5}
    assert c.decide(s, r, 111)['mode'] == 'kill'  # damage between the tries
    c.observe([dict(kind='normal_attack', source_id=10, target_id=1, damage_raw=5)], 1, 112)
    assert c.decide(s, r, 112.1)['skill_id'] == 76


def test_target_on_a_ground_skill_gets_only_throws_in_burst(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10, x=24, body=4, health=4)])
    s['ground_hazard_cells'] = [[24, 20], [25, 20]]
    s['learned_skills'] = [dict(skill_id=i, level=5, sp_cost=1, range=rg, target_flags=1)
                           for i, rg in [(179, 9), (182, 9), (76, 5), (524, 6), (523, 6), (1016, 6)]]
    assert c.target_on_hazard(10, s) and c.throw_range(s) == 5
    seen = set()
    for i in range(6):
        action = c.plan(s, r, 100+i)
        if action:
            seen.add(action['skill_id']); r.sent(action, 100+i)
            r.pending.clear()
    assert seen and seen <= {523, 524}  # never Punhos Intensos, even "in range"
    assert r.burst is False  # burst only while planning on the area
    s['ground_hazard_cells'] = []
    assert not c.target_on_hazard(10, s)


def test_seals_do_not_wait_forever_on_an_expired_pending_skill(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10), mob(11, x=24), mob(12, x=23)])
    assert c.decide(s, r, 100)['mode'] == 'area_sleep'
    r.pending[179] = dict(role='offensive', sp_cost=1, deadline=101.5, target_id=10, level=5, control_status='stun')
    r.last_sent[179] = 100
    assert c.plan(s, r, 100.5) is None  # still within its answer window
    action = c.plan(s, r, 101.6)  # expired: dropped, the first seal goes out
    assert action and action['skill_id'] == 500 and 179 not in r.pending


def test_anbu_gets_only_silence_before_being_killed(config):
    c = MapCombat(config); r = rotation(config)
    anbu = mob(10, species=1635)
    intent = c.decide(state([anbu]), r, 100)
    assert intent['target_id'] == 10 and intent['skill_id'] == 76  # no stun or sleep on it
    anbu['health_state'] = 4
    assert c.decide(state([anbu]), r, 100.5)['mode'] == 'kill'
    # Not the one to kill: left alone (no Fukai Yasumi, not counted for the Kemuri).
    s = state([mob(11, health=4), mob(12, species=1635, x=22), mob(13, species=1635, x=23)])
    assert c.decide(s, r, 101)['mode'] == 'kill' and c.decide(s, r, 101)['target_id'] == 11


def test_silence_is_cast_from_two_cells(config):
    c = MapCombat(config); r = rotation(config)
    s = state([mob(10)])
    assert c.control_margin(76, r, s) == 3  # silence range 5: cast within 2 cells
