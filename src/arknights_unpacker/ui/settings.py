from __future__ import annotations
from PySide6.QtCore import Signal, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QSpinBox, QComboBox, QCheckBox, QGroupBox
from arknights_unpacker.contracts import ExportFormat, ReportOptions


class SettingsView(QWidget):
    changed = Signal()

    def __init__(self, config, data_root, parent=None):
        super().__init__(parent)
        self.config = config
        layout = QVBoxLayout(self)
        output_group = QGroupBox('文件与输出')
        form = QFormLayout(output_group)
        output_row = QHBoxLayout()
        self.output = QLineEdit(str(config.get('output_root', str(data_root / 'exports'))))
        self.output.setObjectName('outputRoot')
        choose = QPushButton('选择…')
        choose.clicked.connect(self.choose_output)
        output_row.addWidget(self.output, 1)
        output_row.addWidget(choose)
        form.addRow('输出目录', output_row)
        note = QLabel('游戏目录仅作为只读输入。请将输出保存在独立目录，避免放入游戏安装目录。')
        note.setWordWrap(True)
        form.addRow(note)
        self.mode = QComboBox()
        self.mode.addItem('自动处理（按签名与对象类型）', 'auto')
        self.mode.addItem('原始导出（保留可得原始内容）', 'raw')
        self.mode.setCurrentIndex(max(0, self.mode.findData(config.get('extraction_mode', 'auto'))))
        form.addRow('解包方式', self.mode)
        kinds_row = QHBoxLayout()
        self.kinds = {}
        for key, name in [('image', '图片'), ('text', '文本／数据'), ('audio', '音频'), ('spine', 'Spine')]:
            check = QCheckBox(name)
            check.setChecked(key in config.get('extraction_kinds', ['image', 'text', 'audio', 'spine']))
            self.kinds[key] = check
            kinds_row.addWidget(check)
        form.addRow('资源类型', kinds_row)
        layout.addWidget(output_group)
        report_group = QGroupBox('干员／模组资料排版')
        report_form = QFormLayout(report_group)
        format_row = QHBoxLayout()
        self.formats = {}
        for fmt in ExportFormat:
            check = QCheckBox(fmt.value.upper())
            check.setChecked(fmt.value in config.get('formats', ['png', 'html', 'json', 'txt']))
            if fmt in (ExportFormat.JSON, ExportFormat.TXT):
                check.setChecked(True)
                check.setEnabled(False)
                check.setToolTip('随资料保存，用于复核数值、来源与诊断。')
            self.formats[fmt] = check
            format_row.addWidget(check)
        report_form.addRow('保存格式', format_row)
        self.width = QSpinBox()
        self.width.setRange(720, 3000)
        self.width.setSingleStep(120)
        self.width.setSuffix(' px')
        self.width.setValue(int(config.get('report_width', 1200)))
        self.width.setToolTip('仅决定新生成的干员／模组资料长图排版宽度，不缩放游戏资源原图。')
        report_form.addRow('资料 PNG 画布宽度', self.width)
        self.font_size = QSpinBox()
        self.font_size.setRange(18, 56)
        self.font_size.setValue(int(config.get('report_font_size', 28)))
        report_form.addRow('资料 PNG 字号', self.font_size)
        self.theme = QComboBox()
        self.theme.addItem('深色', 'dark')
        self.theme.addItem('浅色', 'light')
        self.theme.setCurrentIndex(max(0, self.theme.findData(config.get('report_theme', 'dark'))))
        report_form.addRow('资料图片主题', self.theme)
        report_note = QLabel('以上设置仅用于生成资料长图，界面始终使用浅色工作台。\n解包的资源图片和“保存原图”保留原始像素；预览缩放只改变显示大小。')
        report_note.setProperty('muted', True)
        report_note.setWordWrap(True)
        report_form.addRow(report_note)
        layout.addWidget(report_group)
        app_group = QGroupBox('运行与历史')
        app_form = QFormLayout(app_group)
        self.data_locale = QComboBox()
        self.data_locale.setObjectName('dataLocale')
        self.data_locale.addItem('未知：仅同一安装自动对比', 'unknown')
        self.data_locale.addItem('简体中文／国服（用户声明）', 'zh_CN')
        self.data_locale.setCurrentIndex(max(0, self.data_locale.findData(config.get('data_locale', 'unknown'))))
        app_form.addRow('数据区服声明', self.data_locale)
        locale_note = QLabel('用于声明当前与导入历史数据的区服，修改后重新解析当前数据；无法自动确认同服时不认定新增。')
        locale_note.setWordWrap(True)
        app_form.addRow(locale_note)
        self.monitor = QCheckBox('运行期间检查资源清单变动（每 15 秒；发现后重扫）')
        self.monitor.setChecked(bool(config.get('monitor', False)))
        app_form.addRow(self.monitor)
        data_path = QLabel(str(data_root))
        data_path.setTextInteractionFlags(data_path.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        data_path.setWordWrap(True)
        app_form.addRow('本地记录目录', data_path)
        open_data = QPushButton('打开数据目录')
        open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_root))))
        app_form.addRow(open_data)
        data_note = QLabel('默认保存在程序目录旁的 data 文件夹；指定独立数据目录时使用指定位置。\n每次启动读取上次扫描和解析记录，新扫描与已有完整记录比较。导出文件和历史基线不会自动清理。')
        data_note.setProperty('muted', True)
        data_note.setWordWrap(True)
        app_form.addRow(data_note)
        layout.addWidget(app_group)
        save = QPushButton('保存设置')
        save.setProperty('primary', True)
        save.clicked.connect(self.commit)
        layout.addWidget(save)
        layout.addStretch()

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, '选择独立输出目录', self.output.text())
        if path:
            self.output.setText(path)

    def commit(self):
        self.config.update(output_root=self.output.text().strip(), extraction_mode=self.mode.currentData(),
                           extraction_kinds=[key for key, check in self.kinds.items() if check.isChecked()],
                           formats=[fmt.value for fmt, check in self.formats.items() if check.isChecked()],
                           report_width=self.width.value(), report_font_size=self.font_size.value(),
                           report_theme=self.theme.currentData(), monitor=self.monitor.isChecked(),
                           data_locale=self.data_locale.currentData())
        self.changed.emit()

    def selected_formats(self):
        return {fmt for fmt, check in self.formats.items() if check.isChecked()}

    def report_options(self):
        return ReportOptions(width=self.width.value(), font_size=self.font_size.value(), theme=self.theme.currentData())
