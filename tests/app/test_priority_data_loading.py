"""Core data parsing must not require an unrelated whole-resource catalog walk."""
from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import GameDataSnapshot


def test_core_loading_works_without_full_catalog_walk_and_keeps_existing_inventory(tmp_path, monkeypatch):
    import arknights_unpacker.library as library
    import arknights_unpacker.gamedata as gamedata
    root = tmp_path / 'game'
    root.mkdir()
    (root / 'one.ab').write_bytes(b'fixture')
    services = AppServices(tmp_path / 'data', tmp_path / 'output')
    inventory = services.scan(root)
    original = services.catalog
    monkeypatch.setattr(services.runner, 'run', lambda *a, **k: {})
    monkeypatch.setattr(gamedata, 'load_gamedata', lambda sources: GameDataSnapshot('core', 'v', 'r', {}))

    def forbidden(*args):
        raise AssertionError('Core results were delayed by a whole-resource catalog walk')

    monkeypatch.setattr(library, 'load_catalog', forbidden)
    services.load_data(root)
    assert services.catalog is original
    assert services.scan_snapshot is inventory['snapshot']
    services.shutdown()


def test_data_only_first_run_has_explicit_empty_catalog_then_scan_populates_it(tmp_path, monkeypatch):
    import arknights_unpacker.library as library
    import arknights_unpacker.gamedata as gamedata
    root = tmp_path / 'game'
    root.mkdir()
    (root / 'one.ab').write_bytes(b'fixture')
    services = AppServices(tmp_path / 'data', tmp_path / 'output')
    monkeypatch.setattr(services.runner, 'run', lambda *a, **k: {})
    monkeypatch.setattr(gamedata, 'load_gamedata', lambda sources: GameDataSnapshot('core', 'v', 'r', {}))
    monkeypatch.setattr(library, 'load_catalog', lambda *a: (_ for _ in ()).throw(AssertionError('Full catalog walk')))
    services.load_data(root)
    assert services.catalog.installation == services.installation
    assert not services.catalog.resources
    assert services.scan_snapshot is None
    result = services.scan(root)
    assert len(result['snapshot'].files) == 1
    assert services.catalog is result['catalog']
    services.shutdown()
