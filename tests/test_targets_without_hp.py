"""Monsters whose name reply comes without "HP: x/y" are still hunted (seen on other PCs)."""
from nrobot.map_monsters import is_confirmed_monster
from nrobot.monster_db import monster_choice_key


def test_a_named_monster_sprite_is_a_monster_even_without_hp():
    assert is_confirmed_monster(dict(entity_id=111411301, species_id=1139, name='Louva-a-Deus', object_type_raw=0))
    assert not is_confirmed_monster(dict(entity_id=111411302, species_id=1139, object_type_raw=0))  # name still unknown
    assert not is_confirmed_monster(dict(entity_id=111411303, species_id=111, name='Kafra', object_type_raw=0))  # NPC sprite


def relay_on(tmp_path, choices, entity):
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path)
    r.tracker.observer.map_name = 'anthell02.gat'
    r.settings = dict(monster_name_choices=choices, species=[1139], auto_map_targets=False)
    r.inventory.entities[entity['entity_id']] = entity
    return r


def test_only_an_unchecked_name_restricts_a_sprite(tmp_path):
    louva = dict(entity_id=111411301, species_id=1139, object_type_raw=0)  # name and HP not received yet
    checked = {monster_choice_key('anthell02.gat', 1139, 'Louva-a-Deus'): True}
    assert relay_on(tmp_path, checked, louva).monster_name_allowed(111411301, 1139)
    mixed = dict(checked, **{monster_choice_key('anthell02.gat', 1139, 'Outro'): False})
    r = relay_on(tmp_path, mixed, dict(louva))
    assert not r.monster_name_allowed(111411301, 1139)  # waits for the name
    r.inventory.entities[111411301]['name'] = 'Louva-a-Deus'
    assert r.monster_name_allowed(111411301, 1139)  # name enough, HP not needed
    r.inventory.entities[111411301]['name'] = 'Outro'
    assert not r.monster_name_allowed(111411301, 1139)
