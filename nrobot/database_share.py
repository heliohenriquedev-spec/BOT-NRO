"""Portable game database snapshot and additive, idempotent import (never personal settings)."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import uuid
from . import drop_db

COLUMNS={
 'deaths':('id','species','name','map','x','y','stamp'),
 'floor':('id','item','amount','map','x','y','fresh','stamp','source'),
 'links':('floor_id','death_id','status'),
 'mob_info':('species','name','stamp','raw'),
 'mob_drops':('species','position','mvp','item','item_name','rate')}


def identity(root):
    path=Path(root)/'data/database/origem.json'
    try:value=json.loads(path.read_text(encoding='utf-8'))['source']
    except (OSError,ValueError,KeyError):value=None
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value):
        value=uuid.uuid4().hex;path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps({'source':value}),encoding='utf-8');temp.replace(path)
    return value


def snapshot(root):
    root=Path(root);path=root/'data/database/observacoes.sqlite3'
    if not path.exists():return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            db.execute('BEGIN')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result={}
            for name,columns in COLUMNS.items():
                if name not in tables:result[name]=[];continue
                present={row[1] for row in db.execute('PRAGMA table_info('+name+')')}
                selected=["'floor'" if name=='floor' and c=='source' and c not in present else c for c in columns]
                result[name]=[dict(zip(columns,row)) for row in db.execute('SELECT '+','.join(selected)+' FROM '+name)]
    except sqlite3.Error as exc:raise ValueError('Falha ao ler database para compartilhar: '+str(exc)) from exc
    return {'schema':1,'source':identity(root),'tables':result}


def validate(data):
    if not isinstance(data,dict) or data.get('schema')!=1 or not re.fullmatch('[0-9a-f]{32}',str(data.get('source',''))):
        raise ValueError('Database compartilhado invalido')
    tables=data.get('tables')
    if not isinstance(tables,dict):raise ValueError('Tabelas do database ausentes')
    for name,columns in COLUMNS.items():
        rows=tables.get(name,[])
        if not isinstance(rows,list):raise ValueError('Tabela invalida: '+name)
        for row in rows:
            if not isinstance(row,dict) or set(row)!=set(columns):raise ValueError('Colunas invalidas: '+name)
            if any(isinstance(v,(dict,list)) for v in row.values()):raise ValueError('Valor invalido no database')
    return data


def merge(data,root,log=print):
    data=validate(data);root=Path(root)
    if data['source']==identity(root):return 0
    path=root/'data/database/observacoes.sqlite3'
    if path.exists():
        backup=root/'backups'/('database_'+datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]+'.sqlite3')
        backup.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path,timeout=5)) as original,closing(sqlite3.connect(backup)) as saved:original.backup(saved)
    imported=0
    with closing(drop_db.open_database(path)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS shared_rows(source TEXT,kind TEXT,original INTEGER,local INTEGER,PRIMARY KEY(source,kind,original))')
        mapping={}
        for table in ('deaths','floor'):
            cols=COLUMNS[table][1:];ids={}
            for row in data['tables'].get(table,[]):
                match=db.execute('SELECT local FROM shared_rows WHERE source=? AND kind=? AND original=?',(data['source'],table,row['id'])).fetchone()
                if match:local=match[0]
                else:
                    cursor=db.execute('INSERT INTO '+table+'('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[row[k] for k in cols])
                    local=cursor.lastrowid;imported+=1
                    db.execute('INSERT INTO shared_rows VALUES(?,?,?,?)',(data['source'],table,row['id'],local))
                ids[row['id']]=local
            mapping[table]=ids
        for row in data['tables'].get('links',[]):
            floor=mapping['floor'].get(row['floor_id']);death=mapping['deaths'].get(row['death_id'])
            if floor is None or death is None:raise ValueError('Associacao de drop sem observacao correspondente')
            existing=db.execute('SELECT status FROM links WHERE floor_id=? AND death_id=?',(floor,death)).fetchone()
            if not existing:db.execute('INSERT INTO links VALUES(?,?,?)',(floor,death,row['status']))
            elif existing[0]=='candidate':db.execute('UPDATE links SET status=? WHERE floor_id=? AND death_id=?',(row['status'],floor,death))
        replace=set()
        for row in data['tables'].get('mob_info',[]):
            old=db.execute('SELECT stamp FROM mob_info WHERE species=?',(row['species'],)).fetchone()
            if old and old[0]>row['stamp']:continue
            replace.add(row['species'])
            db.execute('INSERT OR REPLACE INTO mob_info VALUES(?,?,?,?)',[row[k] for k in COLUMNS['mob_info']])
            db.execute('DELETE FROM mob_drops WHERE species=?',(row['species'],))
        for row in data['tables'].get('mob_drops',[]):
            if row['species'] in replace:db.execute('INSERT OR REPLACE INTO mob_drops VALUES(?,?,?,?,?,?)',[row[k] for k in COLUMNS['mob_drops']])
    log('Database recebido: '+str(imported)+' observacoes novas; drops e informacoes de monstros mesclados.')
    return imported
