import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


TABLES = {
    'seat_pattern': 'cue:T cue_rev:I label:T pulse:T',
    'session': 'start:I end:I language:T',
    'cue': 'session:T start:I end:I terms:T',
    'rehearsal': 'cue:T cue_rev:I term:T language:T accepted:I',
    'credential': 'person:T language:T start:I end:I approved:I',
    'shift': 'person:T session:T start:I end:I',
    'turn': 'cue:T cue_rev:I shift:T person:T start:I end:I',
    'relay': 'outgoing:T out_rev:I incoming:T in_rev:I at:I witnessed:I',
    'layout': 'width:I height:I left:I top:I right:I bottom:I',
    'overlay': 'layout:T layout_rev:I left:I top:I right:I bottom:I',
    'asset': 'session:T session_rev:I start:I end:I',
    'review': 'asset:T asset_rev:I turn:T turn_rev:I start:I end:I layout:T layout_rev:I left:I top:I right:I bottom:I approved:I',
}


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(obj):
    return hashlib.sha256(encode(obj).encode()).hexdigest()


@contextmanager
def transaction(db, write=True):
    db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def schema(table):
    return {'id': 'T', 'rev': 'I', **dict(col.split(':') for col in TABLES[table].split())}


def connect(path, create=False):
    if not create and not Path(path).is_file():
        raise ValueError('database missing; use ingest or demo')
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    if create:
        with transaction(db):
            for table in TABLES:
                columns = ', '.join(f'{key} {"INTEGER" if dtype == "I" else "TEXT"} NOT NULL'
                                    for key, dtype in schema(table).items())
                db.execute(f'CREATE TABLE IF NOT EXISTS {table} ({columns}, PRIMARY KEY(id,rev))')
            db.execute('CREATE TABLE IF NOT EXISTS replay_sign (seq INTEGER PRIMARY KEY, asset TEXT NOT NULL, '
                       'basis TEXT NOT NULL, operator TEXT NOT NULL, evidence TEXT NOT NULL)')
    return db


def current(db, table):
    return {row['id']: dict(row) for row in db.execute(
        f'SELECT a.* FROM {table} a JOIN (SELECT id, max(rev) AS rev FROM {table} GROUP BY id) b '
        'USING(id, rev) ORDER BY a.id')}


def validate(table, record, columns):
    if record.keys() != columns.keys():
        raise ValueError(f'{table} requires {", ".join(columns)}')
    for key, kind in columns.items():
        value = record[key]
        if kind == 'T' and (type(value) is not str or (key != 'terms' and not value.strip())):
            raise ValueError(f'{table}.{key} requires text')
        if kind == 'I' and (type(value) is not int or not 0 <= value < 2**63):
            raise ValueError(f'{table}.{key} requires a nonnegative SQLite integer')
    for key, value in record.items():
        if (key == 'rev' or key.endswith('_rev')) and value < 1:
            if not (table == 'review' and key == 'asset_rev' and record['asset'] == '-'):
                raise ValueError(f'{table}.{key} must be positive')
        if key in ('approved', 'witnessed', 'accepted') and value not in (0, 1):
            raise ValueError(f'{table}.{key} must be 0 or 1')
    for lo, hi in [('start', 'end'), ('left', 'right'), ('top', 'bottom')]:
        if lo in record and record[lo] >= record[hi]:
            raise ValueError(f'{table}.{lo} must be less than {hi}')
    if table == 'seat_pattern' and (not 1 <= len(record['pulse']) <= 8 or set(record['pulse']) - {'0', '1'}):
        raise ValueError('seat pulse requires one to eight bits')
    if table == 'layout' and (not record['width'] or not record['height']):
        raise ValueError('canvas must be positive')
    if table == 'asset' and record['id'] == '-':
        raise ValueError('asset identity reserved for live capture')
    if table == 'review' and record['asset'] == '-' and record['asset_rev'] != 0:
        raise ValueError('live review asset revision must be zero')
    if table == 'cue' and record['terms']:
        terms = record['terms'].split(',')
        if any(not term or term != term.strip() for term in terms) or len(set(terms)) != len(terms):
            raise ValueError('cue terms must be distinct comma-separated keys')


def ingest(db, capture):
    if not isinstance(capture, list):
        raise ValueError('capture must be an array')
    added = 0
    with transaction(db):
        for event in capture:
            if not isinstance(event, dict):
                raise ValueError('capture row must be an object')
            table = event.get('type')
            if not isinstance(table, str) or table not in TABLES:
                raise ValueError(f'unknown capture type {table}')
            data = {key: value for key, value in event.items() if key != 'type'}
            columns = schema(table)
            validate(table, data, columns)
            prior = db.execute(f'SELECT * FROM {table} WHERE id=? AND rev=?', (data['id'], data['rev'])).fetchone()
            if prior is not None:
                if dict(prior) != data:
                    raise ValueError(f'conflicting {table} {data["id"]} revision {data["rev"]}')
                continue
            db.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in columns)})',
                       [data[key] for key in columns])
            added += 1
    return {'inserted': added, 'replayed': len(capture) - added}
