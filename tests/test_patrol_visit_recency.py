from nrobot.packet_patrol import PacketPatrol
from nrobot.map_navigation import CollisionMap


def test_repeated_routes_choose_older_branch_with_same_length():
    c=CollisionMap(40,32,[int(not(16<=x<=23 and 10<=y<=21)) for y in range(32) for x in range(40)])
    p=PacketPatrol()
    baseline=p.route(c,[8,16],[32,16],exact=True,wall_cost=0,greed=1)
    bottom=max(y for x,y in baseline)>=22
    for y in range(8):
        for x in range(10):p.last_passage[x,y]=100
    for sector in p.last_passage:
        if (sector[1]<4 if bottom else sector[1]>=5):p.last_passage[sector]=1
    chosen=p.route(c,[8,16],[32,16],exact=True,wall_cost=0,greed=1)
    assert len(chosen)==len(baseline)
    assert (min(y for x,y in chosen)<=9) if bottom else (max(y for x,y in chosen)>=22)
    assert all(c.edge(a,b) for a,b in zip(chosen,chosen[1:]))


def test_passing_near_waypoint_counts_even_when_goal_is_elsewhere():
    c=CollisionMap(80,80,[1]*6400);c.name='field.gat'
    p=PacketPatrol();p.switch_map(c,[10,10])
    block=min(p.remaining,key=lambda b:abs(p.tour.points[b][0]-35)+abs(p.tour.points[b][1]-35))
    point=p.tour.points[block]
    p.goal=(65,65)
    p.observe_position([point[0],point[1]-4],100,'field.gat')
    assert block in p.done and block not in p.remaining
    assert p.goal==(65,65)
    assert p.last_passage[(point[0]//4,(point[1]-4)//4)]==100


def test_observations_do_not_mark_between_teleports_or_in_other_map():
    c=CollisionMap(100,100,[1]*10000);c.name='field.gat'
    p=PacketPatrol();p.switch_map(c,[10,10])
    p.observe_position([10,10],100,'field.gat')
    p.observe_position([80,80],110,'field.gat')
    assert (12,12) not in p.last_passage  # no imaginary crossing through [50,50]
    before=set(p.done)
    p.observe_position([50,50],120,'other.gat')
    assert p.done==before


def test_proximity_does_not_explore_waypoint_across_wall():
    c=CollisionMap(80,80,[int(x!=39 or y==70) for y in range(80) for x in range(80)])
    p=PacketPatrol();p.switch_map(c,[35,30])
    for block in p.tour.seen_from([35,30]):
        assert p.tour.points[block][0]<39
