from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableView,
    QTextBrowser, QVBoxLayout, QWidget, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox)


def dark_palette():
    palette = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.AlternateBase,
                     QPalette.ColorRole.Button, QPalette.ColorRole.ToolTipBase):
            palette.setColor(group, role, QColor('#171c23'))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                     QPalette.ColorRole.ToolTipText):
            palette.setColor(group, role, QColor('#f4f7fa'))
    return palette


def test_application_theme_replaces_all_dark_color_groups(qapp):
    from arknights_unpacker.ui.styles import apply_theme
    qapp.setPalette(dark_palette())
    apply_theme(qapp)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        palette = qapp.palette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button,
                     QPalette.ColorRole.ToolTipBase, QPalette.ColorRole.AlternateBase):
            assert palette.color(group, role).lightnessF() > .85
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                     QPalette.ColorRole.ToolTipText):
            assert palette.color(group, role).lightnessF() < .65
    assert QApplication.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)


def test_tables_inputs_popups_and_dialogs_share_light_theme(qtbot, qapp):
    from arknights_unpacker.ui.styles import apply_theme
    qapp.setPalette(dark_palette())
    apply_theme(qapp)
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    entry = QLineEdit('portrait_amiya.ab')
    combo = QComboBox()
    combo.addItems(['PNG 原图', '文本／数据'])
    spin = QDoubleSpinBox()
    check = QCheckBox('只显示 AB 文件')
    check.setChecked(True)
    for title, control in [('文件', entry), ('类型', combo), ('查看缩放', spin), ('筛选', check)]:
        form.addRow(title, control)
    layout.addLayout(form)
    table = QTableView()
    model = QStandardItemModel(1, 2, table)
    model.setHorizontalHeaderLabels(['包文件', '文件夹用途'])
    model.setItem(0, 0, QStandardItem('portrait_amiya.ab'))
    model.setItem(0, 1, QStandardItem('干员立绘'))
    table.setModel(model)
    table.setAlternatingRowColors(True)
    layout.addWidget(table)
    scroll = QScrollArea()
    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.addWidget(QLabel('原始资源 · 缩放只影响预览'))
    scroll.setWidget(content)
    layout.addWidget(scroll)
    browser = QTextBrowser()
    browser.setHtml('<h2>阿米娅</h2><p>本地资料预览</p>')
    layout.addWidget(browser)
    disabled = QPushButton('等待选择图片')
    disabled.setEnabled(False)
    layout.addWidget(disabled)
    dialog.resize(640, 680)
    dialog.show()
    qtbot.waitExposed(dialog)
    for control in (entry, combo.view(), spin, table, table.viewport(), scroll, browser, disabled):
        assert control.palette().color(QPalette.ColorRole.Base).lightnessF() > .85
        assert control.palette().color(QPalette.ColorRole.Text).lightnessF() < .65
    message = QMessageBox(QMessageBox.Icon.Information, '保存原图', '原始像素已保存。', parent=dialog)
    qtbot.addWidget(message)
    assert message.palette().color(QPalette.ColorRole.Window).lightnessF() > .85
    assert not dialog.grab().isNull()


def test_styled_combo_and_spin_controls_keep_visible_arrows(qtbot, qapp):
    from arknights_unpacker.ui.styles import apply_theme
    apply_theme(qapp)
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    combo = QComboBox()
    combo.addItem('图片 · 原始像素')
    spin = QDoubleSpinBox()
    spin.setValue(24)
    layout.addWidget(combo)
    layout.addWidget(spin)
    window.resize(400, 120)
    window.show()
    qtbot.waitExposed(window)
    combo_option = QStyleOptionComboBox()
    combo.initStyleOption(combo_option)
    spin_option = QStyleOptionSpinBox()
    spin.initStyleOption(spin_option)
    controls = [(combo, QStyle.ComplexControl.CC_ComboBox, combo_option, QStyle.SubControl.SC_ComboBoxArrow),
                (spin, QStyle.ComplexControl.CC_SpinBox, spin_option, QStyle.SubControl.SC_SpinBoxUp),
                (spin, QStyle.ComplexControl.CC_SpinBox, spin_option, QStyle.SubControl.SC_SpinBoxDown)]
    for widget, complex_control, option, subcontrol in controls:
        area = widget.style().subControlRect(complex_control, option, subcontrol, widget)
        center = area.center()
        rendered = widget.grab().toImage()
        # The center must contain an ink arrow, not only the subcontrol border.
        ink_pixels = sum(rendered.pixelColor(x, y).lightnessF() < .6
            for x in range(center.x() - 5, center.x() + 6)
            for y in range(center.y() - 3, center.y() + 4))
        assert ink_pixels >= 5
