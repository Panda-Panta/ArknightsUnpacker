"""Specific resource types search globally, restoring directory scope on clear."""
from copy import deepcopy
import time

import pytest
from PySide6.QtCore import QPoint, Qt

from arknights_unpacker.contracts import (FileChangeSet, FileRecord, GameInstallation,
    ResolvedResource, ResourceCatalog, ScanSnapshot, as_jsonable)
from arknights_unpacker.library.classifications import category_labels, classify
from arknights_unpacker.ui.explorer import ExplorerView
from arknights_unpacker.ui.styles import apply_theme


@pytest.fixture
def explorer(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    paths = ('avg/images/current.AB', 'avg/images/alternate.bin', 'avg/images/deep/nested.ab',
             'avg/backgrounds/backdrop.ab', 'arts/charportraits/operator.ab', 'custom/extra.ab', 'notes.json')
    now = time.time()
    records = []
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'UnityFS-UI-fixture')
        category = '自定义原始用途' if name.startswith('custom/') else classify(name, 'base')
        records.append(FileRecord(name, 20, int(now * 1e9), path.suffix, 'base', category))
    for name in ('anon/story.bin', 'anon/custom.bin'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'UnityFS-UI-fixture')
    catalog = ResourceCatalog(GameInstallation(tmp_path, 'profile'), resources={
        'story': ResolvedResource('avg/images/logical', str(tmp_path / 'anon/story.bin'), 'hot', 'current', '剧情插图'),
        'story_ab': ResolvedResource('avg/images/current', str(tmp_path / 'avg/images/current.AB'), 'base', 'current', '剧情插图'),
        'backdrop': ResolvedResource('avg/backgrounds/backdrop', str(tmp_path / 'avg/backgrounds/backdrop.ab'), 'base', 'current', '剧情背景'),
        'custom': ResolvedResource('custom/logical', str(tmp_path / 'anon/custom.bin'), 'hot', 'current', '自定义生效用途'),
        'missing': ResolvedResource('avg/images/missing', None, 'hot', 'missing', '剧情插图'),
    })
    view = ExplorerView()
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.set_root(tmp_path)
    view.set_data(ScanSnapshot('current', 'profile', str(tmp_path), now, now, records),
                  FileChangeSet(None, 'current'), catalog)
    return view


def choose_type(view, category):
    index = view.file_type.findData(category)
    assert index >= 0
    view.file_type.setCurrentIndex(index)


def visible_paths(view):
    return {row['path'] for row in view.model.rows}


def test_file_type_choices_reuse_common_labels_before_scan(qtbot):
    view = ExplorerView()
    qtbot.addWidget(view)
    assert view.file_type.currentData() is None
    choices = [view.file_type.itemData(index) for index in range(1, view.file_type.count())]
    assert set(choices) == set(category_labels())
    assert choices.count('剧情插图') == 1


def test_specific_original_type_ignores_saved_directory_and_recursion_but_keeps_search_and_extension(explorer):
    before = deepcopy(as_jsonable(explorer.snapshot))
    explorer.folder = 'avg/backgrounds'
    explorer.recursive.setChecked(False)
    explorer.refresh()
    assert visible_paths(explorer) == {'avg/backgrounds/backdrop.ab'}
    choose_type(explorer, '剧情插图')
    assert visible_paths(explorer) == {'avg/images/current.AB', 'avg/images/alternate.bin', 'avg/images/deep/nested.ab'}
    explorer.ab_only.setChecked(True)
    assert visible_paths(explorer) == {'avg/images/current.AB', 'avg/images/deep/nested.ab'}
    explorer.search.setText('nested')
    assert visible_paths(explorer) == {'avg/images/deep/nested.ab'}
    assert explorer.folder == 'avg/backgrounds' and not explorer.recursive.isChecked()
    assert as_jsonable(explorer.snapshot) == before


def test_effective_types_use_existing_categories_even_for_anonymous_or_missing_sources(explorer):
    explorer.layer.setCurrentIndex(1)
    explorer.recursive.setChecked(True)
    choose_type(explorer, '剧情插图')
    assert visible_paths(explorer) == {'anon/story.bin', 'avg/images/current.AB', 'avg/images/missing'}
    explorer.search.setText('anon')
    assert visible_paths(explorer) == {'anon/story.bin'}
    explorer.ab_only.setChecked(True)
    assert not visible_paths(explorer)
    explorer.search.clear()
    assert visible_paths(explorer) == {'avg/images/current.AB'}
    explorer.folder = 'avg/backgrounds'
    explorer.refresh()
    assert visible_paths(explorer) == {'avg/images/current.AB'}
    choose_type(explorer, '剧情背景')
    assert visible_paths(explorer) == {'avg/backgrounds/backdrop.ab'}
    explorer.folder = 'avg'
    explorer.recursive.setChecked(False)
    assert visible_paths(explorer) == {'avg/backgrounds/backdrop.ab'}


@pytest.mark.parametrize('layer', [0, 1])
@pytest.mark.parametrize('recursive', [False, True])
def test_global_type_scope_disables_navigation_and_restores_original_directory_on_all_types(explorer, layer, recursive):
    explorer.folder = 'avg/backgrounds'
    explorer.recursive.setChecked(recursive)
    explorer.layer.setCurrentIndex(layer)
    explorer.refresh()
    original_paths = visible_paths(explorer)
    choose_type(explorer, '剧情插图')
    assert len(visible_paths(explorer)) == 3
    assert '全库筛选' in explorer.breadcrumb.text()
    assert ('全部已扫描资源' if layer == 0 else '全部生效资源') in explorer.breadcrumb.text()
    assert not explorer.tree.isEnabled()
    assert not explorer.up_button.isEnabled()
    assert not explorer.recursive.isEnabled()
    explorer.up_button.click()
    explorer.recursive.click()
    assert explorer.folder == 'avg/backgrounds' and explorer.recursive.isChecked() is recursive
    explorer.file_type.setCurrentIndex(0)
    assert visible_paths(explorer) == original_paths
    assert explorer.tree.isEnabled() and explorer.up_button.isEnabled() and explorer.recursive.isEnabled()
    assert explorer.breadcrumb.text() == str(explorer.root / 'avg/backgrounds')
    assert explorer.folder == 'avg/backgrounds' and explorer.recursive.isChecked() is recursive


def test_observed_custom_types_are_available_across_both_sources_and_refreshes(explorer):
    assert explorer.file_type.findData('自定义原始用途') >= 0
    assert explorer.file_type.findData('自定义生效用途') >= 0
    explorer.recursive.setChecked(True)
    choose_type(explorer, '自定义原始用途')
    assert visible_paths(explorer) == {'custom/extra.ab'}
    explorer.set_data(explorer.snapshot, catalog=explorer.catalog)
    assert explorer.file_type.currentData() == '自定义原始用途'
    assert visible_paths(explorer) == {'custom/extra.ab'}
    explorer.layer.setCurrentIndex(1)
    choose_type(explorer, '自定义生效用途')
    assert visible_paths(explorer) == {'anon/custom.bin'}
    # A selected label remains available when a newer observation lacks it.
    explorer.set_data(None, catalog=ResourceCatalog(explorer.catalog.installation))
    assert explorer.file_type.currentData() == '自定义生效用途'
    assert not visible_paths(explorer)


def test_clear_file_type_recovers_empty_results_without_changing_directory_source_or_recursion(explorer, qtbot):
    explorer.show()
    explorer.folder = 'avg/images'
    explorer.recursive.setChecked(True)
    explorer.layer.setCurrentIndex(1)
    choose_type(explorer, '剧情背景')
    explorer.ab_only.setChecked(True)
    explorer.search.setText('nothing-matches')
    assert '没有匹配' in explorer.empty_title.text()
    assert '文件类型' in explorer.empty.text()
    assert '全库' in explorer.empty.text() and '当前目录' not in explorer.empty.text()
    assert explorer.clear_filters_button.isVisible()
    qtbot.mouseClick(explorer.clear_filters_button, Qt.MouseButton.LeftButton)
    assert explorer.file_type.currentData() is None
    assert explorer.search.text() == '' and not explorer.ab_only.isChecked()
    assert explorer.folder == 'avg/images' and explorer.recursive.isChecked()
    assert explorer.layer.currentIndex() == 1
    assert visible_paths(explorer) == {'avg/images/current.AB', 'avg/images/missing'}
    assert explorer.tree.isEnabled() and explorer.recursive.isEnabled() and explorer.up_button.isEnabled()
    assert explorer.breadcrumb.text() == str(explorer.root / 'avg/images')


def test_catalog_only_global_filter_has_truthful_recoverable_empty_state(explorer):
    explorer.show()
    explorer.set_data(None, catalog=explorer.catalog)
    explorer.layer.setCurrentIndex(1)
    choose_type(explorer, '干员肖像')
    assert not visible_paths(explorer)
    assert '没有匹配' in explorer.empty_title.text()
    assert '全库' in explorer.empty.text()
    assert explorer.clear_filters_button.isVisible()
    explorer.clear_filters()
    assert len(visible_paths(explorer)) == 5


@pytest.mark.parametrize('layer', [0, 1])
def test_select_all_and_extraction_use_only_visible_type_results(explorer, layer):
    explorer.recursive.setChecked(True)
    explorer.layer.setCurrentIndex(layer)
    explorer.table.selectAll()
    choose_type(explorer, '剧情插图')
    assert explorer.selected_paths() == []
    explorer.select_all_button.click()
    emitted = []
    explorer.extract_requested.connect(emitted.append)
    explorer.extract_selected()
    expected = ({'avg/images/current.AB', 'avg/images/alternate.bin', 'avg/images/deep/nested.ab'} if layer == 0
                else {'anon/story.bin', 'avg/images/current.AB'})
    assert set(emitted[0]) == {str(explorer.root / path) for path in expected}


@pytest.mark.parametrize('layer', [0, 1])
def test_sorting_filtered_selection_keeps_preview_file_identity(explorer, layer):
    explorer.recursive.setChecked(True)
    explorer.layer.setCurrentIndex(layer)
    choose_type(explorer, '剧情插图')
    row = next(index for index, value in enumerate(explorer.model.rows) if value['path'] == 'avg/images/current.AB')
    explorer.table.selectRow(row)
    explorer.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    emitted = []
    explorer.objects_requested.connect(emitted.append)
    explorer.show_objects()
    assert emitted == [str(explorer.root / 'avg/images/current.AB')]


def test_explicit_recursive_directory_extraction_keeps_its_unfiltered_contract(explorer):
    explorer.folder = 'avg/images'
    explorer.ab_only.setChecked(True)
    choose_type(explorer, '剧情背景')
    assert visible_paths(explorer) == {'avg/backgrounds/backdrop.ab'}
    emitted = []
    explorer.extract_requested.connect(emitted.append)
    explorer.extract_directory()
    assert set(emitted[0]) == {str(explorer.root / path) for path in (
        'avg/images/current.AB', 'avg/images/alternate.bin', 'avg/images/deep/nested.ab')}


@pytest.mark.parametrize('width', [1000, 1050])
def test_file_type_controls_fit_supported_small_windows(qtbot, qapp, width):
    apply_theme(qapp)
    view = ExplorerView()
    qtbot.addWidget(view)
    view.resize(width, 480)
    view.show()
    qtbot.waitUntil(view.isVisible)
    assert view.width() <= width
    for control in (view.layer, view.search, view.ab_only, view.recursive, view.file_type):
        assert view.rect().contains(control.mapTo(view, QPoint(0, 0)))
        assert view.rect().contains(control.mapTo(view, control.rect().bottomRight()))
