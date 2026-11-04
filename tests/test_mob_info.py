import struct

from nrobot import drop_db, mob_info
from nrobot.packet_reader import server_text
from nrobot.mob_info import MobInfoQueue, chat_command, parse

RATHENA = [
    "Monster: 'Poring'/'Poring'/'Poring' (1002)",
    ' Lv:1  HP:50  Base EXP:2  Job EXP:1  HIT:202  FLEE:154',
    ' DEF:0  MDEF:5  STR:1  AGI:1  VIT:1  INT:0  DEX:6  LUK:30',
    ' ATK:7~10  Range:1~10~12  Size:Medium  Race: Plant  Element: Water (Lv:1)',
    ' Drops:',
    ' - Jellopy  70.00% - Knife [3]  1.00% - Sticky Mucus  4.00%',
    ' - Apple  10.00% - Poring Card  0.01%',
    ' MVP Bonus EXP:0',
    ' MVP Items:',
    ' - Old Card Album  0,50%',
]


def test_parses_rathena_sheet_with_rare_and_mvp_items(monkeypatch):
    monkeypatch.setattr(drop_db, 'item_names', lambda: {909: 'Jellopy', 1201: 'Knife', 4001: 'Poring Card'})
    info = parse(1002, RATHENA)
    assert info['name'] == 'Poring'
    assert [(d['item_id'], d['item_name'], d['rate']) for d in info['drops']] == [
        (909, 'Jellopy', 70.0), (1201, 'Knife', 1.0), (0, 'Sticky Mucus', 4.0), (0, 'Apple', 10.0), (4001, 'Poring Card', .01)]
    assert [(d['item_name'], d['rate']) for d in info['mvp']] == [('Old Card Album', .5)]


def test_item_links_carry_the_item_id(monkeypatch):
    monkeypatch.setattr(drop_db, 'item_names', lambda: {909: 'Jellopy'})
    # rAthena <ITEML>: 5 chars equip location, equip flag, base62 item id (909 = "eF")
    info = parse(1002, ["Monstro: 'Poring' (1002)", ' Drops:', ' - <ITEML>000000eF</ITEML>  70.00% - Faca (1201)  1.00%'])
    assert [(d['item_id'], d['item_name']) for d in info['drops']] == [(909, 'Jellopy'), (1201, 'Faca')]


def test_other_answers_are_not_a_sheet():
    assert parse(1002, ['Comando desconhecido.']) is None
    assert parse(1002, []) is None


def test_chat_frame_and_server_lines(monkeypatch):
    import time
    from nrobot import packet_reader
    frame = chat_command('@mi 1002', 'Naruto')
    assert struct.unpack_from('<HH', frame) == (0xf3, len(frame))
    assert frame[4:] == b'Naruto : @mi 1002\0'
    assert server_text(0x8e, ' - Jellopy  70.00%')['kind'] == 'other'  # nothing kept without a pending @mi
    monkeypatch.setattr(packet_reader, 'SERVER_TEXT_UNTIL', time.monotonic()+5)
    assert server_text(0x8e, ' - Jellopy  70.00%') == {'kind': 'server_text', 'text': ' - Jellopy  70.00%'}
    assert server_text(0x8e, 'Fulano : oi')['kind'] == 'other'  # someone's chat is never kept
    assert server_text(0x9a, 'broadcast')['kind'] == 'other'


def test_queue_asks_each_species_once_and_stops_after_failures():
    q = MobInfoQueue(known={1113})
    assert not q.want(1113) and q.want(1002) and not q.want(1002)
    assert q.due(0) == 1002
    q.sent(1002, 0)
    assert q.due(10) is None  # waiting for the answer
    q.observe([{'kind': 'server_text', 'text': line} for line in RATHENA], 0.1)
    q.observe([], 2.0)
    species, info, lines = q.results.pop()
    assert species == 1002 and info['name'] == 'Poring' and 1002 in q.known
    for species in (1003, 1004):
        q.want(species); q.sent(species, 0); q.observe([], 10)
    assert q.suspended and not q.want(1005)
    assert q.want(1005, force=True)  # the panel button still asks


def test_database_keeps_server_drops(tmp_path, monkeypatch):
    monkeypatch.setattr(drop_db, 'item_names', lambda: {909: 'Jellopy'})
    path = tmp_path/'db.sqlite3'
    info = parse(1002, RATHENA)
    drop_db.save_mob_info(1002, info, RATHENA, path)
    drop_db.save_mob_info(1002, info, RATHENA, path)  # a new answer replaces the old one
    rows = drop_db.server_drops(path=path)
    assert len(rows) == 6 and rows[0]['monster_name'] == 'Poring' and rows[0]['item_name'] == 'Jellopy'
    assert [r['item_name'] for r in drop_db.server_drops('card', path=path)] == ['Poring Card', 'Old Card Album']
    assert drop_db.mob_info_species(path) == {1002}
    assert drop_db.server_drops(species=1113, path=path) == []


def test_base62():
    assert mob_info.base62('eF') == 909


def test_relay_sends_mi_and_saves_the_answer(tmp_path, monkeypatch):
    import asyncio
    import time
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(drop_db, 'FILE', tmp_path/'db.sqlite3')
    monkeypatch.setattr(drop_db, 'item_names', lambda: {909: 'Jellopy'})

    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
        relay.own_look, relay.login_phase = {'name': 'Naruto'}, 'map'
        relay.native_frames._fallback = {0xf3: -1}

        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        relay.mob_info.want(1002, force=True)
        await relay.send_mob_info(game_gate=lambda: True)
        assert relay.upstream.packets == [chat_command('@mi 1002', 'Naruto')]
        await relay.send_mob_info(game_gate=lambda: True)
        assert len(relay.upstream.packets) == 1  # one command at a time
        for line in RATHENA:
            body = line.encode('cp1252')+b'\0'
            relay.mirror_map(struct.pack('<HH', 0x8e, 4+len(body))+body)
        relay.mob_info_observe([], time.monotonic()+2)
    asyncio.run(scenario())
    rows = drop_db.server_drops()
    assert rows[0]['item_id'] == 909 and rows[0]['rate'] == 70.0 and len(rows) == 6
    assert (tmp_path/'respostas_mi.jsonl').is_file()
