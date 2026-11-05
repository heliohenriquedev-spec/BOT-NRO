"""Fresh install in a different folder/drive and initial character data lifecycle."""
import hashlib
import json
from pathlib import Path
import struct

import pytest
from nrobot import packet_reader, game_folder, runtime_check
from nrobot.network_observer import LiveStream
from nrobot.continuous_observer import ContinuousTracker
from nrobot.network_targets import Entity
from nrobot.session_relay import SessionRelay


@pytest.fixture
def portable_client(tmp_path,monkeypatch):
    folder=tmp_path/'outro disco'/'NRO Jogo'
    folder.mkdir(parents=True)
    exe=folder/'NRO.exe';exe.write_bytes(b'unit test compatible executable')
    table=tmp_path/'tamanhos_cliente.json'
    table.write_text(json.dumps({'source_executable':str(tmp_path/'maquina autor'/'NRO.exe'),
        'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
        'entries':{'010F':{'length':-1},'0283':{'length':6},'00BD':{'length':44}}}))
    monkeypatch.setattr(packet_reader,'CLIENT_LENGTHS_FILE',table)
    monkeypatch.setattr(packet_reader,'CLIENT_GAME_DIR',None)
    monkeypatch.setattr(game_folder,'saved',lambda:folder)
    monkeypatch.setattr(game_folder,'find',lambda:folder)
    packet_reader.client_lengths.cache_clear()
    yield folder,table
    packet_reader.client_lengths.cache_clear()


def skill_packet():
    entry=struct.pack('<HIHHH24sB',524,1,10,20,6,b'Kunai',0)
    return struct.pack('<HH',0x10f,4+len(entry))+entry


def initial_data():
    return struct.pack('<HI',0x283,2003143)+skill_packet()+struct.pack('<HHI',0xb1,7,1234)


def test_packet_table_uses_users_selected_folder_not_authors_path(portable_client):
    folder,table=portable_client
    assert not Path(json.loads(table.read_text())['source_executable']).exists()
    assert packet_reader.client_lengths()[0x10f]==-1
    t=ContinuousTracker({1037},player_ttl=None,idle_timeout=None,entity_ttl=None)
    t.feed(0,initial_data(),0)
    assert t.observer.skills[524]['level']==10
    assert t.observer.skills_received and t.observer.sp==1234 and t.observer.player_id==2003143


def test_client_hash_validation_is_still_required(portable_client):
    folder,_=portable_client
    (folder/'NRO.exe').write_bytes(b'incompatible executable')
    with pytest.raises(ValueError,match='incompativel'):
        packet_reader.client_lengths()


def test_explicitly_verified_visual_variant_is_accepted_but_unknown_change_is_not(portable_client):
    folder, table = portable_client
    variant = b'known client with independently verified visual-only changes'
    data = json.loads(table.read_text())
    data['compatible_executables'] = [{'sha256': hashlib.sha256(variant).hexdigest(),
                                      'description': 'verified visual variant'}]
    table.write_text(json.dumps(data))
    (folder/'NRO.exe').write_bytes(variant)
    assert packet_reader.client_lengths()[0x10f] == -1
    packet_reader.client_lengths.cache_clear()
    (folder/'NRO.exe').write_bytes(variant+b'unknown modification')
    with pytest.raises(ValueError, match='incompativel'):
        packet_reader.client_lengths()


def test_installer_preflight_checks_actual_game_folder(portable_client,monkeypatch,capsys):
    monkeypatch.setattr(runtime_check,'check_runtime',lambda:None)
    assert runtime_check.main(['--game'])==0
    assert str(portable_client[0]) in capsys.readouterr().out
    (portable_client[0]/'NRO.exe').write_bytes(b'wrong version')
    packet_reader.client_lengths.cache_clear()
    assert runtime_check.main(['--game'])==1
    assert 'incompativel' in capsys.readouterr().err


def test_valid_initial_data_is_not_discarded_due_to_unknown_message_after_it(portable_client):
    t=ContinuousTracker({1037},player_ttl=None,idle_timeout=None,entity_ttl=None)
    events=t.feed(0,initial_data()+b'\xfe\x7f\x01\x02',0)
    assert t.observer.skills_received and t.observer.sp==1234
    assert [e['kind'] for e in events]==['own_identity','skills_info','player_stat','stream_resync']
    assert events[-1]['dropped']==4


def test_unknown_prefix_does_not_turn_embedded_bytes_into_fake_skills(portable_client):
    t=ContinuousTracker({1037},player_ttl=None,idle_timeout=None,entity_ttl=None)
    events=t.feed(0,b'\xfe\x7f\x01\x02'+initial_data(),0)
    assert [e['kind'] for e in events]==['stream_resync']
    assert not t.observer.skills and t.observer.sp is None


def test_map_reconnect_keeps_character_data_but_replaces_map_entities(tmp_path):
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    r.account=struct.pack('<I',2003143);r.select_character(100)
    o=r.tracker.observer
    o.skills={524:dict(skill_id=524,level=10)};o.skills_received=True;o.sp=1234
    o.effects={12:True};o.hotkeys={1:dict(id=524)};o.walk_speed_ms=150
    o.registry.update(Entity(111000001,1051,10,10,0,'monster'))
    kept=o.keep_character();o.clear();o.restore_character(kept)  # old map socket closed
    r.next_map='hospital2.gat';r.begin_map_observation()
    n=r.tracker.observer
    assert n is not o and n.skills_received and n.skills[524]['level']==10 and n.sp==1234
    assert n.effects=={12:True} and n.hotkeys[1]['id']==524 and n.walk_speed_ms==150
    assert n.player_id==2003143 and n.map_name=='hospital2.gat' and not n.registry.entities


def test_selecting_another_character_never_reuses_old_skills_or_sp(tmp_path):
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    r.select_character(100);o=r.tracker.observer
    o.skills={524:dict(skill_id=524,level=10)};o.skills_received=True;o.sp=1234
    r.select_character(100)
    assert o.sp==1234 and o.skills_received
    r.select_character(101)
    assert not o.skills and not o.skills_received and o.sp is None


def test_sp_and_skills_survive_position_initialization_after_login(portable_client):
    t=ContinuousTracker({1037},player_ttl=None,idle_timeout=None,entity_ttl=None)
    auth=struct.pack('<HI',0x73,0)+bytes([2,128,160,0,0])
    t.feed(0,initial_data()+auth,0)
    assert t.observer.player==[10,10] and t.observer.player_id==2003143
    assert t.observer.skills_received and t.observer.sp==1234
