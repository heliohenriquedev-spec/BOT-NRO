import json
import sqlite3
from contextlib import closing
from pathlib import Path
import pytest
from nrobot import drop_db,shared_data,database_share


def sample(root,suffix='',stamp='2026-11-05T10:00:00'):
    path=Path(root)/'data/database/observacoes.sqlite3'
    with closing(drop_db.open_database(path)) as db,db:
        db.execute('INSERT INTO deaths(species,name,map,x,y,stamp) VALUES(1037,?,\'field\',10,10,?)',('Cobra'+suffix,stamp))
        db.execute("INSERT INTO floor(item,amount,map,x,y,fresh,stamp) VALUES(501,2,'field',10,10,1,?)",(stamp,))
        db.execute("INSERT INTO links VALUES(1,1,'candidate')")
        db.execute('INSERT INTO mob_info VALUES(1037,?,?,?)',('Cobra'+suffix,stamp,'HP 100'))
        db.execute("INSERT INTO mob_drops VALUES(1037,0,0,501,'Pocao',30)")
    return path


def test_export_and_import_preserve_local_data_links_and_do_not_duplicate(tmp_path):
    author=tmp_path/'author';user=tmp_path/'user'
    source=sample(author);local=sample(user,' local',stamp='2026-11-05T11:00:00')
    data=database_share.snapshot(author)
    assert set(data['tables'])==set(database_share.COLUMNS)
    assert database_share.merge(data,user,lambda _:None)==2
    assert database_share.merge(data,user,lambda _:None)==0
    with closing(sqlite3.connect(local)) as db:
        assert db.execute('SELECT COUNT(*) FROM deaths').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM floor').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM links').fetchone()[0]==2
        assert db.execute('SELECT name FROM mob_info').fetchone()[0]=='Cobra local'
    assert list((user/'backups').glob('database_*.sqlite3'))
    assert database_share.merge(data,author,lambda _:None)==0


def test_new_receiver_gets_server_drop_rates_and_local_review_is_preserved(tmp_path):
    author=tmp_path/'author';user=tmp_path/'user';sample(author)
    data=database_share.snapshot(author);database_share.merge(data,user,lambda _:None)
    path=user/'data/database/observacoes.sqlite3'
    with closing(sqlite3.connect(path)) as db,db:db.execute("UPDATE links SET status='reviewed'")
    database_share.merge(data,user,lambda _:None)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT rate FROM mob_drops').fetchone()[0]==30
        assert db.execute('SELECT status FROM links').fetchone()[0]=='reviewed'


def test_snapshot_sees_committed_wal_and_whitelists_game_tables(tmp_path):
    path=sample(tmp_path)
    with closing(sqlite3.connect(path)) as db,db:
        db.execute('CREATE TABLE secret(value TEXT)');db.execute("INSERT INTO secret VALUES('do not export')")
    data=database_share.snapshot(tmp_path)
    assert 'secret' not in data['tables'] and 'do not export' not in json.dumps(data)
    assert len(data['tables']['floor'])==1


def test_shared_release_contains_database_and_receiver_imports_it(tmp_path):
    author=tmp_path/'author';user=tmp_path/'user';sample(author)
    shared_data.export(root=author,log=lambda _:None)
    source=author/shared_data.SHARED
    import shutil
    shutil.copytree(source,user/shared_data.SHARED)
    assert shared_data.merge(user,lambda _:None)
    assert drop_db.server_drops(path=user/'data/database/observacoes.sqlite3')[0]['item_id']==501
    assert not shared_data.merge(user,lambda _:None)


def test_bad_link_rolls_back_import_without_damaging_existing_records(tmp_path):
    author=tmp_path/'author';user=tmp_path/'user';sample(author);local=sample(user)
    data=database_share.snapshot(author);data['tables']['links'][0]['death_id']=99999
    with pytest.raises(ValueError):database_share.merge(data,user,lambda _:None)
    with closing(sqlite3.connect(local)) as db:assert db.execute('SELECT COUNT(*) FROM deaths').fetchone()[0]==1
