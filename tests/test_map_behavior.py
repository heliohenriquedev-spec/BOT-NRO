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

