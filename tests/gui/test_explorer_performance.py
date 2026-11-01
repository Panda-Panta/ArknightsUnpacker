"""Filtering an unchanged catalogue must not repeatedly rebuild its path rows."""
from pathlib import Path

from arknights_unpacker.contracts import GameInstallation, ResolvedResource, ResourceCatalog
from arknights_unpacker.ui.explorer import ExplorerView


def test_effective_resource_search_reuses_rows_and_data_refresh_invalidates(qtbot, tmp_path, monkeypatch):
    view = ExplorerView()
    qtbot.addWidget(view)
    view.set_root(tmp_path)
    catalog = ResourceCatalog(GameInstallation(tmp_path, 'profile'), resources={
        'one': ResolvedResource('images/one.ab', str(tmp_path / 'images/one.ab'),
                                'base', 'current', '剧情插图'),
        'missing': ResolvedResource('images/missing.ab', None, 'hot', 'missing', '剧情插图'),
    })
    view.set_data(None, None, catalog)
    view.recursive.setChecked(True)
    view.layer.setCurrentIndex(1)
    assert {row['path'] for row in view.model.rows} == {'images/one.ab', 'images/missing.ab'}

    original = Path.relative_to
    conversions = []

    def count(self, *args, **kwargs):
        conversions.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'relative_to', count)
    view.search.setText('missing')
    assert [row['path'] for row in view.model.rows] == ['images/missing.ab']
    view.search.clear()
    view.ab_only.setChecked(True)
    assert len(view.model.rows) == 2
    assert conversions == [], 'Unchanged catalogue search must reuse already prepared resource paths'

    catalog.resources['two'] = ResolvedResource('images/two.ab', str(tmp_path / 'images/two.ab'),
                                               'hot', 'current', '剧情插图')
    view.set_data(None, None, catalog)
    assert {row['path'] for row in view.model.rows} == {'images/one.ab', 'images/two.ab', 'images/missing.ab'}
    assert conversions, 'A new catalogue observation must invalidate the prepared rows'


def test_effective_resource_cache_tracks_root_and_keeps_original_source_paths(qtbot, tmp_path):
    view = ExplorerView()
    qtbot.addWidget(view)
    first_root = tmp_path / 'first'
    second_root = tmp_path / 'second'
    first_root.mkdir()
    second_root.mkdir()
    path = first_root / 'one.ab'
    catalog = ResourceCatalog(GameInstallation(first_root, 'profile'), resources={
        'one': ResolvedResource('logical/one.ab', str(path), 'base', 'current', '剧情插图'),
    })
    view.set_root(first_root)
    view.set_data(None, None, catalog)
    view.recursive.setChecked(True)
    view.layer.setCurrentIndex(1)
    assert view.model.rows[0]['path'] == 'one.ab'
    assert view.model.rows[0]['source_path'] == str(path)
    view.set_root(second_root)
    assert view.model.rows[0]['path'] == str(path)
    assert view.model.rows[0]['source_path'] == str(path)
