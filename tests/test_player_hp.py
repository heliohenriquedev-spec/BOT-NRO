import struct

from nrobot.packet_reader import decode,message_length
from nrobot.player_hp import PlayerHp


def test_legacy_hp_bar_keeps_scaled_values_separate_from_absolute_hp():
    raw=struct.pack('<HIHH',0x106,2000001,73,100)
    assert message_length(raw)==10
    event=decode(raw)
    assert event['kind']=='actor_hp_bar' and event['entity_id']==2000001
    assert event['hp_percent']==73 and not event['absolute_hp_confirmed']
    assert 'hp' not in event and 'max_hp' not in event


def test_battlefield_bar_layout_and_invalid_ratio():
    name=b'Test'+bytes(20)
    event=decode(struct.pack('<HI',0x2e0,2000001)+name+struct.pack('<HH',12,40))
    assert event['name']=='Test' and event['hp_percent']==30
    assert decode(struct.pack('<HIHH',0x106,2000001,200,100))['hp_percent'] is None
    assert decode(struct.pack('<HIHH',0x106,2000001,0,0))['hp_percent'] is None


def test_passive_evidence_tracks_players_outside_guild_without_inventing_hp():
    hp=PlayerHp()
    hp.observe([decode(struct.pack('<HIHH',0x106,i,50,100)) for i in (2000001,2000002)],'hospital2',100)
    records={'2000001':{'name':'Ally','guild':'Guild A','party':'Party A'},
             '2000002':{'name':'Other','guild':'Guild B'}}
    rows=hp.snapshot(2000000,records,{'guild':'Guild A','party':'Party A'},105)
    assert len(rows)==2 and all(r['recent'] and r['age_seconds']==5 for r in rows)
    assert rows[1]['guild_received']=='Guild B'
    assert all(not r['absolute_hp_confirmed'] for r in rows)
    assert all(not r['recent'] for r in hp.snapshot(2000000,records,{},120))
    hp.observe([{'kind':'map_change','map':'field'}],'field',121)
    assert not hp.snapshot(2000000,records,{},121)


def test_relay_status_publishes_passive_hp_diagnostic(tmp_path):
    from test_bg_entry import relay
    r=relay(tmp_path)
    r.received_player_hp.observe([decode(struct.pack('<HIHH',0x106,2000001,25,100))],'hospital2')
    result=r.status()
    assert result['received_player_hp'][0]['hp_percent']==25
    assert (tmp_path/'hp_recebido.json').exists()
