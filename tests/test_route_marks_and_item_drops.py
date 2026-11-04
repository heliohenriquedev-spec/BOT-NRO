from datetime import date

from nrobot import drop_db, quest_daily
from nrobot.mob_info import parse
from nrobot.quest_panel import route_done_today


def test_route_is_done_today_only_when_every_mission_was_delivered_today():
    missions = [dict(id='a', board_id='kakashi', name='Rank B-1'), dict(id='b', board_id='kakashi', name='Rank B-2')]
    route = dict(mission_ids=['a', 'b'])
    today = date.today().isoformat()
    assert route_done_today(route, missions, {}) == (0, 2)
    assert route_done_today(route, missions, {quest_daily.key('kakashi', 'Rank B-1'): today}) == (1, 2)
    both = {quest_daily.key('kakashi', 'Rank B-1'): today, quest_daily.key('kakashi', 'Rank B-2'): today}
    assert route_done_today(route, missions, both) == (2, 2)
    assert route_done_today(route, missions, {k: '2000-01-01' for k in both}) == (0, 2)  # another day


def test_items_list_their_monsters_by_highest_chance(tmp_path, monkeypatch):
    monkeypatch.setattr(drop_db, 'item_names', lambda: {909: 'Jellopy', 4001: 'Poring Card'})
    path = tmp_path/'db.sqlite3'
    drop_db.save_mob_info(1002, parse(1002, ["Monster: 'Poring' (1002)", ' Drops:',
                                             ' - Jellopy (909)  70.00% - Poring Card (4001)  0.01%']), [], path)
    drop_db.save_mob_info(1113, parse(1113, ["Monster: 'Drops' (1113)", ' Drops:', ' - Jellopy (909)  80.00%']), [], path)
    items = drop_db.item_overview(path=path)
    jellopy = next(i for i in items if i['item_id'] == 909)
    assert [(s['species_id'], s['rate']) for s in jellopy['sources']] == [(1113, 80.0), (1002, 70.0)]
    assert items[0]['item_id'] == 909  # items sorted by their best chance
    assert [i['item_id'] for i in drop_db.item_overview('drops', path=path)] == [909]  # search by monster
    assert [i['item_id'] for i in drop_db.item_overview(species=1002, path=path)] == [909, 4001]
    assert drop_db.data_stamp(path)[0] is not None
