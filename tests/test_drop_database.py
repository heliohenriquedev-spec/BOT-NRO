import struct

import pytest

from nrobot import drop_db
from nrobot.packet_reader import decode


def spawn(identity=110777031, **extra):
    return dict(kind='appearance', entity_id=identity, species_id=1037,
                position=[10, 10], object_type=5, **extra)


def death(identity=110777031):
    return dict(kind='remove', entity_id=identity, reason=1)


def item(identity=99, fresh=True, position=None):
    return dict(kind='floor_item', object_id=identity, item_id=501, amount=2,
                position=position or [11, 10], newly_dropped=fresh)


@pytest.mark.parametrize('opcode,offset', [(0x9d, 13), (0x9e, 15)])
def test_floor_packet_layouts(opcode, offset):
    packet = bytearray(17)
    struct.pack_into('<HIHBHH', packet, 0, opcode, 123, 501, 1, 20, 30)
    struct.pack_into('<H', packet, offset, 7)
    result = decode(bytes(packet))
    assert result['amount'] == 7 and result['position'] == [20, 30]
    assert result['item_id'] == 501 and result['object_id'] == 123
    assert result['newly_dropped'] == (opcode == 0x9e)
    assert decode(struct.pack('<HI', 0xa1, 123))['kind'] == 'floor_item_removed'


def test_candidate_persists_and_repeated_appearances_do_not_duplicate():
    observer = drop_db.DropObserver()
    observer.observe([spawn(), death(), item(), item()], 1, 10, 'moc_fild01.gat')
    observer.close()
    row, = drop_db.rows()
    assert row['species_id'] == 1037 and row['status'] == 'candidate'
    assert row['quantity'] == 2 and row['observations'] == 1
    drop_db.review(row)
    assert drop_db.rows()[0]['status'] == 'reviewed'


def test_item_before_death_and_ambiguous_same_species_not_double_counted():
    observer = drop_db.DropObserver()
    observer.observe([spawn(), spawn(110777032), item()], 1, 10, 'moc_fild01.gat')
    observer.observe([death(), death(110777032)], 1, 10.5, 'moc_fild01.gat')
    row, = drop_db.rows()
    assert row['quantity'] == 2 and row['observations'] == 1
    assert observer.db.execute('SELECT count(*) FROM links').fetchone()[0] == 2
    observer.close()


@pytest.mark.parametrize('events', [
    [spawn(), death(), item(fresh=False)],
    [spawn(summoned=True), death(), item()],
    [spawn(2003143), death(2003143), item()],
    [spawn(), death(), item(position=[50, 50])],
])
def test_no_false_source_for_existing_items_summons_players_or_distant_drops(events):
    observer = drop_db.DropObserver()
    observer.observe(events, 1, 10, 'moc_fild01.gat')
    assert all(row['species_id'] == 0 for row in drop_db.rows())
    observer.close()


def test_map_transition_and_expired_deaths_cannot_link():
    observer = drop_db.DropObserver()
    observer.observe([spawn(), death()], 1, 10, 'moc_fild01.gat')
    observer.observe([item()], 1, 12, 'moc_fild01.gat')
    observer.observe([dict(kind='map_change', map='other.gat'), item(100)], 1, 12.1, 'other.gat')
    assert all(row['status'] == 'unlinked' for row in drop_db.rows())
    observer.close()


def test_inventory_receipts_have_no_inferred_monster_source():
    observer = drop_db.DropObserver()
    receipt = dict(kind='inventory_added', item_id=501, amount=4, success=True)
    observer.observe([spawn(), death(), receipt, {**receipt, 'success': False}], 1, 10, 'moc_fild01.gat')
    row, = drop_db.rows()
    assert row['source'] == 'inventory' and row['quantity'] == 4
    assert row['species_id'] == 0
    with pytest.raises(ValueError):
        drop_db.review(row)
    observer.close()


def test_local_database_is_update_protected():
    from nrobot.updater import is_protected
    assert is_protected('data/database/observacoes.sqlite3')
    assert is_protected('data/database/observacoes.sqlite3-wal')


def test_dialog_queries_passive_records():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from nrobot.drop_panel import DropDatabaseDialog
    observer = drop_db.DropObserver()
    observer.observe([spawn(), death(), item()], 1, 10, 'moc_fild01.gat')
    observer.close()
    dialog = DropDatabaseDialog()
    assert dialog.table.rowCount() == 1
    dialog.search.setText('impossible-item-name')
    dialog.reload()  # typing waits 300 ms before rebuilding the tables
    assert dialog.table.rowCount() == 0
    dialog.close()
