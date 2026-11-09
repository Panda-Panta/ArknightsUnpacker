"""Save the original image bytes from either preview dialog."""
from pathlib import Path
import shutil

from PySide6.QtWidgets import QFileDialog, QMessageBox

from arknights_unpacker.paths import validate_output


def input_roots(parent, source_package=None):
    """Capture the selected installation while a preview is opened."""
    roots = []
    while parent is not None:
        services = getattr(parent, 'services', None)
        installation = getattr(services, 'installation', None)
        if installation is not None:
            roots.append(Path(installation.root).resolve())
        root_edit = getattr(parent, 'root_edit', None)
        if root_edit is not None and root_edit.text().strip():
            roots.append(Path(root_edit.text().strip()).expanduser().resolve())
        parent = parent.parentWidget()
    if source_package:
        roots.append(Path(source_package).expanduser().resolve().parent)
    return tuple(dict.fromkeys(roots))


def _save_start(parent, source):
    while parent is not None:
        settings = getattr(parent, 'settings', None)
        if settings is not None and settings.output.text().strip():
            return Path(settings.output.text().strip()) / source.name
        parent = parent.parentWidget()
    return Path.home() / 'Pictures' / source.name


def _copy_original_image(source, destination, input_roots, preview_roots=()):
    """Copy encoded bytes, never the scaled QLabel pixmap or a re-encoded image."""
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError('原始图片文件不存在。请重新预览后保存。')
    target = Path(destination).expanduser()
    if not target.suffix:
        target = target.with_suffix(source.suffix)
    same_format = {source.suffix.lower()}
    if source.suffix.lower() in {'.jpg', '.jpeg'}:
        same_format.update({'.jpg', '.jpeg'})
    if target.suffix.lower() not in same_format:
        raise ValueError(f'保存原图保留原始文件格式，请使用 {source.suffix} 扩展名。')
    target = validate_output(target)
    for root in input_roots:
        validate_output(target, root)
    for root in preview_roots:
        if target.is_relative_to(Path(root).resolve()):
            raise ValueError('预览缓存会自动清理，请选择正式输出目录保存原图。')
    if target.exists():
        raise FileExistsError('目标文件已存在，请选择其他文件名；已有文件会保留。')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects a destination created after the dialog.
    with target.open('xb') as output:
        try:
            with source.open('rb') as original:
                shutil.copyfileobj(original, output)
        except BaseException:
            output.close()
            target.unlink(missing_ok=True)
            raise
    return target


def choose_original_save(dialog, source, input_roots, preview_roots):
    source = Path(source)
    filename, _ = QFileDialog.getSaveFileName(dialog, '保存原图（保留原始像素）',
        str(_save_start(dialog.parentWidget(), source)), f'原始图片 (*{source.suffix.lower()})',
        options=QFileDialog.Option.DontConfirmOverwrite)
    if not filename:
        return None
    preview_roots = list(preview_roots)
    parent = dialog.parentWidget()
    while parent is not None:
        preview_roots.extend(getattr(getattr(parent, 'preview_cache', None), 'roots', ()))
        parent = parent.parentWidget()
    try:
        return _copy_original_image(source, filename, input_roots, preview_roots)
    except (OSError, ValueError) as error:
        QMessageBox.warning(dialog, '无法保存原图', str(error))
        return None
