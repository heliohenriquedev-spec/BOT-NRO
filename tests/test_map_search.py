from nrobot.entity_inventory import EntityInventory
from nrobot.map_navigation import CollisionMap
from nrobot.map_search import MapSearch
from nrobot.packet_hunt import PacketHunt


def sight(identity, position, species=1037):
    return {'kind': 'appearance', 'entity_id': identity, 'species_id': species, 'position': position}


def test_search_visits_known_targets_in_sequence_without_authorizing_attack():
    inventory = EntityInventory()
    collision = CollisionMap(80, 80, [1]*6400)
    inventory.observe([sight(20, [20,10]), sight(21, [50,10])], 0)
    search = MapSearch()
    goal = search.plan(inventory, [10,10], {1037}, 1, collision)
    assert goal['entity_id'] == 20
    assert search.plan(inventory, [20,10], {1037}, 2, collision)['entity_id'] == 21
    hunt = PacketHunt(patrol=True)
    hunt.start()
    action = hunt.plan({'state':'tracking', 'player_position_recent':True, 'player_position':[20,10],
                        'recent_entities':[], 'search_goal':search.goal}, 2, 100, collision)
    assert action['purpose'] == 'patrol' and action['target_id'] is None


def test_search_drops_dead_old_lost_and_other_map_information():
    inventory = EntityInventory()
    collision = CollisionMap(80, 80, [1]*6400)
    inventory.observe([sight(20,[20,10]), sight(21,[30,10]), sight(22,[40,10],1212)], 0)
    inventory.observe([{'kind':'remove','entity_id':20,'reason':1},
                       {'kind':'remove','entity_id':21,'reason':0}], 1)
    search = MapSearch()
    assert search.plan(inventory, [10,10], {1037}, 2, collision)['entity_id'] == 21
    assert search.plan(inventory, [10,10], {1037}, 62, collision) is None
    inventory.reset('other.gat')
    assert search.plan(inventory, [10,10], {1037}, 63, collision) is None
    assert search.summary['received_species_entities'] == 0


def test_visible_stationary_entity_remains_searchable_and_death_invalidates_cache():
    inventory = EntityInventory()
    collision = CollisionMap(80, 80, [1]*6400)
    inventory.observe([sight(20,[20,10])], 0)
    search = MapSearch()
    assert search.plan(inventory,[10,10],{1037},1000,collision)['entity_id'] == 20
    inventory.observe([{'kind':'remove','entity_id':20,'reason':1}],1000.1)
    assert search.plan(inventory,[10,10],{1037},1000.2,collision) is None
