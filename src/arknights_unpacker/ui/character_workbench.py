"""AVG expression placement previews automatically and binds export to its result."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout,
                              QLabel, QPushButton, QSpinBox, QSplitter,
                              QVBoxLayout, QWidget)

from .resource_preview import ResourcePreviewWidget


class CharacterWorkbench(QDialog):
    preview_requested = Signal(dict)
    export_requested = Signal(dict)
    batch_requested = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = str(path)
        self.preview_generation = 0
        self.preview_closed = False
        self.successful_options = None
        self._requested_options = None
        self._last_options = None
        self._groups = []
        self._updating = False
        self._preview_leases = []
        self._current_preview_lease = None
        self._preview_cache_roots = ()
        self.setWindowTitle('表情差分制作 · ' + Path(path).name)
        self.resize(1160, 790)
        outer = QVBoxLayout(self)
        self.status = QLabel('正在读取角色表情配置…')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setToolTip(self.path)
        outer.addWidget(self.status)
        splitter = QSplitter(self)
        splitter.setChildrenCollapsible(False)
        self.splitter = splitter
        form_widget = QWidget()
        form_widget.setMinimumWidth(300)
        form_widget.setMaximumWidth(430)
        form_outer = QVBoxLayout(form_widget)
        hint = QLabel('选择同组底图和表情，调整后自动预览。\n确认效果后导出当前合成。\n批量导出按各组原配置生成全部表情。')
        hint.setWordWrap(True)
        form_outer.addWidget(hint)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.group_choice = QComboBox()
        self.base_choice = QComboBox()
        self.face_choice = QComboBox()
        for control, name in ((self.group_choice, '角色姿态组'), (self.base_choice, '合成底图'),
                              (self.face_choice, '叠加表情')):
            control.setAccessibleName(name)
            control.setMinimumContentsLength(10)
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.group_choice.setObjectName('characterGroup')
        self.base_choice.setObjectName('characterBase')
        self.face_choice.setObjectName('characterFace')
        form.addRow('姿态组', self.group_choice)
        form.addRow('底图', self.base_choice)
        form.addRow('表情', self.face_choice)
        self.x_spin = self._spin('贴图 X', -32768, 32768)
        self.y_spin = self._spin('贴图 Y', -32768, 32768)
        self.width_spin = self._spin('表情宽度', 1, 16384)
        self.height_spin = self._spin('表情高度', 1, 16384)
        form.addRow('X（从左向右）', self.x_spin)
        form.addRow('Y（从上向下）', self.y_spin)
        form.addRow('表情宽度', self.width_spin)
        form.addRow('表情高度', self.height_spin)
        form_outer.addLayout(form)
        self.placement_hint = QLabel()
        self.placement_hint.setWordWrap(True)
        self.placement_hint.setProperty('muted', True)
        form_outer.addWidget(self.placement_hint)
        self.reset_button = QPushButton('恢复本组配置')
        form_outer.addWidget(self.reset_button)
        self.diagnostics = QLabel()
        self.diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setProperty('muted', True)
        form_outer.addWidget(self.diagnostics)
        form_outer.addStretch()
        splitter.addWidget(form_widget)
        self.preview_panel = ResourcePreviewWidget()
        self.preview_panel.setMinimumWidth(340)
        # Saving is a formal extraction task handled by the host, with the exact
        # successful options. Hide the viewer's otherwise unconnected copy action.
        self.preview_panel.save_original_button.hide()
        splitter.addWidget(self.preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 800])
        outer.addWidget(splitter, 1)
        buttons = QHBoxLayout()
        self.export_button = QPushButton('导出当前合成')
        self.export_button.setObjectName('exportCharacterComposition')
        self.export_button.setProperty('primary', True)
        self.batch_button = QPushButton('批量导出全部表情')
        self.batch_button.setObjectName('exportAllCharacterExpressions')
        self.batch_button.setToolTip('按资源中的各组配置导出，不使用当前手动偏移和尺寸。')
        close = QPushButton('关闭')
        for button in (self.export_button, self.batch_button, self.reset_button, close):
            button.setAutoDefault(False)
            button.setDefault(False)
        for button in (self.export_button, self.batch_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(close)
        outer.addLayout(buttons)
        self.group_choice.currentIndexChanged.connect(self._select_group)
        self.base_choice.currentIndexChanged.connect(self._form_changed)
        self.face_choice.currentIndexChanged.connect(self._form_changed)
        for spin in (self.x_spin, self.y_spin, self.width_spin, self.height_spin):
            spin.valueChanged.connect(self._form_changed)
        self.reset_button.clicked.connect(self._select_group)
        self.export_button.clicked.connect(self.request_export)
        self.batch_button.clicked.connect(self._request_batch)
        close.clicked.connect(self.close)
        self.finished.connect(self._release_previews)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(250)
        self._auto_timer.timeout.connect(self.request_preview)
        self._set_available(False)

    @staticmethod
    def _spin(name, minimum, maximum):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(' px')
        spin.setAccessibleName(name)
        spin.setKeyboardTracking(True)
        return spin

    def _set_available(self, available):
        for control in (self.group_choice, self.base_choice, self.face_choice, self.reset_button, self.batch_button):
            control.setEnabled(available)
        self.export_button.setEnabled(False)
        self._update_placement()

    def set_catalog(self, catalog):
        if self.preview_closed:
            return
        self._updating = True
        self._groups = deepcopy(catalog.get('groups', []))
        self.group_choice.clear()
        for group in self._groups:
            self.group_choice.addItem(str(group.get('title') or group['id']), group['id'])
        messages = [str(message) for message in catalog.get('diagnostics', [])]
        self.diagnostics.setText('\n'.join(messages[:6]) +
                                 (f'\n另有 {len(messages) - 6} 条诊断，悬停可查看。' if len(messages) > 6 else ''))
        self.diagnostics.setToolTip('\n'.join(messages))
        self._updating = False
        self._set_available(bool(self._groups))
        self._select_group()
        if not self._groups:
            self.status.setText('此资源没有可制作的角色表情配置。请查看下方诊断，或选择其他角色包。')

    def _group(self):
        group_id = self.group_choice.currentData()
        return next((group for group in self._groups if group['id'] == group_id), None)

    def _select_group(self, *_):
        if self._updating or self.preview_closed:
            return
        group = self._group()
        self._updating = True
        self.base_choice.clear()
        self.face_choice.clear()
        if group:
            self.face_choice.addItem('不叠加表情（仅底图）', '')
            for entry in group.get('entries', []):
                label = str(entry.get('alias') or entry.get('name') or entry['id'])
                if entry.get('width') and entry.get('height'):
                    label += f"（{entry['width']} × {entry['height']}）"
                if entry.get('role') in {'base', 'whole'}:
                    self.base_choice.addItem(label, entry['id'])
                if entry.get('role') in {'face', 'whole'}:
                    if entry.get('role') == 'whole':
                        label += ' · 整幅替换'
                    self.face_choice.addItem(label, entry['id'])
            self.base_choice.setCurrentIndex(max(0, self.base_choice.findData(group.get('base_id'))))
            if self.face_choice.count() > 1:
                self.face_choice.setCurrentIndex(1)
            position = group.get('face_pos') or [0, 0]
            size = group.get('face_size') or [1, 1]
            self.x_spin.setValue(round(position[0]))
            self.y_spin.setValue(round(position[1]))
            self.width_spin.setValue(max(1, round(size[0])))
            self.height_spin.setValue(max(1, round(size[1])))
        self._updating = False
        self._last_options = None
        self._form_changed()

    def _update_placement(self):
        group = self._group()
        face_id = self.face_choice.currentData()
        face = next((entry for entry in (group or {}).get('entries', []) if entry['id'] == face_id), None)
        overlay = bool(face and face.get('role') == 'face')
        for spin in (self.x_spin, self.y_spin, self.width_spin, self.height_spin):
            spin.setEnabled(overlay)
        if face and face.get('role') == 'whole':
            text = '此项为整幅替换，直接使用该完整姿态，不叠加坐标或缩放。'
        elif face is None:
            text = '仅使用所选底图，不叠加表情。'
        else:
            text = '以底图左上角为原点；负坐标或超出画布的部分会被裁剪。底图画布保持原尺寸。'
        self.placement_hint.setText(text)

    def current_options(self):
        return {'group_id': self.group_choice.currentData(), 'base_id': self.base_choice.currentData(),
                'face_id': self.face_choice.currentData() or '', 'x': self.x_spin.value(),
                'y': self.y_spin.value(), 'width': self.width_spin.value(), 'height': self.height_spin.value()}

    def _form_changed(self, *_):
        if self._updating or self.preview_closed:
            return
        options = self.current_options()
        if options == self._last_options:
            return
        self._last_options = dict(options)
        self._auto_timer.stop()
        self.preview_generation += 1
        self.successful_options = None
        self._requested_options = None
        self._clear_current_preview()
        self._update_placement()
        available = bool(self._group() and self.base_choice.currentData())
        self.batch_button.setEnabled(bool(self._groups))
        self.export_button.setEnabled(False)
        if available:
            self.status.setText('合成参数已更新，正在准备自动预览…')
            self._auto_timer.start()

    def request_preview(self):
        if self.preview_closed or not self._group() or not self.base_choice.currentData():
            return
        self.preview_generation += 1
        self.successful_options = None
        self._clear_current_preview()
        self.export_button.setEnabled(False)
        options = self.current_options()
        self._requested_options = (self.preview_generation, dict(options))
        self.status.setText('正在自动合成预览…')
        self.preview_requested.emit(dict(options))

    def request_export(self):
        if (not self.preview_closed and self.successful_options is not None
                and self.successful_options == self.current_options() and self.export_button.isEnabled()):
            self.export_requested.emit(dict(self.successful_options))

    def _request_batch(self):
        if not self.preview_closed and self.batch_button.isEnabled():
            self.batch_requested.emit()

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
        self.preview_panel.clear()
        previous, self._current_preview_lease = self._current_preview_lease, None
        if previous is not keep_lease:
            self._release_lease(previous)

    def show_files(self, outputs, preview_lease=None, generation=None):
        requested = self._requested_options
        if (self.preview_closed or requested is None or requested[0] != self.preview_generation
                or (generation is not None and generation != self.preview_generation)
                or requested[1] != self.current_options()):
            self._release_lease(preview_lease)
            return False
        self._clear_current_preview(keep_lease=preview_lease)
        if preview_lease is not None:
            self.track_preview(preview_lease)
        try:
            shown = self.preview_panel.show_files(outputs)
            shown = shown and not self.preview_panel.image_pixmap.isNull()
        except (OSError, ValueError) as error:
            self._release_lease(preview_lease)
            self.preview_failed(str(error), generation=generation)
            return False
        if not shown:
            self._release_lease(preview_lease)
            self.preview_failed('没有生成可用的合成图片。请查看任务诊断。', generation=generation)
            return False
        self._current_preview_lease = preview_lease
        self.successful_options = dict(requested[1])
        self.export_button.setEnabled(True)
        self.status.setText('自动预览已就绪，可导出当前效果。修改参数后将自动更新。')
        return True

    def preview_failed(self, message, generation=None):
        if self.preview_closed or (generation is not None and generation != self.preview_generation):
            return
        self.successful_options = None
        self._requested_options = None
        self._auto_timer.stop()
        self.export_button.setEnabled(False)
        self.status.setText('预览失败：' + str(message))

    def load_failed(self, message):
        if self.preview_closed:
            return
        self.set_catalog({'groups': [], 'diagnostics': [str(message)]})
        self.status.setText('无法读取角色表情配置：' + str(message))

    def _release_previews(self, *_):
        if self.preview_closed:
            return
        self.preview_closed = True
        self._auto_timer.stop()
        self.preview_generation += 1
        self.successful_options = None
        self._requested_options = None
        self.preview_panel.shutdown()
        for lease in list(self._preview_leases):
            self._release_lease(lease)
        self._current_preview_lease = None

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self._release_previews()
