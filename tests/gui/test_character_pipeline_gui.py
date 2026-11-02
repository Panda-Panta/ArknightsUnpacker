from copy import deepcopy
from pathlib import Path
import time
import pytest

from PIL import Image

from arknights_unpacker.contracts import ExtractionResult
from arknights_unpacker.ui.character_workbench import CharacterWorkbench
from test_character_workbench import catalog
from test_explorer import make_window, wait_idle


def prepare(qtbot, tmp_path, *, delay=0):
    window, services = make_window(qtbot, tmp_path)
    services.character_catalog = lambda path, **kw: catalog()
    calls = []

    def extract(paths, output, **kwargs):
        calls.append((list(paths), output, deepcopy(kwargs.get('character_options')), kwargs.get('kinds'), kwargs.get('remember_output')))
        if delay:
            time.sleep(delay)
        target = Path(output) / 'composition.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        options = kwargs.get('character_options') or {}
        Image.new('RGBA', (30, 40), (int(options.get('x', 0)) % 255, 60, 100, 180)).save(target)
        return ExtractionResult(outputs=[{'path': str(target), 'kind': 'character_expression'}])

    services.extract = extract
    return window, services, calls


def open_workbench(qtbot, window, path):
    window.character_workbench([str(path)])
    wait_idle(qtbot, window)
    return next(dialog for dialog in window._dialogs if isinstance(dialog, CharacterWorkbench))


def test_character_preview_and_export_keep_options_page_and_hidden_metadata_read(qtbot, tmp_path):
    window, services, calls = prepare(qtbot, tmp_path)
    window.pages.select('explorer')
    page = window.tabs.currentWidget()
    original_output = services.config['output_root']
    dialog = open_workbench(qtbot, window, tmp_path / 'hero.ab')
    reads = [job for job in window.queue.jobs if job.title.startswith('读取角色表情配置 · ')]
    assert reads and all(not job.show_in_tasks for job in reads)
    qtbot.waitUntil(lambda: dialog.export_button.isEnabled(), timeout=5000)
    assert dialog.export_button.isEnabled()
    assert calls[-1][2] == dialog.current_options() and calls[-1][3] == ['expression']
    assert calls[-1][4] is False
    preview_pixels = Image.open(dialog.preview_panel.current_path).tobytes()
    assert services.config['output_root'] == original_output
    dialog.request_export()
    wait_idle(qtbot, window)
    assert calls[-1][4] is True
    assert calls[-1][2] == dialog.successful_options
    assert Image.open(Path(calls[-1][1]) / 'composition.png').tobytes() == preview_pixels
    assert window.tabs.currentWidget() is page
    assert window.queue.jobs[-1].request['character_options'] == dialog.successful_options
    dialog.batch_button.click()
    wait_idle(qtbot, window)
    assert calls[-1][2] is None and calls[-1][3] == ['expression']
    dialog.close()


def test_latest_character_preview_preserves_explicit_kind_and_manual_options(qtbot, tmp_path):
    window, _, calls = prepare(qtbot, tmp_path, delay=.5)
    dialog = open_workbench(qtbot, window, tmp_path / 'hero.ab')
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=5000)
    original_x = dialog.x_spin.value()
    for change in (1, 3, 8):
        dialog.x_spin.setValue(original_x + change)
    wanted = dialog.current_options()
    qtbot.waitUntil(lambda: dialog in window._object_preview_pending, timeout=5000)
    assert len(calls) == 1
    qtbot.waitUntil(lambda: len(calls) == 2 and dialog.export_button.isEnabled(), timeout=5000)
    assert calls[-1][2] == wanted and calls[-1][3] == ['expression']
    assert dialog.successful_options == wanted
    lease = dialog._current_preview_lease
    dialog.close()
    qtbot.waitUntil(lambda: lease.cleaned)


def test_multiple_character_packages_use_configuration_batch_without_opening_manual_window(qtbot, tmp_path):
    window, _, calls = prepare(qtbot, tmp_path)
    paths = [str(tmp_path / name) for name in ('one.ab', 'two.ab')]
    window.character_workbench(paths)
    wait_idle(qtbot, window)
    assert calls[-1][0] == paths and calls[-1][2] is None and calls[-1][3] == ['expression']
    assert not any(isinstance(dialog, CharacterWorkbench) for dialog in window._dialogs)


@pytest.mark.parametrize('operation', ['catalog', 'preview'])
def test_closing_character_workbench_cancels_only_its_pending_work(qtbot, tmp_path, operation):
    window, services, _ = prepare(qtbot, tmp_path)
    entered = []

    def slow(*args, **kwargs):
        entered.append(True)
        while True:
            kwargs['cancel'].check()
            time.sleep(.005)

    if operation == 'catalog':
        services.character_catalog = slow
        window.character_workbench([str(tmp_path / 'hero.ab')])
        dialog = next(dialog for dialog in window._dialogs if isinstance(dialog, CharacterWorkbench))
    else:
        services.extract = slow
        window.character_workbench([str(tmp_path / 'hero.ab')])
        dialog = next(dialog for dialog in window._dialogs if isinstance(dialog, CharacterWorkbench))
    qtbot.waitUntil(lambda: bool(entered))
    job = window.queue.active
    dialog.close()
    qtbot.waitUntil(lambda: not window.queue.busy, timeout=5000)
    assert job.token.cancelled and job.status == '已取消'


def test_close_before_automatic_preview_fires_creates_no_late_task(qtbot, tmp_path):
    window, _, calls = prepare(qtbot, tmp_path)
    dialog = open_workbench(qtbot, window, tmp_path / 'hero.ab')
    dialog.close()
    qtbot.wait(350)
    assert calls == []
