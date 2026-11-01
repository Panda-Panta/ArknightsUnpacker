"""SQLite transactions; each call owns its connection, including GUI workers."""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
from arknights_unpacker.contracts import (EntityChangeSet, FileChange, FileChangeSet,
                                         FileRecord, GameInstallation, GameDataSnapshot,
                                         ScanSnapshot, as_jsonable)
from .serialization import dumps_snapshot, loads_snapshot

SCHEMA_VERSION = 3
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
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            migrating = version < SCHEMA_VERSION and bool(tables)
            if migrating:
                # SQLite backup captures committed pages, including WAL content;
                # a raw filesystem copy is insufficient while another reader exists.
                backup_path = self.db_path.with_name(self.db_path.name + f'.v{version or 1}-backup-{uuid.uuid4().hex}.sqlite')
                with backup_path.open('xb'):
                    pass
                backup_db = sqlite3.connect(backup_path)
                try:
                    db.backup(backup_db)
                finally:
                    backup_db.close()
            db.execute('BEGIN IMMEDIATE')
            if version < 2 and 'data_snapshots' in tables:
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
        db.execute('''CREATE TABLE IF NOT EXISTS profiles(
                      profile_id TEXT PRIMARY KEY,root_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS result_state(
                      profile_id TEXT NOT NULL,kind TEXT NOT NULL,snapshot_id TEXT NOT NULL,
                      changes TEXT NOT NULL,baseline TEXT,PRIMARY KEY(profile_id,kind))''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _root_key(root):
        return os.path.normcase(str(Path(root).expanduser().resolve()))

    def save_installation(self, installation: GameInstallation):
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO profiles VALUES(?,?,?)',
                       (installation.profile_id, self._root_key(installation.root),
                        json.dumps(as_jsonable(installation), ensure_ascii=False)))

    def get_installation(self, root) -> GameInstallation | None:
        """Resolve saved roots even when the source disk is no longer available."""
        roots = [Path(root).expanduser().resolve()]
        if roots[0].name.casefold() == 'arknights_data':
            roots.append(roots[0].parent)
        keys = [self._root_key(value) for value in roots]
        with self._connect() as db:
            for key in keys:
                row = db.execute('SELECT payload FROM profiles WHERE root_key=?', (key,)).fetchone()
                if row:
                    value = json.loads(row['payload'])
                    for name in ('root', 'base_root', 'hot_root'):
                        value[name] = Path(value[name]) if value.get(name) else None
                    return GameInstallation(**value)
            # v1/v2 did not save profile metadata separately. A captured scan is
            # sufficient to reconstruct its installation without reading game files.
            rows = db.execute('SELECT payload FROM scans ORDER BY started DESC,rowid DESC')
            for row in rows:
                scan = loads_snapshot(row['payload'])
                if self._root_key(scan.root) in keys:
                    captured = scan.manifest_versions.get('installation', {})
                    return GameInstallation(Path(scan.root), scan.profile_id,
                                            Path(captured['base_root']) if captured.get('base_root') else None,
                                            Path(captured['hot_root']) if captured.get('hot_root') else None,
                                            captured.get('locale', 'unknown'))
            # A legacy data-only session has the same deterministic profile key
            # as discover_installation, though its source layers were not retained.
            for candidate, key in zip(roots, keys):
                profile = hashlib.sha256(('pc|unknown|' + key).encode('utf8')).hexdigest()[:24]
                if db.execute('SELECT 1 FROM data_snapshots WHERE profile_id=? LIMIT 1', (profile,)).fetchone():
                    return GameInstallation(candidate, profile, diagnostics=['从历史资料恢复，资源层信息未保留'])
        return None

    @staticmethod
    def _save_result(db, profile_id, kind, snapshot_id, changes, baseline=None):
        db.execute('INSERT OR REPLACE INTO result_state VALUES(?,?,?,?,?)',
                   (profile_id, kind, snapshot_id,
                    json.dumps(as_jsonable(changes), ensure_ascii=False, separators=(',', ':')),
                    dumps_snapshot(baseline) if baseline is not None else None))

    @staticmethod
    def _file_changes(raw):
        value = json.loads(raw)
        for change in value.get('changes', []):
            for name in ('before', 'after'):
                change[name] = FileRecord(**change[name]) if change.get(name) else None
        value['changes'] = [FileChange(**item) for item in value.get('changes', [])]
        return FileChangeSet(**value)

    def save_scan(self, snapshot: ScanSnapshot, changes: FileChangeSet | None = None):
        payload = dumps_snapshot(snapshot)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if changes is None:
                from .changes import compare_files
                previous = None
                if snapshot.baseline_id:
                    row = db.execute('SELECT payload FROM scans WHERE profile_id=? AND id=?',
                                     (snapshot.profile_id, snapshot.baseline_id)).fetchone()
                    previous = loads_snapshot(row['payload']) if row else None
                changes = compare_files(previous, snapshot)
            db.execute('INSERT OR REPLACE INTO scans VALUES(?,?,?,?,?,?)',
                       (snapshot.snapshot_id, snapshot.profile_id, snapshot.started_at,
                        snapshot.finished_at, int(snapshot.complete), payload))
            self._save_result(db, snapshot.profile_id, 'scan', snapshot.snapshot_id, changes)

    def latest_scan_result(self, profile_id: str):
        with self._connect() as db:
            state = db.execute("SELECT * FROM result_state WHERE profile_id=? AND kind='scan'", (profile_id,)).fetchone()
            if state:
                row = db.execute('SELECT payload FROM scans WHERE profile_id=? AND id=?',
                                 (profile_id, state['snapshot_id'])).fetchone()
                if row is None:
                    raise ValueError('保存的扫描结果缺少关联快照，请重新扫描。')
                return loads_snapshot(row['payload']), self._file_changes(state['changes'])
        current = self.latest_scan(profile_id, complete_only=False)
        if current is None:
            return None, None
        from .changes import compare_files
        previous = None
        if current.baseline_id:
            with self._connect() as db:
                row = db.execute('SELECT payload FROM scans WHERE profile_id=? AND id=?',
                                 (profile_id, current.baseline_id)).fetchone()
            previous = loads_snapshot(row['payload']) if row else None
        return current, compare_files(previous, current)

    def latest_scan(self, profile_id: str, complete_only: bool = True) -> ScanSnapshot | None:
        sql = 'SELECT payload FROM scans WHERE profile_id=?' + (' AND complete=1' if complete_only else '') + ' ORDER BY started DESC,rowid DESC LIMIT 1'
        with self._connect() as db:
            row = db.execute(sql, (profile_id,)).fetchone()
        return loads_snapshot(row['payload']) if row else None

    def list_scans(self, profile_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute('SELECT id AS snapshot_id,profile_id,started AS started_at,finished AS finished_at,complete FROM scans WHERE profile_id=? ORDER BY started DESC,rowid DESC', (profile_id,)).fetchall()
        return [dict(row) for row in rows]

    def save_data_snapshot(self, profile_id: str, data: GameDataSnapshot,
                           changes: EntityChangeSet | None = None, *, baseline=None):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if changes is None:
                from ..gamedata import compare_entities
                row = db.execute('SELECT payload FROM data_snapshots WHERE profile_id=? AND complete=1 ORDER BY created DESC,rowid DESC LIMIT 1', (profile_id,)).fetchone()
                changes = compare_entities(loads_snapshot(row['payload']) if row else None, data)
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
            changes = replace(changes, current_id=data.snapshot_id)
            self._save_result(db, profile_id, 'data', data.snapshot_id, changes, baseline)
        return data

    def save_data_changes(self, profile_id: str, data: GameDataSnapshot,
                          changes: EntityChangeSet, *, baseline=None):
        with self._connect() as db:
            if not db.execute('SELECT 1 FROM data_snapshots WHERE profile_id=? AND id=?',
                              (profile_id, data.snapshot_id)).fetchone():
                raise ValueError('当前资料快照尚未保存，无法保存比较结果。')
            self._save_result(db, profile_id, 'data', data.snapshot_id, changes, baseline)

    def latest_data_result(self, profile_id: str):
        with self._connect() as db:
            state = db.execute("SELECT * FROM result_state WHERE profile_id=? AND kind='data'", (profile_id,)).fetchone()
            if state:
                row = db.execute('SELECT payload FROM data_snapshots WHERE profile_id=? AND id=?',
                                 (profile_id, state['snapshot_id'])).fetchone()
                if row is None:
                    raise ValueError('保存的解析结果缺少关联快照，请重新解析核心数据。')
                return (loads_snapshot(row['payload']), EntityChangeSet(**json.loads(state['changes'])),
                        loads_snapshot(state['baseline']) if state['baseline'] else None)
            row = db.execute('SELECT rowid,payload,created,id FROM data_snapshots WHERE profile_id=? ORDER BY created DESC,rowid DESC LIMIT 1', (profile_id,)).fetchone()
            if row is None:
                return None, None, None
            prior = db.execute('''SELECT payload FROM data_snapshots WHERE profile_id=? AND complete=1
                                  AND (created<? OR (created=? AND rowid<?))
                                  ORDER BY created DESC,rowid DESC LIMIT 1''',
                               (profile_id, row['created'], row['created'], row['rowid'])).fetchone()
        from ..gamedata import compare_entities
        data = loads_snapshot(row['payload'])
        previous = loads_snapshot(prior['payload']) if prior else None
        changes = compare_entities(previous, data)
        self.save_data_changes(profile_id, data, changes)
        return data, changes, None

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
