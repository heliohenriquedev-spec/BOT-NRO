import struct

from nrobot import storage, packet_reader


CHAT = lambda text: text.encode()
OPEN = [{'kind': 'storage_opened', 'count': 0, 'capacity': 600}]


def make(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'BUNDLED_PATH', tmp_path/'pacotes.json')
    monkeypatch.setattr(storage, 'PATH', tmp_path/'armazem.json')
    monkeypatch.setattr(storage, 'CONTENT_PATH', tmp_path/'conteudo.json')
    return storage.Storage()


def store_frame(index, amount):
    return struct.pack('<H', 0x94a)+b'ab'+struct.pack('<H', index)+b'xyz'+struct.pack('<I', amount)


def test_learns_store_frame_and_rebuilds_it(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    s.learning = 'store'
    s.client(0x94a, store_frame(7, 12), 1.0)
    s.observe([{'kind': 'inventory_removed', 'inventory_index': 7, 'amount': 12},
               {'kind': 'storage_added', 'index': 3, 'amount': 12, 'item_id': 909}], 1.2)
    assert s.learning is None
    assert storage.build(s.config['frames']['store'], 9, 40) == store_frame(9, 40)
    assert storage.load()['frames']['store']['amount_size'] == 4


def test_deposit_skips_equipped_kept_and_equipment_then_closes(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    s.config = storage.save(dict(auto_enabled=True, threshold=50, keep_ids=[501],
                                 frames=dict(store=dict(hex=store_frame(0, 0).hex(), index_offset=4, amount_offset=9, amount_size=4),
                                             close=dict(hex='f700'))))
    s.observe([{'kind': 'player_stat', 'stat_type': 24, 'value': 600},
               {'kind': 'player_stat', 'stat_type': 25, 'value': 1000}], 0)
    assert s.wants_auto(1000)
    inventory = {2: dict(item_id=909, amount=5, stackable=True, equipped=0),
                 3: dict(item_id=501, amount=5, stackable=True, equipped=0),
                 4: dict(item_id=13001, amount=1, stackable=False, equipped=0),
                 5: dict(item_id=1750, amount=99, stackable=True, equipped=0x8000)}
    s.start_deposit(inventory, 1000)
    assert s.step(1000, lambda t: t.encode()) == b'@storage'
    s.observe([{'kind': 'storage_opened', 'count': 0, 'capacity': 600}], 1001)
    assert s.step(1002, None) == store_frame(2, 5)
    # refused by the server (never confirmed): skipped after the wait, then close
    assert s.step(1003, None) is None
    assert s.step(1004.5, None) == bytes.fromhex('f700')
    s.observe([{'kind': 'storage_closed'}], 1005)
    assert s.job is None and not s.wants_auto(1006, inventory)


def test_withdraw_takes_chosen_amounts(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    s.config = storage.save(dict(frames=dict(take=dict(hex=store_frame(0, 0).hex(), index_offset=4, amount_offset=9, amount_size=4),
                                             close=dict(hex='f700'))))
    s.start_withdraw([dict(item_id=909, amount=10), dict(item_id=512, amount=0)], 1)
    assert s.step(1, CHAT) == b'@storage'
    s.observe([{'kind': 'storage_list', 'stackable': True,
                'items': [{'index': 1, 'item_id': 909, 'amount': 30}, {'index': 2, 'item_id': 512, 'amount': 4}]}], 1.1)
    assert s.step(2, None) == store_frame(1, 10)
    s.observe([{'kind': 'storage_removed', 'index': 1, 'amount': 10}], 2.1)
    assert s.step(2.5, None) == store_frame(2, 4)


def test_reader_storage_packets():
    assert packet_reader.decode(struct.pack('<HHH', 0xf2, 3, 600))['kind'] == 'storage_opened'
    assert packet_reader.decode(struct.pack('<HHI', 0xf6, 4, 2)) == {'opcode': '00F6', 'kind': 'storage_removed', 'index': 4, 'amount': 2}
    assert packet_reader.decode(struct.pack('<H', 0xf8))['kind'] == 'storage_closed'


def test_learns_store_when_server_confirms_storage_before_inventory(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    s.learning = 'store'
    s.client(0x94, store_frame(7, 12), 1.0)
    s.observe([{'kind': 'storage_added', 'index': 3, 'amount': 12, 'item_id': 909},
               {'kind': 'inventory_removed', 'inventory_index': 7, 'amount': 12}], 1.2)
    assert s.learning is None and 'store' in s.config['frames']


def test_refused_item_is_never_tried_again_when_others_went_in(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    s.config = storage.save(dict(frames=dict(store=dict(hex=store_frame(0, 0).hex(), index_offset=4, amount_offset=9, amount_size=4),
                                             close=dict(hex='f700'))))
    inventory = {2: dict(item_id=7000, amount=1, stackable=True, equipped=0),
                 3: dict(item_id=909, amount=4, stackable=True, equipped=0)}
    s.start_deposit(inventory, 1)
    assert s.step(1, CHAT) == b'@storage'
    s.observe(OPEN, 1.1)
    assert s.step(2, None) == store_frame(2, 1)          # refused: no confirmation
    assert s.step(4.5, None) == store_frame(3, 4)
    s.observe([{'kind': 'storage_added', 'index': 1, 'amount': 4, 'item_id': 909}], 4.6)
    assert s.step(5, None) == bytes.fromhex('f700')
    s.observe([{'kind': 'storage_closed'}], 5.1)
    assert storage.load()['refused_ids'] == [7000]
    s.start_deposit(inventory, 10)
    assert [q[2] for q in s.job['queue']] == [909]


def test_nothing_accepted_marks_nothing(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    s.config = storage.save(dict(frames=dict(store=dict(hex=store_frame(0, 0).hex(), index_offset=4, amount_offset=9, amount_size=4),
                                             close=dict(hex='f700'))))
    s.start_deposit({2: dict(item_id=7000, amount=1, stackable=True, equipped=0)}, 1)
    s.step(1, CHAT); s.observe(OPEN, 1.1); s.step(2, None); s.step(4.5, None)
    s.observe([{'kind': 'storage_closed'}], 5)
    assert storage.load()['refused_ids'] == []


def test_bundled_frames_are_used_without_learning(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    (tmp_path/'pacotes.json').write_text('{"close": {"hex": "9301"}}', encoding='utf-8')
    assert storage.load()['frames']['close'] == {'hex': '9301'}


def heavy_storage(tmp_path, monkeypatch):
    s = make(tmp_path, monkeypatch)
    s.config = storage.save(dict(auto_enabled=True, threshold=50, frames=dict(
        store=dict(hex=store_frame(0, 0).hex(), index_offset=4, amount_offset=9, amount_size=4), close=dict(hex='f700'))))
    s.observe([{'kind': 'player_stat', 'stat_type': 24, 'value': 700},
               {'kind': 'player_stat', 'stat_type': 25, 'value': 1000}], 0)
    return s


def test_still_heavy_after_a_deposit_deposits_again_soon(tmp_path, monkeypatch):
    s = heavy_storage(tmp_path, monkeypatch)
    inventory = {2: dict(item_id=909, amount=5, stackable=True, equipped=0)}
    s.start_deposit(inventory, 100)
    s.step(100, CHAT); s.observe(OPEN, 100.1)
    s.step(101, None)
    s.observe([{'kind': 'storage_added', 'index': 1, 'amount': 5, 'item_id': 909}], 101.1)
    s.step(101.5, None); s.observe([{'kind': 'storage_closed'}], 101.6)
    # items put in by hand afterwards, still above 50%: no 5 minute wait any more
    inventory = {4: dict(item_id=512, amount=9, stackable=True, equipped=0)}
    assert s.wants_auto(107, inventory)


def test_same_items_that_did_not_go_in_wait_but_new_items_do_not(tmp_path, monkeypatch):
    s = heavy_storage(tmp_path, monkeypatch)
    inventory = {2: dict(item_id=909, amount=5, stackable=True, equipped=0)}
    s.start_deposit(inventory, 100)
    s.step(100, CHAT)
    s.step(107, None)  # @storage never answered
    assert s.job is None and not s.wants_auto(110, inventory)
    assert s.wants_auto(170, inventory)
    assert s.wants_auto(110, {**inventory, 5: dict(item_id=512, amount=1, stackable=True, equipped=0)})


def test_stuck_visit_is_abandoned(tmp_path, monkeypatch):
    s = heavy_storage(tmp_path, monkeypatch)
    s.start_deposit({2: dict(item_id=909, amount=5, stackable=True, equipped=0)}, 100)
    s.step(100, CHAT); s.observe(OPEN, 100.1); s.step(101, None)
    s.job['stage'] = 'stuck'
    s.step(200, None)
    assert s.job is None


def test_stale_open_state_still_sends_storage_command(tmp_path, monkeypatch):
    s = heavy_storage(tmp_path, monkeypatch)
    s.open = True
    s.start_deposit({2: dict(item_id=909, amount=5, stackable=True, equipped=0)}, 100)
    assert s.step(100, CHAT) == b'@storage'
