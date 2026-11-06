import copy
import pytest
from nrobot import map_behavior as m
from nrobot.packet_settings import DEFAULTS

def profile(**settings):
    return dict(schema=1,name='Combate',map='MOC_FILD01.gat',settings=settings)

def test_roundtrip_and_normalize(tmp_path):
    path=tmp_path/'profiles.json'
    m.save([profile(kite=True)],path)
    rows=m.load(path)
    assert rows[0]['map']=='moc_fild01'
    assert rows[0]['settings']=={'kite':True,'melee_approach':False}

@pytest.mark.parametrize('settings',[{'patrol':False},{'radius':40},{'script':'run'},{'kite':1},{'switch_distance':999}])
def test_reject_unsupported_or_invalid(settings):
    with pytest.raises(ValueError):m.validate(profile(**settings))

def test_effective_restores_and_does_not_mutate():
    base=copy.deepcopy(DEFAULTS)
    rows=[m.validate(profile(kite=True,auto_attacks=False))]
    active,p=m.effective(base,rows,'moc_fild01.gat')
    assert active['kite'] and not active['auto_attacks'] and p
    assert active['patrol']==base['patrol']
    assert base==DEFAULTS
    assert m.effective(base,rows,'other')[0]==base
    assert m.effective(base,rows,'moc_fild01',True)==(base,None)
    rows[0]['enabled']=False
    assert m.effective(base,rows,'moc_fild01')==(base,None)

def test_duplicate_map_rejected(tmp_path):
    with pytest.raises(ValueError):m.save([profile(kite=True),profile(kite=False)],tmp_path/'x.json')

def test_relay_applies_once_restores_and_suspends_for_quest(monkeypatch):
    from types import SimpleNamespace
    from nrobot.session_relay import SessionRelay
    rows=[m.validate(profile(kite=True))]
    monkeypatch.setattr(m,'load',lambda:rows)
    calls=[]
    relay=SimpleNamespace(hunt=object(),map_behavior_base=copy.deepcopy(DEFAULTS),
        tracker=SimpleNamespace(observer=SimpleNamespace(map_name='moc_fild01.gat')),
        quests=SimpleNamespace(active=False),apply_settings=lambda settings,**kw:calls.append(settings))
    SessionRelay.sync_map_behavior(relay)
    assert calls[-1]['kite']
    relay.map_behavior_poll=0
    SessionRelay.sync_map_behavior(relay)
    assert len(calls)==1
    relay.quests.active=True
    relay.map_behavior_poll=0
    SessionRelay.sync_map_behavior(relay)
    assert calls[-1]==DEFAULTS and relay.quest_hunt_id is None
    relay.quests.active=False
    relay.map_behavior_poll=0
    SessionRelay.sync_map_behavior(relay)
    assert calls[-1]['kite']
    relay.tracker.observer.map_name='other'
    relay.map_behavior_poll=0
    SessionRelay.sync_map_behavior(relay)
    assert calls[-1]==DEFAULTS


def test_database_hunt_keeps_map_combat_profile_only_during_hunt(monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from nrobot.session_relay import SessionRelay
    example=Path('exemplos/comportamentos/ra_fild03.json')
    rows=[m.validate(json.loads(example.read_text(encoding='utf-8')))]
    monkeypatch.setattr(m,'load',lambda:rows)
    calls=[]
    relay=SimpleNamespace(hunt=SimpleNamespace(priority_target=1,target_priority={}),
        map_behavior_base=copy.deepcopy(DEFAULTS),map_behavior_poll=0,map_behavior_signature=None,
        map_behavior_effective=None,quest_hunt_id=1,group_follower=lambda:False,player_focus=lambda:False,
        tracker=SimpleNamespace(observer=SimpleNamespace(map_name='ra_fild03.gat',skills={})),
        quests=SimpleNamespace(active=True,phase='hunt',route={'id':'database_hunt'}),
        apply_settings=lambda settings,**kw:calls.append(settings))
    SessionRelay.sync_map_behavior(relay)
    assert relay.map_combat is not None and relay.map_combat_map=='ra_fild03'
    assert calls[-1]['skill_burst'] and calls[-1]['skill_burst_interval']==.05
    relay.quests.phase='travel';relay.map_behavior_poll=0
    SessionRelay.sync_map_behavior(relay)
    assert relay.map_combat is None and calls[-1]==DEFAULTS



def test_quest_hunt_apply_is_not_reapplied_by_map_behavior(monkeypatch):
    """Quest hunt applies its settings; the map behavior (no profile) must not re-apply them and reset
    the quest hunt, which applied again every 0.5 s (lag, skills delayed)."""
    from types import SimpleNamespace
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(m,'load',lambda:[])
    calls=[]
    relay=SimpleNamespace(hunt=SimpleNamespace(priority_target=None,target_priority={}),quest_hunt_id=('q',),
        group_follower=lambda:False,player_focus=lambda:False,
        tracker=SimpleNamespace(observer=SimpleNamespace(map_name='ra_fild03.gat',skills={})),
        quests=SimpleNamespace(active=True,phase='hunt',route={'id':'quest'}),
        apply_settings=lambda settings,**kw:calls.append(settings))
    settings=copy.deepcopy(DEFAULTS);settings['kite']=not settings['kite']
    # what SessionRelay.apply_settings leaves behind for a normal (non overlay) apply
    relay.map_behavior_base=copy.deepcopy(settings);relay.map_behavior_signature=None
    relay.map_behavior_effective=copy.deepcopy(settings);relay.map_behavior_poll=0
    SessionRelay.sync_map_behavior(relay)
    assert calls==[] and relay.quest_hunt_id==('q',)
