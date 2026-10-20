from __future__ import annotations
from html import escape
from pathlib import Path
import shutil
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QPushButton, QTextBrowser, QSplitter, QAbstractItemView, QScrollArea, QComboBox, QDoubleSpinBox, QFileDialog, QMessageBox, QWidget
from arknights_unpacker.contracts import ReportDocument, OperatorProfile, ModuleProfile
from arknights_unpacker.paths import validate_output
from arknights_unpacker.reports.model import semantic_blocks
from .models import RecordsModel, selected_records, value


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


def _copy_original_image(source, destination, input_roots):
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
    try:
        return _copy_original_image(source, filename, dialog._input_roots)
    except (OSError, ValueError) as error:
        QMessageBox.warning(dialog, '无法保存原图', str(error))
        return None


class ReportArtifactsDialog(QDialog):
    """Inspect exactly the returned report files; browser launch is an explicit action."""
    html_open_requested = Signal(str)
    export_requested = Signal()

    def __init__(self, artifacts, parent=None, *, preview_only=False):
        super().__init__(parent)
        self.artifacts = list(artifacts)
        self._pixmap = QPixmap()
        self._input_roots = _input_roots(parent)
        self.setWindowTitle('资料预览' if preview_only else '本次资料导出产物')
        self.resize(1150, 850)
        layout = QVBoxLayout(self)
        self.summary = QLabel(('预览保存在本地记录目录；点击“导出所选到输出目录”保存完整资料。' if preview_only else '本次生成的图片、HTML 与来源文件。') + f'　共 {len(self.artifacts)} 个文件。缩放只影响预览。')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
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
        for artifact in self.artifacts:
            path = str(value(artifact, 'path', ''))
            fmt = str(value(artifact, 'format', '')).lower()
            if fmt == 'png':
                self.pages.addItem(f'{self.pages.count() + 1} · {Path(path).name}', path)
            elif fmt == 'html':
                self.html_files.addItem(Path(path).name, path)
        self.open_html.setEnabled(self.html_files.count() > 0)
        self.pages.currentIndexChanged.connect(self.select_page)
        self.select_page()

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
            self.html_open_requested.emit(str(path))

    def save_original(self):
        path = self.pages.currentData()
        if path and not self._pixmap.isNull():
            saved = _choose_original_save(self, path)
            if saved:
                self.image_status.setText(f'已保存原始 PNG　·　{self._pixmap.width()} × {self._pixmap.height()} 像素　·　{saved}')

def _escaped_text(text):
    return escape(str(text), quote=True).replace('\n', '<br>')


def blocks_html(blocks):
    """Qt's rich text subset: no scripts, remote assets, or recursive raw evidence."""
    parts = []
    for block in blocks:
        parts.append('<h2>' + _escaped_text(block.title) + '</h2>')
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
    return ''.join(parts)


def profile_html(profile):
    document = ReportDocument(title=profile.name,
        operators=[profile] if isinstance(profile, OperatorProfile) else [],
        modules=[profile] if isinstance(profile, ModuleProfile) else [])
    body = '<h1>' + _escaped_text(document.title) + '</h1>' + blocks_html(semantic_blocks(document))
    body += '<p style="color:#607786">完整来源、字段读取证据及原始结构随 JSON 资料保存。</p>'
    return '<html><head><style>h1{font-size:22px;color:#203b4c}h2{font-size:16px;color:#087e8b;margin-top:18px}table{border-color:#d5e0e6}th{background-color:#eaf0f4;color:#415b6b}td{background-color:#ffffff}p{line-height:150%}</style></head><body style="font-family:Microsoft YaHei UI; color:#233746; background-color:#ffffff;">' + body + '</body></html>'


def changes_html(changes, kind, entity_id):
    selected = [change for change in value(changes, kind, []) if
                str(change.get('id', change.get('char_id', change.get('equip_id', '')))) == entity_id]
    diagnostics = value(changes, 'diagnostics', [])
    if not selected and not diagnostics:
        return ''
    payload = {'baseline_id': value(changes, 'baseline_id'), 'current_id': value(changes, 'current_id'),
               'diagnostics': diagnostics, kind: selected}
    document = ReportDocument(title='相对历史基线的变化', metadata={'changes': payload})
    return blocks_html(block for block in semantic_blocks(document) if block.group == '更新对照')


class ObjectsDialog(QDialog):
    extract_requested = Signal(str, list, bool)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self._input_roots = _input_roots(parent, path)
        self._image_path = None
        self._image_pixmap = QPixmap()
        self.setWindowTitle('内部对象 · ' + Path(path).name)
        self.resize(1060, 720)
        layout = QVBoxLayout(self)
        self.status = QLabel('正在读取内部对象…')
        layout.addWidget(self.status)
        split = QSplitter()
        self.model = RecordsModel([('对象 ID', 'id'), ('类型', 'type'), ('名称', 'name'), ('逻辑路径', 'logical_path')], self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        split.addWidget(self.table)
        self.preview = QTextBrowser()
        self.preview.setPlainText('选择图片或文本对象后点击“预览所选对象”。\n预览只写入应用缓存，不改动游戏文件。')
        split.addWidget(self.preview)
        split.setSizes([600, 420])
        layout.addWidget(split, 1)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setProperty('imageCanvas', True)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll.setMinimumHeight(150)
        self.image_scroll.setMaximumHeight(320)
        self.image_scroll.setWidget(self.picture)
        self.image_scroll.hide()
        layout.addWidget(self.image_scroll)
        self.image_tools = QWidget()
        image_tools = QHBoxLayout(self.image_tools)
        image_tools.setContentsMargins(0, 0, 0, 0)
        image_tools.addWidget(QLabel('查看缩放'))
        self.image_zoom = QDoubleSpinBox()
        self.image_zoom.setObjectName('objectImageZoom')
        self.image_zoom.setRange(1, 400)
        self.image_zoom.setDecimals(0)
        self.image_zoom.setSuffix(' %')
        self.image_zoom.setValue(100)
        self.image_zoom.setToolTip('缩放只影响预览，保存原图保留原始像素。')
        self.image_zoom.valueChanged.connect(self.update_image)
        image_tools.addWidget(self.image_zoom)
        fit = QPushButton('适应预览区')
        fit.clicked.connect(self.fit_image)
        image_tools.addWidget(fit)
        image_tools.addStretch()
        self.save_original_button = QPushButton('保存原图…')
        self.save_original_button.setObjectName('saveOriginalImage')
        self.save_original_button.setProperty('primary', True)
        self.save_original_button.setToolTip('保存解包后的原始图片，不受查看缩放影响。')
        self.save_original_button.setEnabled(False)
        self.save_original_button.clicked.connect(self.save_original)
        image_tools.addWidget(self.save_original_button)
        self.image_tools.hide()
        layout.addWidget(self.image_tools)
        row = QHBoxLayout()
        preview = QPushButton('预览所选对象')
        preview.clicked.connect(lambda: self.request(True))
        extract = QPushButton('解包所选对象')
        extract.clicked.connect(lambda: self.request(False))
        row.addWidget(preview)
        row.addWidget(extract)
        row.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)

    def set_objects(self, objects):
        self.model.replace(objects)
        self.status.setText(f'{len(objects):,} 个对象　·　{self.path}')

    def request(self, preview):
        ids = [str(r['id']) for r in selected_records(self.table)]
        if preview and len(ids) != 1:
            self.status.setText('请选择一个对象进行预览。')
            return
        if ids:
            self.extract_requested.emit(self.path, ids, preview)

    def show_file(self, path):
        path = Path(path)
        self._image_path = None
        self._image_pixmap = QPixmap()
        self.picture.clear()
        self.save_original_button.setEnabled(False)
        self.image_scroll.hide()
        self.image_tools.hide()
        if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.preview.setPlainText('图片无法读取。可在输出目录查看诊断。')
            else:
                self._image_path = path.resolve()
                self._image_pixmap = pixmap
                self.save_original_button.setEnabled(True)
                self.image_scroll.show()
                self.image_tools.show()
                self.preview.setPlainText(f'{path.name}\n原始尺寸：{pixmap.width()} × {pixmap.height()} 像素\n缩放只影响预览；“保存原图”保留原始文件。\n{path}')
                self.update_image()
        elif path.is_file():
            with path.open('rb') as stream:
                data = stream.read(256 * 1024 + 1)
            self.preview.setPlainText(data[:256 * 1024].decode('utf-8', errors='replace') + ('\n\n预览已限长，完整内容见输出。' if len(data) > 256 * 1024 else ''))

    def update_image(self, *_):
        if self._image_pixmap.isNull():
            return
        scale = self.image_zoom.value() / 100
        rendered = self._image_pixmap.scaled(max(1, round(self._image_pixmap.width() * scale)),
            max(1, round(self._image_pixmap.height() * scale)), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.picture.setPixmap(rendered)
        self.picture.resize(rendered.size())

    def fit_image(self):
        if not self._image_pixmap.isNull():
            width_scale = max(1, self.image_scroll.viewport().width() - 12) / self._image_pixmap.width()
            height_scale = max(1, self.image_scroll.viewport().height() - 12) / self._image_pixmap.height()
            self.image_zoom.setValue(min(width_scale, height_scale) * 100)

    def save_original(self):
        if self._image_path and not self._image_pixmap.isNull():
            saved = _choose_original_save(self, self._image_path)
            if saved:
                self.status.setText(f'已保存原图　·　{self._image_pixmap.width()} × {self._image_pixmap.height()} 像素　·　{saved}')
