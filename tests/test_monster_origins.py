from nrobot import monster_db
from nrobot.entity_inventory import EntityInventory
from nrobot.map_monsters import confirmed_types, is_confirmed_monster


def test_false_hospital_spawns_and_ninkame_map_are_suppressed_in_old_data(monkeypatch):
    old = {1031: {'name': 'Mula sem Cabesa', 'maps': {'hospital2': 1, 'moc_fild13': 3}},
           1188: {'name': 'Tronco de madeira', 'maps': {'hospital2': 3, 'kakashi': 2},
                  'names_by_map': {'hospital2': ['Tronco de madeira']}},
           1315: {'name': 'Ninkame', 'maps': {'tur_dun03': 5, 'ra_fild03': 2},
                  'names_by_map': {'tur_dun03': ['Ninkame'], 'ra_fild03': ['Ninkame']}}}
    monkeypatch.setattr(monster_db, 'load_base', lambda: old)
    monkeypatch.setattr(monster_db, 'catalog', lambda: {
        1315: {'maps': ['tur_dun03']}, 1031: {'maps': ['hospital2']}, 1188: {'maps': ['hospital2']}})
    assert monster_db.monsters_of_map('hospital2.gat', captured=old) == []
    assert monster_db.monsters_of_map('tur_dun03.gat', captured=old) == []
    assert monster_db.maps_for_name('Ninkame', captured=old) == {'ra_fild03'}
    assert monster_db.names_for_map('hospital2.gat', captured=old) == {}
    assert monster_db.monsters_of_map('moc_fild13.gat', captured=old) == [1031]


def test_trunk_is_visible_as_a_note_but_never_a_target_or_spawn():
    inventory = EntityInventory()
    inventory.reset('hospital2.gat')
    inventory.observe([dict(kind='appearance', entity_id=110000001, species_id=1188,
                            object_type=5, position=[10, 10]),
                       dict(kind='name', entity_id=110000001, name='Tronco de madeira', hp=100, max_hp=100)], 1)
    assert not is_confirmed_monster(inventory.entities[110000001])
    assert confirmed_types(inventory) == {}
    assert 'hide' in inventory.snapshot(2)['entities'][0]['origin_note']
    records = {}
    assert not monster_db.record(records, 1188, 'hospital2', name='Tronco de madeira', max_hp=100)
    assert records == {}


def test_confirmed_summon_ownership_survives_repeated_appearance_and_cannot_be_learned():
    inventory = EntityInventory()
    event = dict(kind='appearance', entity_id=110000002, species_id=1031, object_type=5, position=[10, 10])
    inventory.observe([dict(event, owner_id=2000001, summoned=True), event,
                       dict(kind='name', entity_id=110000002, name='Mula', hp=100, max_hp=100)], 1)
    entity = inventory.entities[110000002]
    assert entity['owner_id'] == 2000001 and entity['summoned']
    assert not is_confirmed_monster(entity)
    assert not monster_db.record({}, 1031, 'field', name='Mula', owner_id=entity['owner_id'])
    inventory.reset('field')
    inventory.observe([event], 2)
    assert not inventory.entities[110000002]['owner_id']


