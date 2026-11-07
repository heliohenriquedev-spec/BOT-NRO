from nrobot.quest_navigation import closest_connection
from nrobot.map_navigation import CollisionMap
from nrobot.quest_routes import QuestRoutes


def leg(origin,point,target):
    return [dict(kind='portal',map=origin,position=point),dict(kind='wait_map',map=target)]


def test_nearby_two_hop_path_beats_distant_direct_portal():
    edges={'home':[('target',leg('home',[90,90],'target')),('mid',leg('home',[12,10],'mid'))],
           'mid':[('target',leg('mid',[11,10],'target'))]}
    destinations={'home':{'12,10':dict(map='mid',arrival=[10,10])}}
    steps=closest_connection(edges,'home','target',[10,10],destinations=destinations)
    assert steps[0]['position']==[12,10]
    assert [s['map'] for s in steps if s['kind']=='wait_map']==['mid','target']


def test_distinct_arrivals_on_same_map_are_compared_to_next_portal():
    edges={'home':[('mid',leg('home',[1,0],'mid')),('mid',leg('home',[4,0],'mid'))],
           'mid':[('target',leg('mid',[11,10],'target'))]}
    destinations={'home':{'1,0':dict(map='mid',arrival=[90,90]),'4,0':dict(map='mid',arrival=[10,10])}}
    assert closest_connection(edges,'home','target',[0,0],destinations=destinations)[0]['position']==[4,0]


def test_real_walk_around_wall_is_used_instead_of_straight_distance():
    collision=CollisionMap(40,40,[int(x!=20 or y>=32) for y in range(40) for x in range(40)])
    edges={'home':[('target',leg('home',[25,5],'target')),('target',leg('home',[5,15],'target'))]}
    steps=closest_connection(edges,'home','target',[15,5],collision=lambda name:collision)
    assert steps[0]['position']==[5,15]


def test_quest_chooses_shorter_known_route_instead_of_its_saved_path():
    q=QuestRoutes()
    fixed=leg('home',[90,90],'target')
    q.start([dict(id='R',name='Quest',enabled=True,kills=50,species=[1037],target_map='target',steps=fixed)],0)
    q.learned_portals={'home':{'12,10':dict(map='mid',arrival=[10,10],confirmed=True)},
                       'mid':{'11,10':dict(map='target',arrival=[10,10],confirmed=True)}}
    q.route_position=[10,10];q.route_position_map='home'
    result=q.itinerary('home')
    assert result[0]['position']==[12,10]
    assert q.route['steps']==fixed  # recordings remain available as known connections


def test_final_npc_approach_is_part_of_route_comparison():
    edges={'home':[('target',leg('home',[1,0],'target')),('target',leg('home',[5,0],'target'))]}
    destinations={'home':{'1,0':dict(map='target',arrival=[90,90]),'5,0':dict(map='target',arrival=[10,10])}}
    result=closest_connection(edges,'home','target',[0,0],target_position=[12,10],destinations=destinations)
    assert result[0]['position']==[5,0]
