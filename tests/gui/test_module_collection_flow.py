"""Exercise the real report service through the module page and its job queue."""
import json
from pathlib import Path

from PIL import Image

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import (
    DecodedTable, EntityChangeSet, GameInstallation, TableSourceSet,
)
from arknights_unpacker.gamedata import load_gamedata
from arknights_unpacker.ui.main_window import MainWindow


def test_new_modules_button_exports_one_named_collection(qtbot, tmp_path):
    fixture = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text('utf-8'))
    data = load_gamedata(TableSourceSet(
        tables={name: DecodedTable(name, raw) for name, raw in fixture['tables'].items()},
        version=fixture['version'], resource_version=fixture['resource_version'], locale='zh_CN'))
    game = tmp_path / 'game'
    game.mkdir()
    services = AppServices(tmp_path / 'data', output_root=tmp_path / 'exports')
    services.config['game_root'] = ''
    services.installation = GameInstallation(game, 'controlled-profile')
    services.gamedata = data
    rows = services.modules()
    assert len(rows) >= 3
    added = [row['id'] for row in rows[:2]]
    modified = rows[2]['id']
    # Controlled comparison only: this test does not observe a server update.
    services.entity_changes = EntityChangeSet('controlled-before', data.snapshot_id,
        modules=[{'equip_id': item, 'kind': 'added'} for item in added] +
                [{'equip_id': modified, 'kind': 'modified'}])
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.root_edit.setText(str(game))
    window.refresh_entities()
    window.show()
    try:
        window.modules.search.setText(rows[0]['name'])
        assert window.modules.export_new.isEnabled()
        window.modules.export_new.click()
        qtbot.waitUntil(lambda: not window.queue.busy and
                       all(job.status != '排队中' for job in window.queue.jobs), timeout=30000)
        job = window.queue.jobs[-1]
        assert job.status == '成功', (job.status, job.error)
        pngs = [artifact for artifact in job.artifacts if artifact.format == 'png']
        htmls = [artifact for artifact in job.artifacts if artifact.format == 'html']
        assert len(pngs) == len(htmls) == 1
        assert pngs[0].pages == 1
        with Image.open(pngs[0].path) as image:
            image.verify()
        html = Path(htmls[0].path).read_text('utf-8')
        assert '<title>本次新增模组</title>' in html
        payload = json.loads(next(Path(a.path) for a in job.artifacts if a.format == 'json').read_text('utf-8'))
        assert payload['title'] == '本次新增模组'
        assert {module['equip_id'] for module in payload['modules']} == set(added)
        assert {change['equip_id'] for change in payload['metadata']['changes']['modules']} == set(added)
        assert job.request['options']['module_image_layout'] == 'single'
        assert job.request['options']['title'] == '本次新增模组'
        assert len(services.entity_changes.modules) == 3
        assert window._dialogs[-1].pages.count() == 1
    finally:
        window.close()
        services.shutdown()
