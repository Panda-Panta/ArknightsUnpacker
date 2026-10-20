"""A light, PRTS-inspired native workbench, independent of the Windows theme."""

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication
from arknights_unpacker.paths import resource_root


COLORS = {
    'window': '#f1f5f7', 'surface': '#ffffff', 'alternate': '#f4f8fa',
    'ink': '#233746', 'muted': '#617582', 'border': '#c7d4dc',
    'accent': '#087e8b', 'selection': '#deeff2', 'disabled': '#7a8993',
}


STYLE = '''
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #233746; }
QMainWindow, QDialog { background: #f1f5f7; }
QWidget:disabled { color: #7a8993; }
QLabel { background: transparent; }
QLabel#appTitle { font-family: "Segoe UI Semibold", "Microsoft YaHei UI"; font-size: 20px; font-weight: 600; color: #203b4c; }
QLabel#subtitle, QLabel[muted="true"] { color: #617582; }
QLabel#sessionStatus { color: #426472; font-size: 12px; }
QLabel[notice="warning"] { color: #73521c; background: #fff5df; border: 1px solid #e5d5af; padding: 8px 10px; }
QFrame#header { background: #ffffff; border: 1px solid #d3dee4; border-bottom: 3px solid #087e8b; }
QPushButton, QToolButton { padding: 7px 12px; border: 1px solid #c1cfd8; border-radius: 3px; background: #ffffff; color: #233746; }
QPushButton:hover, QToolButton:hover { background: #e9f4f6; border-color: #539aa4; }
QPushButton:focus, QToolButton:focus { border-color: #087e8b; background: #e9f4f6; }
QPushButton:pressed, QToolButton:pressed, QPushButton:checked { background: #d6ebef; border-color: #087e8b; }
QPushButton:disabled, QToolButton:disabled { color: #7a8993; background: #edf2f5; border-color: #d3dee4; }
QPushButton[primary="true"] { background: #087e8b; border-color: #087e8b; color: #ffffff; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #066c78; border-color: #066c78; }
QPushButton[primary="true"]:focus { background: #066c78; border: 1px solid #203b4c; }
QPushButton[primary="true"]:pressed { background: #045b66; }
QPushButton[primary="true"]:disabled { background: #b5cdd1; border-color: #b5cdd1; color: #f8fbfc; }
QLineEdit, QAbstractSpinBox, QComboBox { min-height: 20px; padding: 5px 7px; border: 1px solid #c1cfd8; border-radius: 3px; background: #ffffff; color: #233746; selection-background-color: #087e8b; selection-color: #ffffff; }
QLineEdit:hover, QAbstractSpinBox:hover, QComboBox:hover { border-color: #8cabb9; }
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus { border-color: #087e8b; }
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled { background: #edf2f5; border-color: #d3dee4; color: #7a8993; }
QLineEdit[readOnly="true"] { background: #f4f8fa; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border-left: 1px solid #d5e0e6; background: #f4f8fa; }
QComboBox::drop-down:hover { background: #deeff2; }
QComboBox::drop-down:disabled { background: #edf2f5; border-color: #d3dee4; }
QComboBox::down-arrow { image: url("@UI@/arrow-down.svg"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { background: #ffffff; color: #233746; border: 1px solid #9bb4c1; outline: 0; selection-background-color: #deeff2; selection-color: #184e58; padding: 3px; }
QComboBox QAbstractItemView::item { min-height: 27px; padding: 3px 7px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; border-left: 1px solid #d5e0e6; border-bottom: 1px solid #d5e0e6; background: #f4f8fa; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border-left: 1px solid #d5e0e6; background: #f4f8fa; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: #deeff2; }
QSpinBox::up-button:disabled, QSpinBox::down-button:disabled, QDoubleSpinBox::up-button:disabled, QDoubleSpinBox::down-button:disabled { background: #edf2f5; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@UI@/arrow-up.svg"); width: 8px; height: 5px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@UI@/arrow-down.svg"); width: 8px; height: 5px; }
QTabWidget::pane { border: 1px solid #c7d4dc; background: #f7fafb; }
QTabBar::tab { padding: 11px 22px; color: #617582; background: #e8eff3; border: 0; border-bottom: 3px solid transparent; }
QTabBar::tab:hover { color: #233746; background: #edf6f8; }
QTabBar::tab:selected { color: #174858; background: #f7fafb; border-bottom: 3px solid #087e8b; font-weight: 600; }
QTabBar::tab:disabled { color: #7a8993; }
QTreeView, QTableView, QListView, QTextBrowser, QTextEdit, QPlainTextEdit { background: #ffffff; color: #233746; border: 1px solid #c7d4dc; alternate-background-color: #f4f8fa; gridline-color: #e1e9ee; selection-background-color: #deeff2; selection-color: #184e58; }
QTreeView:focus, QTableView:focus, QListView:focus, QTextBrowser:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #7aa8b4; }
QTreeView::item, QTableView::item, QListView::item { min-height: 27px; padding: 2px 4px; }
QTreeView::item:hover, QTableView::item:hover, QListView::item:hover { background: #edf6f8; }
QTreeView::item:selected, QTableView::item:selected, QListView::item:selected { background: #deeff2; color: #184e58; }
QTreeView::item:disabled, QTableView::item:disabled, QListView::item:disabled { color: #7a8993; }
QHeaderView { background: #eaf0f4; }
QHeaderView::section { color: #415b6b; background: #eaf0f4; border: 0; border-right: 1px solid #d5e0e6; border-bottom: 1px solid #c7d4dc; padding: 8px 7px; font-weight: 600; }
QHeaderView::section:hover { background: #deeff2; }
QTableCornerButton::section { background: #eaf0f4; border: 0; border-right: 1px solid #d5e0e6; border-bottom: 1px solid #c7d4dc; }
QGroupBox { background: #f9fbfc; border: 1px solid #ccd8e0; border-radius: 3px; margin-top: 12px; padding: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 11px; padding: 0 6px; color: #355261; font-weight: 600; }
QProgressBar { border: 1px solid #c7d4dc; border-radius: 3px; background: #e8eff3; color: #233746; text-align: center; min-height: 16px; }
QProgressBar::chunk { background: #2995a1; }
QStatusBar { color: #426472; background: #e8eff3; border-top: 1px solid #d3dee4; }
QStatusBar::item { border: 0; }
QSplitter::handle { background: #f1f5f7; width: 7px; height: 7px; }
QSplitter::handle:hover { background: #cfe5ea; }
QCheckBox, QRadioButton { spacing: 7px; padding: 2px; border: 1px solid transparent; background: transparent; }
QCheckBox:focus, QRadioButton:focus { border: 1px dashed #087e8b; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator { border: 1px solid #91a9b6; border-radius: 2px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #087e8b; background: #edf6f8; }
QCheckBox::indicator:checked { border-color: #087e8b; background: #087e8b; image: url("@UI@/check.svg"); }
QCheckBox::indicator:disabled { border-color: #c7d4dc; background: #edf2f5; }
QCheckBox::indicator:checked:disabled { border-color: #b5cdd1; background: #b5cdd1; }
QRadioButton::indicator { border: 1px solid #91a9b6; border-radius: 8px; background: #ffffff; }
QRadioButton::indicator:checked { border: 5px solid #087e8b; }
QScrollArea { border: 1px solid #c7d4dc; background: #edf2f5; }
QScrollArea > QWidget > QWidget { background: #f1f5f7; }
QLabel[imageCanvas="true"] { background: #e7eef2; }
QScrollBar:vertical { width: 12px; background: #edf2f5; margin: 0; }
QScrollBar::handle:vertical { min-height: 30px; background: #b5c6d0; border: 3px solid #edf2f5; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #799daa; }
QScrollBar:horizontal { height: 12px; background: #edf2f5; margin: 0; }
QScrollBar::handle:horizontal { min-width: 30px; background: #b5c6d0; border: 3px solid #edf2f5; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #799daa; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenuBar, QMenu { background: #ffffff; color: #233746; }
QMenu { border: 1px solid #c7d4dc; padding: 4px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background: #deeff2; color: #184e58; }
QMenu::item:disabled { color: #7a8993; }
QMenu::separator { height: 1px; background: #d5e0e6; margin: 4px 7px; }
QToolTip { color: #233746; background: #f6fbfd; border: 1px solid #91b4c2; padding: 6px 8px; }
QDialogButtonBox, QMessageBox, QFileDialog { background: #f1f5f7; color: #233746; }
'''.replace('@UI@', (resource_root() / 'resources' / 'ui').as_posix())


def apply_theme(app: QApplication | None = None) -> None:
    """Apply native style and every palette group before constructing views.

    A stylesheet alone leaves native popups, empty viewports and disabled
    controls using the system's dark palette. Qt file dialogs intentionally
    use the same Fusion surfaces so they follow the chosen application theme.
    """
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError('Create QApplication before applying the workbench theme.')
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app.setStyle('Fusion')
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: COLORS['window'], QPalette.ColorRole.WindowText: COLORS['ink'],
        QPalette.ColorRole.Base: COLORS['surface'], QPalette.ColorRole.AlternateBase: COLORS['alternate'],
        QPalette.ColorRole.Text: COLORS['ink'], QPalette.ColorRole.Button: COLORS['surface'],
        QPalette.ColorRole.ButtonText: COLORS['ink'], QPalette.ColorRole.BrightText: '#ffffff',
        QPalette.ColorRole.Light: '#ffffff', QPalette.ColorRole.Midlight: '#e6eef3',
        QPalette.ColorRole.Mid: COLORS['border'], QPalette.ColorRole.Dark: '#8ba1ae',
        QPalette.ColorRole.Shadow: '#617582', QPalette.ColorRole.Highlight: COLORS['accent'],
        QPalette.ColorRole.HighlightedText: '#ffffff', QPalette.ColorRole.ToolTipBase: '#f6fbfd',
        QPalette.ColorRole.ToolTipText: COLORS['ink'], QPalette.ColorRole.Link: '#086d9d',
        QPalette.ColorRole.LinkVisited: '#506d8b', QPalette.ColorRole.PlaceholderText: '#718594',
        QPalette.ColorRole.Accent: COLORS['accent'],
    }
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        for role, color in roles.items():
            palette.setColor(group, role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(COLORS['disabled']))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor('#b5cdd1'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(COLORS['ink']))
    app.setPalette(palette)
    # Windows' offscreen platform does not discover system fonts automatically.
    if not QFontDatabase.families():
        font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyleSheet(STYLE)
