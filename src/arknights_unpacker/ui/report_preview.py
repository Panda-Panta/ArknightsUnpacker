"""Preview exported report files in the workbench."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTableView, QVBoxLayout,
)

from arknights_unpacker.contracts import ReportOptions
from .models import RecordsModel, value
from .original_image import choose_original_save, input_roots


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
        self._input_roots = input_roots(parent)
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
            saved = choose_original_save(self, path, self._input_roots, self._preview_cache_roots)
            if saved:
                self.image_status.setText(f'已保存原始 PNG　·　{self._pixmap.width()} × {self._pixmap.height()} 像素　·　{saved}')
