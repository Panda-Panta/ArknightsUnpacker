from arknights_unpacker.contracts import EntityChangeSet, ExportFormat
from test_explorer import make_window, wait_idle


def test_sort_preserves_selected_export_identity(qtbot):
    from PySide6.QtCore import Qt
    from arknights_unpacker.ui.entity_view import EntityView
    from arknights_unpacker.ui.models import selected_records
    view = EntityView()
    qtbot.addWidget(view)
    view.set_rows([{'id': 'a', 'name': 'Alpha'}, {'id': 'b', 'name': 'Beta'}])
    view.model.sort(0, Qt.SortOrder.AscendingOrder)
    view.table.selectRow(0)
    assert selected_records(view.table)[0]['id'] == 'a'
    view.model.sort(0, Qt.SortOrder.DescendingOrder)
    assert selected_records(view.table)[0]['id'] == 'a'
    exports = []
    view.export_requested.connect(lambda ids, new: exports.append(ids))
    view.request_export(False)
    assert exports == [['a']]


def test_switch_operator_resets_previous_module_with_real_reference(qtbot):
    import json
    from pathlib import Path
    from arknights_unpacker.contracts import DecodedTable, TableSourceSet, BuildSpec
    from arknights_unpacker.gamedata import load_gamedata, build_operator
    from arknights_unpacker.ui.entity_view import EntityView
    fixture = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text(encoding='utf-8'))
    data = load_gamedata(TableSourceSet(tables={name: DecodedTable(name, raw) for name, raw in fixture['tables'].items()},
                                      version=fixture['version'], resource_version=fixture['resource_version']))
    view = EntityView()
    qtbot.addWidget(view)
    view.set_rows([{'id': 'char_103_angel', 'name': '能天使'}, {'id': 'char_4231_clemnt', 'name': '克莱门莎'}])
    requests = []
    view.profile_requested.connect(lambda entity_id, spec: requests.append((entity_id, spec)))
    view.table.selectRow(0)
    view.set_profile(build_operator(data, 'char_103_angel'))
    view.module_choice.setCurrentIndex(1)
    angel_spec = requests[-1][1]
    assert angel_spec.module_id == 'uniequip_002_angel'
    view.set_profile(build_operator(data, 'char_103_angel', angel_spec))
    # A module change on the same operator remains selected.
    assert view.module_choice.currentData() == 'uniequip_002_angel'
    view.table.selectRow(1)
    entity_id, spec = requests[-1]
    assert entity_id == 'char_4231_clemnt'
    assert spec.module_id is None
    assert view.current_profile is None
    assert '能天使' not in view.details.toPlainText()
    view.set_profile(build_operator(data, entity_id, spec))
    assert view.current_profile.name == '克莱门莎'


def test_png_report_pages_zoom_and_html_requires_explicit_action(qtbot, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from arknights_unpacker.contracts import ReportArtifact
    from arknights_unpacker.ui.report_preview import ReportArtifactsDialog
    artifacts = []
    for page, height in [(1, 500), (2, 300)]:
        path = tmp_path / f'page-{page}.png'
        image = QImage(200, height, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        assert image.save(str(path))
        artifacts.append(ReportArtifact(str(path), 'png', pages=2))
    html = tmp_path / 'report.html'
    html.write_text('<html><body>测试</body></html>', encoding='utf-8')
    artifacts.append(ReportArtifact(str(html), 'html'))
    dialog = ReportArtifactsDialog(artifacts)
    qtbot.addWidget(dialog)
    opened = []
    dialog.html_open_requested.connect(opened.append)
    dialog.show()
    assert dialog.pages.count() == 2
    assert not opened
    dialog.zoom.setValue(200)
    assert dialog.image.width() == 400
    assert dialog.image.height() == 1000
    dialog.pages.setCurrentIndex(1)
    assert dialog.image.height() == 600
    assert dialog.scroll.widget() is dialog.image
    qtbot.mouseClick(dialog.open_html, Qt.MouseButton.LeftButton)
    assert opened == [str(html)]  # Signal only: this test never launches a browser.


def test_preview_exports_to_private_cache_and_task_can_reopen_artifacts(qtbot, tmp_path):
    from pathlib import Path
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    user_output = window.settings.output.text()
    window.preview_reports('operators', ['char_fixture'])
    wait_idle(qtbot, window)
    call = next(c for c in services.calls if c[0] == 'export')
    assert Path(call[3]).is_relative_to(services.data_root / 'previews')
    assert ExportFormat.PNG in call[4]
    assert services.config['output_root'] == user_output
    assert window._dialogs[-1].export_button.isVisible()
    first_count = len(window._dialogs)
    original = window._dialogs[-1]
    window.show_task_history().table.selectRow(len(window.queue.jobs) - 1)
    window.jobs.preview_artifacts()
    assert len(window._dialogs) == first_count
    assert window._dialogs[-1] is original and original.isVisible()


def test_real_reference_detail_uses_readable_report_blocks_and_keeps_evidence(qtbot):
    import json
    from pathlib import Path
    from PySide6.QtWidgets import QTextBrowser
    from arknights_unpacker.contracts import DecodedTable, TableSourceSet, as_jsonable
    from arknights_unpacker.gamedata import load_gamedata, build_operator
    from arknights_unpacker.ui.report_preview import profile_html
    fixture = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text(encoding='utf-8'))
    data = load_gamedata(TableSourceSet(tables={name: DecodedTable(name, raw) for name, raw in fixture['tables'].items()},
                                      version=fixture['version'], resource_version=fixture['resource_version']))
    profile = build_operator(data, 'char_4231_clemnt')
    profile.metadata['field_evidence'] = {'getter': {'raw-internal-getter-sentinel': list(range(1000))}}
    profile.metadata['sources'] = {'dictionary': {'raw-internal-source-sentinel': 'evidence'}}
    profile.diagnostics.append('可读诊断测试')
    original = as_jsonable(profile)
    browser = QTextBrowser()
    qtbot.addWidget(browser)
    html = profile_html(profile)
    browser.setHtml(html)
    text = browser.toPlainText()
    assert '克莱门莎' in text and '1065' in text and '21' in text
    assert '合作原则' in text and '谈判技巧' in text
    assert '初始技力' in text and '专精3' in text
    assert '来源与诊断' not in text and '可读诊断测试' not in text
    assert 'raw-internal-getter-sentinel' not in text
    assert 'raw-internal-source-sentinel' not in text
    assert 'field_evidence' not in text and 'getter' not in text
    assert as_jsonable(profile) == original  # Full evidence remains available to JSON export.
    profile.name = '<img src=x onerror=alert(1)>'
    escaped = profile_html(profile)
    assert '<img src=x' not in escaped
    assert '&lt;img src=x' in escaped


def test_first_inventory_never_becomes_all_new(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    window.refresh_entities()
    assert window.operators.model.rows[0]['status'] == 'unknown'
    assert not window.operators.export_new.isEnabled()
    window.operators.only_new.setChecked(True)
    assert window.operators.model.rowCount() == 0


def test_comparable_current_records_do_not_count_as_changes(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    services.entity_changes = EntityChangeSet('baseline', 'data1')
    rows = services.operators()
    rows[0]['status'] = 'current'
    window.operators.set_rows(rows, services.entity_changes, services.gamedata)
    window.operators.only_new.setChecked(True)
    assert window.operators.model.rowCount() == 0


def test_locale_settings_and_blocked_comparison_diagnostics(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    assert window.settings.data_locale.currentData() == 'unknown'
    window.settings.data_locale.setCurrentIndex(window.settings.data_locale.findData('zh_CN'))
    window.settings.commit()
    assert services.config['data_locale'] == 'zh_CN'
    services.load_data(str(tmp_path))
    services.gamedata.locale = 'unknown'
    warning = '区服未知且来源不同：无法确认同服，不认定新增。'
    services.entity_changes = EntityChangeSet('external-baseline', 'data1', diagnostics=[warning])
    window.refresh_entities()
    assert '区服未知' in window.operators.summary.text()
    assert warning in window.operators.diagnostics.text()
    assert warning in window.modules.diagnostics.text()
    assert not window.operators.export_new.isEnabled()
    assert window.operators.model.rows[0]['status'] == 'unknown'


def test_same_installation_unknown_locale_hint_does_not_block_valid_changes(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    services.gamedata.locale = 'unknown'
    hint = '区服未知；已确认同一安装，可比较两次观测。'
    services.entity_changes = EntityChangeSet('same-profile-baseline', 'data1',
        operators=[{'id': 'char_fixture', 'kind': 'added'}], diagnostics=[hint])
    window.refresh_entities()
    assert hint in window.operators.diagnostics.text()
    assert window.operators.export_new.isEnabled()
    services.gamedata.locale = 'zh_CN'
    window.refresh_entities()
    assert '简体中文／国服' in window.operators.summary.text()


def test_baseline_new_export_passes_formats_and_selection(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    services.entity_changes = EntityChangeSet('baseline-v0', 'data1', operators=[{'id': 'char_fixture', 'kind': 'added'}])
    window.refresh_entities()
    assert window.operators.export_new.isEnabled()
    window.operators.request_export(True)
    wait_idle(qtbot, window)
    call = next(c for c in services.calls if c[0] == 'export')
    assert call[1] == ['char_fixture']
    assert call[2] == []
    assert {ExportFormat.PNG, ExportFormat.HTML, ExportFormat.JSON, ExportFormat.TXT} == call[4]


def test_profile_display_and_module_selection_stays_single(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    services.load_data(str(tmp_path))
    window.refresh_entities()
    window.operators.table.selectRow(0)
    wait_idle(qtbot, window)
    assert '测试技能' in window.operators.details.toPlainText()
    assert '<测试文本>' in window.operators.details.toPlainText()
    assert window.operators.module_choice.currentData() is None


def test_output_inside_game_is_refused_without_service_call(qtbot, tmp_path):
    window, services = make_window(qtbot, tmp_path)
    window.root_edit.setText(str(tmp_path))
    window.settings.output.setText(str(tmp_path / 'unsafe-output'))
    window.extract([str(tmp_path / 'sample.ab')])
    assert not any(call[0] == 'extract' for call in services.calls)
    assert '不能位于游戏目录' in window.statusBar().currentMessage()
