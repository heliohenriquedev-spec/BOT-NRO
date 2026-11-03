import asyncio
import struct
import time

from nrobot.entity_inventory import EntityInventory
from nrobot.map_monsters import confirmed_types
from nrobot.packet_hunt import PacketHunt
from nrobot.packet_settings import DEFAULTS
from nrobot.session_relay import SessionRelay


def appearance(identity, species):
    return {'kind':'appearance','entity_id':identity,'species_id':species,
            'position':[10,10], 'object_type':0, 'walk_speed_ms':200}


def test_discovery_does_not_classify_npc_or_self_as_monster(monkeypatch):
    monkeypatch.setattr('nrobot.map_monsters.monster_assets',lambda:{2000:'local',2001:'other'})
    inventory=EntityInventory()
    inventory.observe([appearance(20,2000),appearance(21,706),appearance(1,2001)],0)
    inventory.observe([{'kind':'name','entity_id':20,'name':'Monstro NRO','hp':100,'max_hp':100},
                       {'kind':'name','entity_id':21,'name':'NPC'},
                       {'kind':'name','entity_id':1,'name':'Self','hp':100,'max_hp':100}],1)
    assert set(confirmed_types(inventory,1))=={2000}


def test_new_map_species_enters_active_hunt_without_pausing(tmp_path,monkeypatch):
    monkeypatch.setattr('nrobot.map_monsters.monster_assets',lambda:{2000:'local'})
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt()
    relay.apply_settings({**DEFAULTS,'species':[], 'auto_map_targets':True})
    relay.hunt.start()
    relay.inventory.observe([appearance(20,2000)],time.monotonic())
    relay.sync_map_monsters()
    assert 2000 not in relay.tracker.observer.species
    relay.inventory.observe([{'kind':'name','entity_id':20,'name':'Novo Monstro','hp':30,'max_hp':30}],time.monotonic())
    relay.sync_map_monsters()
    assert relay.hunt.enabled
    assert 2000 in relay.tracker.observer.species and 20 in relay.tracker.observer.registry.entities
    relay.inventory.reset('new.gat')
    relay.sync_map_monsters()
    assert not relay.tracker.observer.species and not relay.discovered_monsters


def test_discovery_is_passive_and_does_not_write_unvalidated_queries(tmp_path,monkeypatch):
    monkeypatch.setattr('nrobot.map_monsters.monster_assets',lambda:{2000:'local'})
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt();relay.apply_settings(DEFAULTS)
    class Writer:
        def write(self,data):raise AssertionError('Discovery must not write packets')
    relay.upstream=Writer()
    relay.inventory.observe([appearance(20,2000)],time.monotonic())
    for _ in range(5):relay.sync_map_monsters();relay.status()
    assert not hasattr(relay,'discover_map_monsters')


def test_custom_monster_outside_client_catalog_is_discovered_by_server_hp(monkeypatch):
    """REDE-63: e.g. 'Boneco de Treino', whose sprite is not a catalog monster."""
    monkeypatch.setattr('nrobot.map_monsters.monster_assets',lambda:{})
    inventory=EntityInventory()
    inventory.observe([appearance(110829500,739),appearance(2003137,1037)],0)
    inventory.observe([{'kind':'name','entity_id':110829500,'name':'Boneco de Treino','hp':4294967295,'max_hp':429496729},
                       {'kind':'name','entity_id':2003137,'name':'Jogador','hp':10,'max_hp':10}],1)
    found=confirmed_types(inventory,1)
    assert set(found)=={739} and found[739]['name']=='Boneco de Treino'
    assert 'fora do catalogo' in found[739]['evidence']


def test_truncated_training_dummy_hp_is_read():
    import struct
    from nrobot.packet_reader import decode
    message = struct.pack('<HI', 0x195, 110830885)+b'Boneco de Treino'.ljust(24, b'\0')
    message += b'(HP: 4294967295/42949672'+bytes(102-54)
    event = decode(message)
    assert event['name'] == 'Boneco de Treino' and event['hp'] == event['max_hp'] == 4294967295
    closed = struct.pack('<HI', 0x195, 7)+b'X'.ljust(24, b'\0')+b'HP: 50/40)'.ljust(24, b'\0')+bytes(48)
    assert 'hp' not in decode(closed)  # complete but inconsistent values stay rejected


def test_discovery_rejects_disguises_summons_and_known_players():
    inventory = EntityInventory()
    entities = [
        appearance((-2002551) & 0xffffffff, 1772),
        {**appearance(110000002, 1031), 'owner_id': 2002551},
        {**appearance(110000003, 1031), 'summoned': True},
        appearance(110000004, 1772),
        appearance(110000005, 1034),
    ]
    inventory.observe(entities, 0)
    inventory.observe([
        {'kind': 'name', 'entity_id': row['entity_id'], 'name': name, 'max_hp': 50}
        for row, name in zip(entities, ('Disfarce', 'Namekuji', 'Namekuji', 'Barra Mal', 'Girino'))
    ], 1)
    assert set(confirmed_types(inventory)) == {1034}


def test_missing_collision_starts_stationary_without_disabling_setting(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt()
    relay.apply_settings(DEFAULTS)
    relay.tracker.observer.map_name = 'kakashi.gat'
    relay.validate_navigation_start()
    assert relay.navigation_stationary and not relay.hunt.auto_movement
    assert relay.settings['auto_movement']
