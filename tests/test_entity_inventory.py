from nrobot.entity_inventory import EntityInventory


def test_inventory_collects_all_species_and_keeps_old_sightings_separate_from_targets():
    inventory = EntityInventory({'1037': 'Filhote de cobra'})
    inventory.reset('moc_fild01.gat')
    inventory.observe([{'kind': 'appearance', 'entity_id': 1, 'species_id': 1037, 'position': [290, 295]},
                       {'kind': 'appearance', 'entity_id': 2, 'species_id': 9999, 'position': [1, 2]}], 0)
    inventory.observe([{'kind': 'move', 'entity_id': 1, 'position': [289, 295], 'destination': [288, 295]},
                       {'kind': 'name', 'entity_id': 1, 'name': 'Filhote', 'hp': 100, 'max_hp': 200},
                       {'kind': 'remove', 'entity_id': 1, 'reason': 0}], 1)
    result = inventory.snapshot(20)
    assert len(result['entities']) == 2
    first, second = result['entities']
    assert first['correlated_name'] == 'Filhote de cobra' and first['hp'] == 100
    assert first['destination'] == [288, 295] and first['movements'] == 1
    assert first['position_age_seconds'] == 19 and not first['present_last_observation']
    assert second['correlated_name'] is None
    inventory.observe([{'kind': 'map_change', 'map': 'other.gat'}], 21)
    assert inventory.snapshot(22)['entities'] == []
