"""Pure-module reports can produce one complete, bounded native PNG canvas."""
import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from arknights_unpacker.contracts import (CancelToken, CancelledError, EntityChangeSet,
    ExportFormat, ModuleProfile, OperatorProfile, ReportOptions, ReportSelection)
from arknights_unpacker.reports import compose_report, export_report
from arknights_unpacker.reports import render
from arknights_unpacker.reports.model import semantic_blocks


def module_document(layout="single", count=4):
    modules = []
    for index in range(1, count + 1):
        modules.append(ModuleProfile(f"equip_{index}", f"char_{index}", f"干员{index}",
            f"新增模组{index}", "X", phases=[
                {"level": level, "trait": f"模组{index}阶段{level}：" + "所有特性描述必须保留。" * 4 + f"阶段终点{index}{level}",
                 "attributes": [{"label": "生命上限", "value": 100 * level}, {"label": "攻击", "value": 20 * level}],
                 "talents": [{"name": f"天赋{index}{level}", "description": f"完整天赋效果{index}{level}", "potential_delta": "+2"}],
                 "token_attributes": {f"token_{index}": {"max_hp": 50 * level}}}
                for level in (1, 2, 3)], metadata={"version": "fixture-v1", "source": "本地夹具"}))
    changes = EntityChangeSet("before", "current", modules=[
        {"equip_id": f"equip_{count}", "name": f"新增模组{count}", "kind": "added",
         "changes": [{"field": "trait", "before": "旧内容", "after": "最终尾部终点"}]}])
    return compose_report(ReportSelection(modules=modules, changes=changes),
        ReportOptions(width=640, font_size=18, theme="light", max_page_height=600,
                      title="本次新增模组合集", module_image_layout=layout))


def export_manifest(tmp_path):
    return json.loads(next(tmp_path.rglob("manifest.json")).read_text("utf-8"))


def test_multiple_modules_render_one_complete_png_beyond_old_page_height(tmp_path, monkeypatch):
    document = module_document()
    drawn = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(draw, xy, text, *args, **kwargs):
        drawn.append((str(text), xy[1]))
        return original_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    completed = []
    paths = render.render_png(document, tmp_path, "merged", on_page=lambda path, pages: completed.append((path, pages)))
    assert len(paths) == 1, "Merged module selection must be exactly one complete PNG"
    assert list(tmp_path.glob("*.png")) == paths
    assert completed == [(paths[0], 1)]
    pages = render.layout_pages(document)
    assert len(pages) == 1
    with Image.open(paths[0]) as image:
        assert image.width == 640
        assert image.height > document.options.max_page_height
        assert image.width * image.height <= 80_000_000
        assert all(0 <= y < image.height for _, y in drawn)
        # The last semantic content is visibly above the one final footer.
        body_bottom = max(y for text, y in drawn if "最终尾部" in text or "终点" in text)
        footer_y = next(y for text, y in drawn if text.startswith("第 1 / 1 页"))
        assert body_bottom < footer_y
    actual = "".join(text for text, _ in drawn)
    for block in semantic_blocks(document):
        assert block.title.replace("\n", "") in actual
        for key, value in block.rows:
            assert f"{key}：{value}".replace("\n", "") in actual
        for row in [block.columns, *block.cells]:
            for cell in row:
                assert str(cell).replace("\n", "") in actual
    for index in range(1, 5):
        for level in (1, 2, 3):
            assert f"阶段终点{index}{level}" in actual
    assert "最终尾部终点" in actual
    assert actual.count(document.title) == 1
    assert sum(text.startswith("第 ") and " 页" in text for text, _ in drawn) == 1


def test_module_paged_option_keeps_existing_pagination(tmp_path):
    document = module_document("paged", count=2)
    pages = render.layout_pages(document)
    assert len(pages) > 1
    paths = render.render_png(document, tmp_path, "paged")
    assert len(paths) == len(pages)
    for path in paths:
        with Image.open(path) as image:
            assert image.height <= document.options.max_page_height


@pytest.mark.parametrize("include_modules", [False, True])
def test_single_module_option_does_not_change_operator_pagination(tmp_path, include_modules):
    document = module_document(count=1)
    if not include_modules:
        document.modules = []
    document.operators = [OperatorProfile("char_operator", "干员分页保持",
        skills=[{"name": "长技能", "description": "干员技能需要继续分页。" * 60 + "技能末尾仍在"}])]
    pages = render.layout_pages(document)
    assert len(pages) > 1
    assert "技能末尾仍在" in "".join(line.text for page in pages for line in page)
    paths = render.render_png(document, tmp_path, "operator")
    assert len(paths) == len(pages)
    with Image.open(paths[-1]) as image:
        assert image.height <= document.options.max_page_height


def test_oversized_single_image_fails_before_allocation_and_has_no_artifact(tmp_path, monkeypatch):
    document = module_document(count=1)
    monkeypatch.setattr(render, "layout_pages", lambda *args, **kwargs: [[render.DrawLine("too tall", 200_000)]])

    def forbidden_allocation(*args, **kwargs):
        pytest.fail("Oversized RGB canvas was allocated before the 80M pixel limit")

    monkeypatch.setattr(render.Image, "new", forbidden_allocation)
    with pytest.raises(ValueError, match="分页|减少"):
        export_report(document, tmp_path, {ExportFormat.PNG})
    manifest = export_manifest(tmp_path)
    assert manifest["status"] == "failed" and not manifest["complete"]
    assert manifest["artifacts"] == []
    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("*.tmp"))


def test_cancel_during_single_layout_has_no_false_artifact(tmp_path):
    token = CancelToken()

    def cancel_layout(event):
        if event.get("stage") == "report_layout" and event["current"] == 4:
            token.cancel()

    with pytest.raises(CancelledError):
        export_report(module_document(), tmp_path, {ExportFormat.PNG}, cancel=token, emit=cancel_layout)
    manifest = export_manifest(tmp_path)
    assert manifest["status"] == "cancelled" and not manifest["complete"]
    assert manifest["artifacts"] == []
    assert not list(tmp_path.rglob("*.png"))


def test_cancel_at_render_progress_does_not_allocate_canvas(tmp_path, monkeypatch):
    token = CancelToken()

    def cancel_render(event):
        if event.get("stage") == "report_png":
            token.cancel()

    def forbidden_allocation(*args, **kwargs):
        pytest.fail("Cancelled export allocated a new canvas")

    monkeypatch.setattr(render.Image, "new", forbidden_allocation)
    with pytest.raises(CancelledError):
        export_report(module_document(count=1), tmp_path, {ExportFormat.PNG}, cancel=token, emit=cancel_render)
    assert export_manifest(tmp_path)["artifacts"] == []
    assert not list(tmp_path.rglob("*.png"))


def test_cancel_during_drawing_closes_canvas_without_artifact(tmp_path, monkeypatch):
    token = CancelToken()
    original_text = ImageDraw.ImageDraw.text
    original_close = Image.Image.close
    closed = []

    def cancel_draw(draw, *args, **kwargs):
        result = original_text(draw, *args, **kwargs)
        token.cancel()
        return result

    def closed_image(image):
        closed.append(image)
        return original_close(image)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", cancel_draw)
    monkeypatch.setattr(Image.Image, "close", closed_image)
    with pytest.raises(CancelledError):
        export_report(module_document(count=1), tmp_path, {ExportFormat.PNG}, cancel=token)
    assert closed
    assert export_manifest(tmp_path)["artifacts"] == []
    assert not list(tmp_path.rglob("*.png"))


def test_failed_png_write_cleans_partial_canvas_and_receipt(tmp_path, monkeypatch):
    def fail_save(image, path, *args, **kwargs):
        Path(path).write_bytes(b"partial-png")
        raise OSError("disk full during png encoding")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        export_report(module_document(count=1), tmp_path, {ExportFormat.PNG})
    manifest = export_manifest(tmp_path)
    assert manifest["status"] == "failed" and manifest["artifacts"] == []
    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("*.tmp"))


def test_cancel_during_png_encoding_does_not_publish_unrecorded_file(tmp_path, monkeypatch):
    token = CancelToken()
    original_save = Image.Image.save

    def cancel_save(image, path, *args, **kwargs):
        original_save(image, path, *args, **kwargs)
        token.cancel()

    monkeypatch.setattr(Image.Image, "save", cancel_save)
    with pytest.raises(CancelledError):
        export_report(module_document(count=1), tmp_path, {ExportFormat.PNG}, cancel=token)
    manifest = export_manifest(tmp_path)
    assert manifest["status"] == "cancelled" and manifest["artifacts"] == []
    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("*.tmp"))


def test_insufficient_memory_has_actionable_message_and_no_artifact(tmp_path, monkeypatch):
    def fail_allocation(*args, **kwargs):
        raise MemoryError("actual allocation failed")

    monkeypatch.setattr(render.Image, "new", fail_allocation)
    with pytest.raises(ValueError, match="内存不足.*分页"):
        export_report(module_document(count=1), tmp_path, {ExportFormat.PNG})
    assert export_manifest(tmp_path)["status"] == "failed"
    assert export_manifest(tmp_path)["artifacts"] == []
    assert not list(tmp_path.rglob("*.png"))


def test_cancel_after_single_png_keeps_exact_complete_artifact_in_manifest(tmp_path):
    token = CancelToken()

    def cancel_after_output(event):
        if event.get("format") == "png" and event.get("status") == "succeeded":
            token.cancel()

    with pytest.raises(CancelledError):
        export_report(module_document(count=2), tmp_path, {ExportFormat.PNG}, cancel=token, emit=cancel_after_output)
    manifest = export_manifest(tmp_path)
    assert manifest["status"] == "cancelled" and not manifest["complete"]
    assert len(manifest["artifacts"]) == len(list(tmp_path.rglob("*.png"))) == 1
    assert manifest["artifacts"][0]["pages"] == 1
