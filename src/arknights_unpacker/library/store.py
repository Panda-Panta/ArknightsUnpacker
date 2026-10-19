"""SQLite transactions; each call owns its connection, including GUI workers."""
from __future__ import annotations
import sqlite3
import uuid
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
from arknights_unpacker.contracts import ScanSnapshot, GameDataSnapshot
from .serialization import dumps_snapshot, loads_snapshot

SCHEMA_VERSION = 2
_DATA_SCHEMA = '''CREATE TABLE IF NOT EXISTS data_snapshots(
    id TEXT NOT NULL, profile_id TEXT NOT NULL, created REAL NOT NULL,
    complete INTEGER NOT NULL, version TEXT NOT NULL,
    resource_version TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(profile_id,id))'''


class CatalogStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError(f'数据库版本 {version} 高于本程序支持版本 {SCHEMA_VERSION}，拒绝降级')
            table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='data_snapshots'").fetchone()
            migrating = version < SCHEMA_VERSION and table is not None
            if migrating:
                # SQLite backup captures committed pages, including WAL content;
                # a raw filesystem copy is insufficient while another reader exists.
                backup_path = self.db_path.with_name(self.db_path.name + f'.v1-backup-{uuid.uuid4().hex}.sqlite')
                with backup_path.open('xb'):
                    pass
                backup_db = sqlite3.connect(backup_path)
                try:
                    db.backup(backup_db)
                finally:
                    backup_db.close()
            db.execute('BEGIN IMMEDIATE')
            if migrating:
                db.execute('ALTER TABLE data_snapshots RENAME TO data_snapshots_v1')
                db.execute(_DATA_SCHEMA)
                db.execute('''INSERT INTO data_snapshots(id,profile_id,created,complete,version,resource_version,payload)
                              SELECT id,profile_id,created,complete,version,resource_version,payload FROM data_snapshots_v1''')
                db.execute('DROP TABLE data_snapshots_v1')
            self._create_tables(db)
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    @staticmethod
    def _create_tables(db):
        db.execute('''CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,
                      started REAL NOT NULL,finished REAL NOT NULL,complete INTEGER NOT NULL,payload TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS scan_profile ON scans(profile_id,started)')
        db.execute(_DATA_SCHEMA)
        db.execute('CREATE INDEX IF NOT EXISTS data_profile ON data_snapshots(profile_id,created)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_scan(self, snapshot: ScanSnapshot):
        payload = dumps_snapshot(snapshot)
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO scans VALUES(?,?,?,?,?,?)',
                       (snapshot.snapshot_id, snapshot.profile_id, snapshot.started_at,
                        snapshot.finished_at, int(snapshot.complete), payload))

    def latest_scan(self, profile_id: str, complete_only: bool = True) -> ScanSnapshot | None:
        sql = 'SELECT payload FROM scans WHERE profile_id=?' + (' AND complete=1' if complete_only else '') + ' ORDER BY started DESC,rowid DESC LIMIT 1'
        with self._connect() as db:
            row = db.execute(sql, (profile_id,)).fetchone()
        return loads_snapshot(row['payload']) if row else None

    def list_scans(self, profile_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute('SELECT id AS snapshot_id,profile_id,started AS started_at,finished AS finished_at,complete FROM scans WHERE profile_id=? ORDER BY started DESC,rowid DESC', (profile_id,)).fetchall()
        return [dict(row) for row in rows]

    def save_data_snapshot(self, profile_id: str, data: GameDataSnapshot):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT complete FROM data_snapshots WHERE profile_id=? AND id=?', (profile_id, data.snapshot_id)).fetchone()
            if not data.complete and existing is not None and existing['complete']:
                # Content IDs omit observation failures. A failed read of the
                # same content must never replace an already complete baseline.
                # Keep its diagnostics under an independent observation ID,
                # sharing table objects without modifying or copying their tree.
                data = replace(data, snapshot_id=f'{data.snapshot_id}:partial:{uuid.uuid4().hex}',
                               sources={**data.sources, '_content_snapshot_id': data.snapshot_id})
            payload = dumps_snapshot(data)
            db.execute('INSERT OR REPLACE INTO data_snapshots VALUES(?,?,?,?,?,?,?)',
                       (data.snapshot_id, profile_id, data.created_at, int(data.complete),
                        data.version, data.resource_version, payload))

    def latest_data_snapshot(self, profile_id: str) -> GameDataSnapshot | None:
        with self._connect() as db:
            row = db.execute('SELECT payload FROM data_snapshots WHERE profile_id=? AND complete=1 ORDER BY created DESC,rowid DESC LIMIT 1', (profile_id,)).fetchone()
        return loads_snapshot(row['payload']) if row else None

    def list_data_snapshots(self, profile_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute('SELECT id AS snapshot_id,profile_id,created AS created_at,complete,version,resource_version FROM data_snapshots WHERE profile_id=? ORDER BY created DESC,rowid DESC', (profile_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_data_snapshot(self, id: str, profile_id: str | None = None) -> GameDataSnapshot | None:
        # Legacy callers may omit profile. New services must supply it so an
        # explicit baseline belongs to the selected installation.
        sql = 'SELECT payload FROM data_snapshots WHERE id=?'
        parameters = (id,)
        if profile_id is not None:
            sql += ' AND profile_id=?'
            parameters = (id, profile_id)
        with self._connect() as db:
            row = db.execute(sql + ' ORDER BY created DESC,rowid DESC LIMIT 1', parameters).fetchone()
        return loads_snapshot(row['payload']) if row else None
