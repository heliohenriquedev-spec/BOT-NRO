import struct

from nrobot.ammo import AmmoInventory
from nrobot.combat_rotation import CombatRotation
from nrobot.packet_encoder import equip_ammo
from nrobot.packet_reader import decode


def inventory():
    ammo = AmmoInventory({13254:'Shuriken',13256:'Kunai de arremeso',1151:'Tokubetsu Kunai'})
    entries = b''.join(struct.pack('<HHBBHH8s', index, item, kind, 1, amount, equipped, bytes(8))
                       for index,item,kind,amount,equipped in ((2,13254,10,50,0),(3,13256,10,60,0x8000),(4,1151,4,1,0)))
    ammo.observe([decode(struct.pack('<HH',0xa3,len(entries)+4)+entries)],0)
    return ammo


def state(ammo, now):
    return {'state':'tracking','player_position_recent':True,'player_position':[10,10],
            'player_id':1,'player_sp':100,'own_effects':{},'ammo':ammo.snapshot(now),
            'learned_skills':[{'skill_id':i,'level':10,'sp_cost':1,'range':6,'target_flags':1} for i in (523,524)],
            'recent_entities':[{'entity_id':20,'position':[12,10]}]}


def test_only_ammunition_is_selected_and_native_equipment_encoding_is_exact():
    ammo=inventory()
    options=ammo.snapshot(0)['options']
    assert set(options)=={523,524}
    assert options[524]['ready'] and not options[523]['ready']
    assert options[524]['index']==3 and options[523]['amount']==50
    assert equip_ammo(2)==b'\xa9\x00\x02\x00\x00\x80'


def test_rotation_uses_current_ammo_then_waits_for_equipment_confirmation_before_next_skill():
    ammo=inventory()
    profiles=[{'skill_id':i,'enabled':True,'role':'offensive','level':10,'interval':.5,'effect_id':0} for i in (523,524)]
    rotation=CombatRotation(profiles)
    action=rotation.plan(state(ammo,0),0,20)
    assert action['kind']=='skill' and action['skill_id']==524
    rotation.sent(action,0)
    assert rotation.plan(state(ammo,.2),.2,20) is None  # prior offensive request is still pending
    rotation.observe([{'kind':'skill_damage','skill_id':524,'source_id':1,'target_id':20,'level':10,'damage_raw':100}],1,.1)
    assert rotation.plan(state(ammo,.2),.2,20) is None  # REDE-76: server delay after the hit
    action=rotation.plan(state(ammo,.7),.7,20)
    assert action['kind']=='equip' and action['inventory_index']==2
    ammo.sent(2,.7)
    assert rotation.plan(state(ammo,.8),.8,20) is None
    ammo.observe([decode(struct.pack('<HHHB',0xaa,2,0x8000,1))],.81)
    action=rotation.plan(state(ammo,.82),.82,20)
    assert action['kind']=='skill' and action['skill_id']==523


def test_equipment_refusal_timeout_and_consumption_never_mark_ammo_ready():
    ammo=inventory()
    ammo.sent(2,0)
    ammo.observe([decode(struct.pack('<HHHB',0xaa,2,0,0))],.1)
    assert 523 not in ammo.snapshot(.2)['options'] and ammo.equipped==3
    ammo.sent(3,1)
    assert ammo.snapshot(3)['pending'] is None
    ammo.observe([{'kind':'inventory_removed','inventory_index':3,'amount':60}],3)
    assert ammo.equipped is None
    assert 524 not in ammo.snapshot(20)['options']


def test_unexpected_inventory_stride_does_not_invent_items():
    packet=struct.pack('<HH',0xa3,9)+bytes(5)
    assert decode(packet)['kind']=='inventory_layout_unknown'


def test_nro_stackable_02e8_list_exposes_ammo_and_02d0_accepts_newer_equipment_stride():
    ammo = AmmoInventory({13254:'Shuriken',13256:'Kunai de arremeso'})
    entries = b''.join(struct.pack('<HHBBHH8sI', index, item, 10, 1, amount, equipped, bytes(8), 0)
                       for index,item,amount,equipped in ((2,13254,50,0),(3,13256,60,0x8000)))
    ammo.observe([decode(struct.pack('<HH',0x2e8,len(entries)+4)+entries)],0)
    options = ammo.snapshot(0)['options']
    assert set(options)=={523,524} and options[524]['ready'] and options[523]['amount']==50
    gear = struct.pack('<HHBBHHBB8sIHH', 5, 1151, 4, 1, 2, 0, 0, 0, bytes(8), 0, 0, 0)
    event = decode(struct.pack('<HH',0x2d0,len(gear)+4)+gear)
    assert event['kind']=='inventory_list' and not event['stackable'] and event['items'][0]['item_id']==1151


def test_late_unequip_ack_for_old_stack_does_not_clear_new_ammo():
    ammo=inventory()
    ammo.observe([decode(struct.pack('<HHHB',0xaa,2,0x8000,1)),
                  decode(struct.pack('<HHHB',0xac,3,0x8000,1))],.1)
    assert ammo.equipped==2 and ammo.snapshot(.2)['options'][523]['ready']


def test_relay_equips_then_waits_for_server_ack_before_emitting_skill(tmp_path):
    import asyncio,time
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    from nrobot.network_targets import Entity
    async def scenario():
        relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
        relay.hunt=PacketHunt();relay.hunt.start();relay.hunt.target=20
        relay.ammo=inventory()
        relay.rotation=CombatRotation([{'skill_id':523,'enabled':True,'role':'offensive','level':10,'interval':.5,'effect_id':0}])
        now=time.monotonic();observer=relay.tracker.observer
        observer.player_id=1;observer.player=[10,10];observer.player_at=now;observer.sp=100;observer.species={1037}
        observer.skills[523]={'skill_id':523,'level':10,'sp_cost':2,'range':6,'target_flags':1}
        observer.registry.update(Entity(20,1037,12,10,now,'monster'))
        class Writer:
            def __init__(self):self.packets=[]
            def write(self,data):self.packets.append(data)
            async def drain(self):pass
        relay.upstream=Writer()
        action=relay.rotation.plan(relay.status(),now,20)
        assert action['kind']=='equip'
        assert await relay.send_rotation_action(action,game_gate=lambda:True)
        assert relay.upstream.packets==[equip_ammo(2)]
        assert relay.rotation.plan(relay.status(),time.monotonic(),20) is None
        relay.mirror_map(struct.pack('<HHHB',0xaa,2,0x8000,1))
        action=relay.rotation.plan(relay.status(),time.monotonic(),20)
        assert action['kind']=='skill'
        assert await relay.send_rotation_action(action,game_gate=lambda:True)
        assert [len(packet) for packet in relay.upstream.packets]==[6,25]
    asyncio.run(scenario())


def test_late_successful_equipment_ack_releases_timeout_backoff():
    ammo=inventory();ammo.sent(2,0)
    assert 523 not in ammo.snapshot(2)['options']
    ammo.observe([decode(struct.pack('<HHHB',0xaa,2,0x8000,1))],2.1)
    assert ammo.snapshot(2.2)['options'][523]['ready']


def _throw_rotation():
    profiles=[{'skill_id':i,'enabled':True,'role':'offensive','level':10,'interval':.5,'effect_id':0} for i in (523,524)]
    return CombatRotation(profiles,response_timeout=.75)


def _hit(skill_id):
    return [{'kind':'skill_damage','skill_id':skill_id,'source_id':1,'target_id':20,'level':10,'damage_raw':100}]


def test_throws_strictly_alternate_and_turn_waits_for_the_other_cooldown():
    ammo=inventory();rotation=_throw_rotation()
    action=rotation.plan(state(ammo,0),0,20)
    assert action['skill_id']==524
    rotation.sent(action,0);rotation.observe(_hit(524),1,.1)
    # Kunai is ready again before Shuriken's turn ends, but it must not be used twice in a row.
    rotation.ready[523]=2
    for now in (.7,1,1.9):
        assert rotation.plan(state(ammo,now),now,20) is None
        assert 'vez' in rotation.reason
    action=rotation.plan(state(ammo,2),2,20)
    assert action['kind']=='equip' and action['skill_id']==523


def test_unconfirmed_throw_is_retried_and_ammo_is_not_swapped_while_server_may_still_process_it():
    ammo=inventory();rotation=_throw_rotation()
    action=rotation.plan(state(ammo,0),0,20)
    rotation.sent(action,0)
    rotation.plan(state(ammo,.8),.8,20)  # 524 times out without confirmation
    assert 524 not in rotation.pending
    rotation.ready[524]=99  # Kunai deferred: Shuriken may take over, but only after settling
    assert rotation.plan(state(ammo,1.2),1.2,20) is None and 'arremesso anterior' in rotation.reason
    action=rotation.plan(state(ammo,1.6),1.6,20)
    assert action['kind']=='equip' and action['skill_id']==523


def test_turn_falls_back_when_other_throw_has_no_ammo():
    ammo=AmmoInventory({13256:'Kunai de arremeso'})
    entries=struct.pack('<HHBBHH8s',3,13256,10,1,60,0x8000,bytes(8))
    ammo.observe([decode(struct.pack('<HH',0xa3,len(entries)+4)+entries)],0)
    rotation=_throw_rotation()
    rotation.sent(rotation.plan(state(ammo,0),0,20),0);rotation.observe(_hit(524),1,.1)
    action=rotation.plan(state(ammo,.7),.7,20)
    assert action['kind']=='skill' and action['skill_id']==524
