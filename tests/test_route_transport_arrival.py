from nrobot.npc_transports import harmful, purge
from nrobot.quest_navigation import TravelCost


def test_transport_arrival_prices_the_walk_after_it():
    costs = TravelCost()
    leg = [dict(kind='npc', map='a.gat', position=[10, 10]), dict(kind='wait_map', map='b.gat', arrival=[100, 100]),
           dict(kind='portal', map='b.gat', position=[100, 5])]
    cost, position, here = costs.leg('a', [10, 10], leg)
    assert here == 'b' and position == (100, 5) and cost >= 95  # not the 32 of an unknown landing


def test_giving_up_a_mission_is_never_a_transport():
    steps = [dict(kind='npc', position=[87, 140]), dict(kind='select', option='Desistir de uma missão'),
             dict(kind='select', option='Sim'), dict(kind='wait_map', map='hospital2.gat')]
    assert harmful(steps)
    known = {'kakashi': {'87,140>hospital2>x': dict(steps=steps, to='hospital2'),
                         '83,150>hospital2>Sim': dict(steps=[dict(kind='npc', position=[83, 150])], to='hospital2')}}
    assert purge(known) and list(known['kakashi']) == ['83,150>hospital2>Sim']
