from __future__ import annotations
from dataclasses import replace
from html import escape
from pathlib import Path
import shutil
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QPushButton, QTextBrowser, QSplitter, QAbstractItemView, QScrollArea, QComboBox, QDoubleSpinBox, QFileDialog, QMessageBox, QWidget, QCheckBox
from arknights_unpacker.contracts import ReportDocument, OperatorProfile, ModuleProfile, ReportOptions
from arknights_unpacker.paths import validate_output
from arknights_unpacker.reports.model import semantic_blocks
from .models import RecordsModel, selected_records, size_text, value


def _input_roots(parent, source_package=None):
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


def _choose_original_save(dialog, source):
    source = Path(source)
    filename, _ = QFileDialog.getSaveFileName(dialog, '保存原图（保留原始像素）',
        str(_save_start(dialog.parentWidget(), source)), f'原始图片 (*{source.suffix.lower()})',
        options=QFileDialog.Option.DontConfirmOverwrite)
    if not filename:
        return None
    preview_roots = list(getattr(dialog, '_preview_cache_roots', ()))
    parent = dialog.parentWidget()
    while parent is not None:
        preview_roots.extend(getattr(getattr(parent, 'preview_cache', None), 'roots', ()))
        parent = parent.parentWidget()
    try:
        return _copy_original_image(source, filename, dialog._input_roots,
                                    preview_roots)
    except (OSError, ValueError) as error:
        QMessageBox.warning(dialog, '无法保存原图', str(error))
        return None


class ReportArtifactsDialog(QDialog):
    """Inspect exactly the returned report files; browser launch is an explicit action."""
    html_open_requested = Signal(str)
    export_requested = Signal()
    font_preview_requested = Signal(object, int)

    def __init__(self, artifacts, parent=None, *, preview_only=False, preview_lease=None, report_options=None):
        super().__init__(parent)
        self.artifacts = list(artifacts)
        self.preview_closed = False
        self.preview_generation = 0
        self.successful_options = replace(report_options or ReportOptions())
        self._requested_options = self.successful_options
        self.preview_only = preview_only
        self._preview_lease = preview_lease
        self._preview_cache_roots = tuple(preview_lease.cache.roots) if preview_lease else ()
        self._pixmap = QPixmap()
        self._input_roots = _input_roots(parent)
        self.finished.connect(self._release_preview)
        self.setWindowTitle('资料预览' if preview_only else '本次资料导出产物')
        self.resize(1150, 850)
        layout = QVBoxLayout(self)
        self._summary_intro = ('临时预览在关闭后清理，浏览器已打开的 HTML 保留至程序退出；点击“导出所选到输出目录”保存完整资料。'
                               if preview_only else '本次生成的图片、HTML 与来源文件。')
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.font_picker = None
        self._font_refresh_timer = QTimer(self)
        self._font_refresh_timer.setSingleShot(True)
        self._font_refresh_timer.setInterval(150)
        self._font_refresh_timer.timeout.connect(lambda: self.font_preview_requested.emit(
            replace(self._requested_options), self.preview_generation) if not self.preview_closed else None)
        if preview_only:
            from .font_picker import ExportFontPicker
            font_row = QHBoxLayout()
            font_row.addWidget(QLabel('本次资料字体'))
            self.font_picker = ExportFontPicker(self)
            self.font_picker.set_font(self.successful_options.font_path, self.successful_options.font_index)
            self.font_picker.font_changed.connect(self.request_font_preview)
            font_row.addWidget(self.font_picker, 1)
            layout.addLayout(font_row)
        self.font_status = QLabel('切换字体仅影响本次预览和导出，不更改全局设置。')
        self.font_status.setWordWrap(True)
        self.font_status.setVisible(preview_only)
        layout.addWidget(self.font_status)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('PNG 页'))
        self.pages = QComboBox()
        self.pages.setObjectName('reportPngPages')
        toolbar.addWidget(self.pages, 1)
        self.previous = QPushButton('上一页')
        self.previous.clicked.connect(lambda: self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1)))
        toolbar.addWidget(self.previous)
        self.next = QPushButton('下一页')
        self.next.clicked.connect(lambda: self.pages.setCurrentIndex(min(self.pages.count() - 1, self.pages.currentIndex() + 1)))
        toolbar.addWidget(self.next)
        self.zoom = QDoubleSpinBox()
        self.zoom.setObjectName('reportZoom')
        self.zoom.setToolTip('仅改变查看比例；保存 PNG 保留生成时的原始像素。')
        self.zoom.setRange(10, 300)
        self.zoom.setDecimals(0)
        self.zoom.setSuffix(' %')
        self.zoom.setValue(75)
        self.zoom.valueChanged.connect(self.update_image)
        toolbar.addWidget(self.zoom)
        fit = QPushButton('适应宽度')
        fit.clicked.connect(self.fit_width)
        toolbar.addWidget(fit)
        self.save_original_button = QPushButton('保存当前原始 PNG…')
        self.save_original_button.setObjectName('saveReportPng')
        self.save_original_button.setToolTip('复制当前 PNG 原文件，保留原始像素和内容。')
        self.save_original_button.clicked.connect(self.save_original)
        toolbar.addWidget(self.save_original_button)
        layout.addLayout(toolbar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.image = QLabel()
        self.image.setProperty('imageCanvas', True)
        self.image.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.image)
        layout.addWidget(self.scroll, 1)
        self.image_status = QLabel('')
        layout.addWidget(self.image_status)
        self.files_model = RecordsModel([('格式', 'format'), ('文件名', lambda a: Path(value(a, 'path', '')).name),
                                         ('状态', 'status'), ('完整路径', 'path')], self)
        self.files_model.replace(self.artifacts)
        self.files = QTableView()
        self.files.setModel(self.files_model)
        self.files.horizontalHeader().setStretchLastSection(True)
        self.files.setMaximumHeight(155)
        self.files.setColumnWidth(1, 320)
        layout.addWidget(self.files)
        html_row = QHBoxLayout()
        html_row.addWidget(QLabel('HTML 资料'))
        self.html_files = QComboBox()
        html_row.addWidget(self.html_files, 1)
        self.open_html = QPushButton('在浏览器中打开')
        self.open_html.setObjectName('openReportHtml')
        self.open_html.clicked.connect(self.request_html)
        html_row.addWidget(self.open_html)
        layout.addLayout(html_row)
        footer = QHBoxLayout()
        self.export_button = QPushButton('导出所选到输出目录')
        self.export_button.setProperty('primary', True)
        self.export_button.setVisible(preview_only)
        self.export_button.clicked.connect(self.export_requested)
        footer.addWidget(self.export_button)
        footer.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.pages.currentIndexChanged.connect(self.select_page)
        self._set_artifacts(self.artifacts)

    def _set_artifacts(self, artifacts):
        page_index = max(0, self.pages.currentIndex())
        self.artifacts = list(artifacts)
        self.summary.setText(self._summary_intro + f'　共 {len(self.artifacts)} 个文件。缩放只影响预览。')
        self.files_model.replace(self.artifacts)
        self.pages.blockSignals(True)
        self.pages.clear()
        self.html_files.clear()
        for artifact in self.artifacts:
            path = str(value(artifact, 'path', ''))
            fmt = str(value(artifact, 'format', '')).lower()
            if fmt == 'png':
                self.pages.addItem(f'{self.pages.count() + 1} · {Path(path).name}', path)
            elif fmt == 'html':
                self.html_files.addItem(Path(path).name, path)
        self.pages.setCurrentIndex(min(page_index, self.pages.count() - 1))
        self.pages.blockSignals(False)
        self.open_html.setEnabled(self.html_files.count() > 0)
        self.select_page()

    def request_font_preview(self, path, index=0):
        if not self.preview_only or self.preview_closed:
            return
        self.preview_generation += 1
        self._requested_options = replace(self.successful_options, font_path=path, font_index=index)
        self.export_button.setEnabled(False)
        self.font_status.setText('正在生成所选字体的预览…')
        self._font_refresh_timer.start()

    def replace_artifacts(self, artifacts, *, preview_lease, report_options, generation):
        if self.preview_closed or generation != self.preview_generation:
            preview_lease.release()
            return False
        old_lease = self._preview_lease
        self._preview_lease = preview_lease
        self._preview_cache_roots = tuple(preview_lease.cache.roots)
        self._pixmap = QPixmap()
        self._set_artifacts(artifacts)
        self.successful_options = replace(report_options)
        self.font_picker.set_font(report_options.font_path, report_options.font_index)
        self.font_status.setText('字体预览已更新；导出将使用当前预览的字体。')
        self.export_button.setEnabled(True)
        if old_lease:
            old_lease.release()
        return True

    def font_preview_failed(self, message, *, generation):
        if self.preview_closed or generation != self.preview_generation:
            return
        detail = next((line for line in reversed(str(message).splitlines()) if line.strip()), '生成失败')
        self.font_picker.set_font(self.successful_options.font_path, self.successful_options.font_index)
        self._requested_options = replace(self.successful_options)
        self.font_status.setText('字体预览失败：' + detail + '。已恢复上次成功的字体和图片，可重新选择字体重试。')
        self.font_status.setToolTip(str(message))
        self.export_button.setEnabled(True)

    def select_page(self, *_):
        path = self.pages.currentData()
        self._pixmap = QPixmap(str(path)) if path else QPixmap()
        self.previous.setEnabled(self.pages.currentIndex() > 0)
        self.next.setEnabled(0 <= self.pages.currentIndex() < self.pages.count() - 1)
        self.zoom.setEnabled(not self._pixmap.isNull())
        self.save_original_button.setEnabled(not self._pixmap.isNull())
        if self._pixmap.isNull():
            self.image.clear()
            self.image.resize(1, 1)
            self.image_status.setText('当前没有 PNG 产物。可查看文件列表与 HTML 资料。' if not path else 'PNG 无法读取；请检查文件是否仍然存在。')
        else:
            self.image_status.setText(f'{self.pages.currentIndex() + 1} / {self.pages.count()} 页　·　{self._pixmap.width()} × {self._pixmap.height()} 像素　·　{path}')
            self.update_image()

    def update_image(self, *_):
        if self._pixmap.isNull():
            return
        scale = self.zoom.value() / 100
        rendered = self._pixmap.scaled(max(1, round(self._pixmap.width() * scale)), max(1, round(self._pixmap.height() * scale)),
                                       Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image.setPixmap(rendered)
        self.image.resize(rendered.size())

    def fit_width(self):
        if not self._pixmap.isNull():
            self.zoom.setValue((self.scroll.viewport().width() - 16) / self._pixmap.width() * 100)

    def request_html(self):
        path = self.html_files.currentData()
        if path:
            if self._preview_lease:
                self._preview_lease.defer_until_exit()
            self.html_open_requested.emit(str(path))

    def _release_preview(self, *_):
        if self.preview_closed:
            return
        self.preview_closed = True
        self._font_refresh_timer.stop()
        self._pixmap = QPixmap()
        self.image.clear()
        self.save_original_button.setEnabled(False)
        if self._preview_lease:
            self._preview_lease.release()

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self._release_preview()

    def save_original(self):
        path = self.pages.currentData()
        if path and not self._pixmap.isNull():
            saved = _choose_original_save(self, path)
            if saved:
                self.image_status.setText(f'已保存原始 PNG　·　{self._pixmap.width()} × {self._pixmap.height()} 像素　·　{saved}')

def _escaped_text(text):
    return escape(str(text), quote=True).replace('\n', '<br>')


PROFILE_ANCHOR_PREFIX = 'profile-section-'


def blocks_html(blocks, *, anchor_prefix=None):
    """Qt's rich text subset: no scripts, remote assets, or recursive raw evidence."""
    parts = []
    for index, block in enumerate(blocks, 1):
        anchor = '<a name="' + _escaped_text(f'{anchor_prefix}{index}') + '"></a>' if anchor_prefix else ''
        parts.append('<h2>' + anchor + _escaped_text(block.title) + '</h2>')
        if block.rows:
            parts.append('<table border="1" cellspacing="0" cellpadding="5" width="100%">')
            for key, text in block.rows:
                parts.append('<tr><th align="left" valign="top">' + _escaped_text(key) + '</th><td>' + _escaped_text(text) + '</td></tr>')
            parts.append('</table>')
        if block.columns:
            parts.append('<table border="1" cellspacing="0" cellpadding="4" width="100%"><tr>')
            parts.extend('<th>' + _escaped_text(column) + '</th>' for column in block.columns)
            parts.append('</tr>')
            for row in block.cells:
                parts.append('<tr>' + ''.join('<td>' + _escaped_text(cell) + '</td>' for cell in row) + '</tr>')
            parts.append('</table>')
        parts.extend('<p style="font-size:10px; color:#607786;"><b>' + _escaped_text(term) + '：</b>'
                     + _escaped_text(text) + '</p>' for term, text in block.notes)
    return ''.join(parts)


def profile_html(profile, *, blocks=None):
    document = ReportDocument(title=profile.name,
        operators=[profile] if isinstance(profile, OperatorProfile) else [],
        modules=[profile] if isinstance(profile, ModuleProfile) else [])
    if blocks is None:
        blocks = semantic_blocks(document)
    badge = '<div style="font-size:10px; font-weight:700; color:#0093a2; letter-spacing:1px; margin-bottom:4px;">PRTS // LOCAL DOSSIER ARCHIVE</div>'
    body = '<a name="' + PROFILE_ANCHOR_PREFIX + '0"></a>' + badge + '<h1>' + _escaped_text(document.title) + '</h1>' + blocks_html(blocks, anchor_prefix=PROFILE_ANCHOR_PREFIX)
    body += '<p class="footer-note">完整来源、字段读取证据及原始结构随 JSON 资料保存。</p>'
    css = (
        'body { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif; color: #1c2834; background-color: #ffffff; padding: 6px; } '
        'h1 { font-size: 22px; font-weight: 700; color: #14222e; margin: 0 0 16px 0; padding-bottom: 8px; border-bottom: 2px solid #0093a2; } '
        'h2 { font-size: 15px; font-weight: 600; color: #1b3848; margin-top: 20px; margin-bottom: 8px; padding-left: 8px; border-left: 4px solid #0093a2; } '
        'table { border-collapse: collapse; border: 1px solid #d4dfe7; margin-bottom: 12px; } '
        'th { background-color: #f0f5f8; color: #2e4758; font-weight: 600; padding: 6px 10px; border: 1px solid #d4dfe7; font-size: 12px; } '
        'td { background-color: #ffffff; color: #1c2834; padding: 6px 10px; border: 1px solid #d4dfe7; font-size: 12px; line-height: 150%; } '
        'p { line-height: 150%; margin: 6px 0; } '
        '.footer-note { color: #607786; font-size: 11px; margin-top: 18px; border-top: 1px dashed #d4dfe7; padding-top: 8px; }'
    )
    return '<html><head><style>' + css + '</style></head><body>' + body + '</body></html>'


class ObjectsDialog(QDialog):
    extract_requested = Signal(str, list, bool)

    def __init__(self, path, parent=None, *, auto_preview=True):
        super().__init__(parent)
        from .resource_preview import ResourcePreviewWidget

        self.path = path
        self.preview_closed = False
        self.preview_generation = 0
        self._preview_leases = []
        self._current_preview_lease = None
        self._preview_cache_roots = ()
        self._input_roots = _input_roots(parent, path)
        self.finished.connect(self._release_previews)
        self.setWindowTitle('内部对象 · ' + Path(path).name)
        self.resize(1180, 780)
        layout = QVBoxLayout(self)
        self.status = QLabel('正在读取内部对象…')
        self.status.setWordWrap(True)
        self.status.setToolTip(str(path))
        layout.addWidget(self.status)
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        self.model = RecordsModel([('对象 ID', 'id'), ('类型', 'type'), ('名称', 'name'),
                                   ('对象大小', lambda row: size_text(value(row, 'size')) if value(row, 'size') is not None else '未知', 'size'),
                                   ('逻辑路径', 'logical_path')], self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setMinimumWidth(300)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setToolTip('对象大小：Unity 对象的序列化数据字节数，不含独立流式载荷，也不是导出后文件大小；独立文件显示原文件大小。未知表示未提供大小。')
        for column, width in enumerate((90, 110, 120, 95)):
            self.table.setColumnWidth(column, width)
        self.splitter.addWidget(self.table)
        self.preview_panel = ResourcePreviewWidget()
        self.preview_panel.setMinimumWidth(320)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([500, 640])
        layout.addWidget(self.splitter, 1)
        # Existing original-image actions and callers share the embedded panel.
        for name in ('preview', 'picture', 'image_scroll', 'image_tools', 'image_zoom', 'save_original_button'):
            setattr(self, name, getattr(self.preview_panel, name))
        self.preview.setPlainText('选择可预览对象后会自动显示。预览只写入应用缓存，不改动游戏文件。')
        self.preview_panel.save_original_requested.connect(self.save_original)
        row = QHBoxLayout()
        self.auto_preview = QCheckBox('自动预览')
        self.auto_preview.setObjectName('automaticObjectPreview')
        self.auto_preview.setChecked(bool(auto_preview))
        self.auto_preview.setToolTip('选择单个图片、音视频或文本对象后自动预览。音视频需点击播放。')
        row.addWidget(self.auto_preview)
        self.preview_button = QPushButton('预览所选对象')
        self.preview_button.clicked.connect(lambda: self.request(True))
        self.preview_button.setEnabled(False)
        self.extract_button = QPushButton('解包所选对象')
        self.extract_button.clicked.connect(lambda: self.request(False))
        self.extract_button.setEnabled(False)
        row.addWidget(self.preview_button)
        row.addWidget(self.extract_button)
        row.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(250)
        self._auto_timer.timeout.connect(self._auto_request)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.auto_preview.toggled.connect(self._auto_toggled)

    @property
    def _image_path(self):
        return self.preview_panel.image_path

    @property
    def _image_pixmap(self):
        return self.preview_panel.image_pixmap or QPixmap()

    @staticmethod
    def _previewable(row):
        return value(row, 'previewable', True) is not False and str(value(row, 'type', '')).casefold() in {
            'texture2d', 'sprite', 'audioclip', 'textasset', 'videoclip', 'image'}

    def set_objects(self, objects):
        if self.preview_closed:
            return
        self.preview_generation += 1
        self._auto_timer.stop()
        self._clear_current_preview()
        objects = list(objects)
        self.model.replace(objects)
        self.status.setText(f'{len(objects):,} 个对象　·　{Path(self.path).name}')
        if self.auto_preview.isChecked():
            first = next((index for index, row in enumerate(self.model.rows) if self._previewable(row)), None)
            if first is not None:
                self.table.selectRow(first)

    def _selection_changed(self, *_):
        self.preview_generation += 1
        self._auto_timer.stop()
        self._clear_current_preview()
        selected = selected_records(self.table)
        self.preview_button.setEnabled(len(selected) == 1 and value(selected[0], 'previewable', True) is not False)
        self.extract_button.setEnabled(bool(selected))
        self.status.setText(f'已选 {len(selected):,} 个对象　·　{Path(self.path).name}')
        if self.auto_preview.isChecked() and len(selected) == 1 and self._previewable(selected[0]):
            self._auto_timer.start()

    def _auto_toggled(self, checked):
        self.preview_generation += 1
        self._auto_timer.stop()
        selected = selected_records(self.table)
        if checked and len(selected) == 1 and self._previewable(selected[0]) and not self.preview_closed:
            self._auto_timer.start()

    def _auto_request(self):
        selected = selected_records(self.table)
        if not self.preview_closed and self.auto_preview.isChecked() and len(selected) == 1 and self._previewable(selected[0]):
            self.request(True)

    def track_preview(self, lease):
        if self.preview_closed:
            lease.release()
            return
        if lease not in self._preview_leases:
            self._preview_leases.append(lease)
        self._preview_cache_roots = tuple(dict.fromkeys((*self._preview_cache_roots, *lease.cache.roots)))

    def _release_lease(self, lease):
        if lease is not None:
            lease.release()
            if lease in self._preview_leases:
                self._preview_leases.remove(lease)

    def _clear_current_preview(self, keep_lease=None):
        # Media must release file handles before its cache can be removed.
        self.preview_panel.clear()
        previous, self._current_preview_lease = self._current_preview_lease, None
        if previous is not keep_lease:
            self._release_lease(previous)

    def _release_previews(self, *_):
        if self.preview_closed:
            return
        self.preview_closed = True
        self.preview_generation += 1
        self._auto_timer.stop()
        self.preview_panel.shutdown()
        for lease in list(self._preview_leases):
            self._release_lease(lease)
        self._current_preview_lease = None

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self._release_previews()

    def request(self, preview):
        if self.preview_closed:
            return
        selected = selected_records(self.table)
        ids = [str(row['id']) for row in selected]
        if preview:
            self._auto_timer.stop()
            if len(ids) != 1:
                self.status.setText('请选择一个对象进行预览。')
                return
            if value(selected[0], 'previewable', True) is False:
                self.status.setText('此对象暂不支持预览，可选择解包查看诊断。')
                return
            self.preview_generation += 1
            self._clear_current_preview()
            self.status.setText('正在准备预览…')
        if ids:
            self.extract_requested.emit(self.path, ids, preview)

    def show_files(self, outputs, preview_lease=None, generation=None):
        if self.preview_closed or (generation is not None and generation != self.preview_generation):
            self._release_lease(preview_lease)
            return False
        self._clear_current_preview(keep_lease=preview_lease)
        if preview_lease is not None:
            self.track_preview(preview_lease)
        outputs = list(outputs)
        try:
            shown = self.preview_panel.show_files(outputs)
        except (OSError, ValueError) as error:
            self._release_lease(preview_lease)
            self.preview_failed(str(error), generation=generation)
            return False
        if shown:
            self._current_preview_lease = preview_lease
            self.status.setText(f'已显示预览　·　{len(outputs):,} 个产物　·　{Path(self.path).name}')
        else:
            self._release_lease(preview_lease)
            self.status.setText('未生成可预览文件。请在任务页查看失败或跳过原因。')
        return shown

    def show_file(self, path, preview_lease=None, generation=None):
        return self.show_files([path], preview_lease=preview_lease, generation=generation)

    def preview_failed(self, message, generation=None):
        if self.preview_closed or (generation is not None and generation != self.preview_generation):
            return False
        self._clear_current_preview()
        self.status.setText(str(message))
        self.preview.setPlainText(str(message))
        return True

    def update_image(self, *_):
        self.preview_panel.update_image()

    def fit_image(self):
        self.preview_panel.fit_image()

    def save_original(self):
        if self._image_path and not self._image_pixmap.isNull():
            saved = _choose_original_save(self, self._image_path)
            if saved:
                self.status.setText(f'已保存原图　·　{self._image_pixmap.width()} × {self._image_pixmap.height()} 像素　·　{saved}')
