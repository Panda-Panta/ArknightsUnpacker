"""A light, PRTS-inspired native workbench, independent of the Windows theme."""

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication
from arknights_unpacker.paths import resource_root


COLORS = {
    'window': '#f2f5f8', 'surface': '#ffffff', 'alternate': '#f7fafc',
    'ink': '#1c2834', 'muted': '#586c7d', 'border': '#c5d3de',
    'accent': '#0093a2', 'selection': '#deeff2', 'disabled': '#768794',
}


STYLE = '''
QWidget { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif; font-size: 13px; color: #1c2834; }
QMainWindow, QDialog { background: #f2f5f8; }
QWidget:disabled { color: #768794; }
QLabel { background: transparent; }
QLabel#appTitle { font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei UI"; font-size: 20px; font-weight: 700; color: #14222e; letter-spacing: 0.5px; }
QLabel#subtitle, QLabel[muted="true"] { color: #586c7d; font-size: 12px; }
QLabel#sessionStatus { color: #3b5364; font-size: 12px; font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; }
QLabel[notice="warning"] { color: #854d0e; background: #fefce8; border: 1px solid #fde047; border-left: 4px solid #eab308; border-radius: 4px; padding: 9px 12px; font-weight: 500; }
QFrame#header { background: #ffffff; border: 1px solid #d4dfe7; border-radius: 4px; border-bottom: 3px solid #0093a2; }
QPushButton, QToolButton { padding: 6px 14px; border: 1px solid #c8d5df; border-radius: 4px; background: #ffffff; color: #1c2834; font-weight: 500; }
QPushButton:hover, QToolButton:hover { background: #eef6f8; border-color: #3bb2c0; color: #00707e; }
QPushButton:focus, QToolButton:focus { border-color: #0093a2; background: #f4fafb; outline: none; }
QPushButton:pressed, QToolButton:pressed, QPushButton:checked { background: #d7edf1; border-color: #0093a2; color: #005b66; }
QPushButton:disabled, QToolButton:disabled { color: #82939f; background: #edf2f5; border-color: #d6e0e6; }
QPushButton[primary="true"] { background: #0093a2; border: 1px solid #008290; border-radius: 4px; color: #ffffff; font-weight: 600; padding: 7px 16px; }
QPushButton[primary="true"]:hover { background: #008290; border-color: #00707c; }
QPushButton[primary="true"]:focus { background: #008290; border: 1px solid #14222e; }
QPushButton[primary="true"]:pressed { background: #006e79; }
QPushButton[primary="true"]:disabled { background: #b0c9ce; border-color: #b0c9ce; color: #f4f8fa; }
QLineEdit, QAbstractSpinBox, QComboBox { min-height: 22px; padding: 5px 9px; border: 1px solid #c8d5df; border-radius: 4px; background: #ffffff; color: #1c2834; selection-background-color: #0093a2; selection-color: #ffffff; }
QLineEdit:hover, QAbstractSpinBox:hover, QComboBox:hover { border-color: #7ba3b8; }
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus { border-color: #0093a2; }
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled { background: #edf2f5; border-color: #d6e0e6; color: #82939f; }
QLineEdit[readOnly="true"] { background: #f5f8fa; color: #3b505f; }
QComboBox { padding-right: 32px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border-left: 1px solid #d5e0e7; border-top-right-radius: 3px; border-bottom-right-radius: 3px; background: #f6f9fb; }
QComboBox::drop-down:hover { background: #e6f3f6; }
QComboBox::drop-down:disabled { background: #edf2f5; border-color: #d6e0e6; }
QComboBox::down-arrow { image: url("@UI@/arrow-down.svg"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { background: #ffffff; color: #1c2834; border: 1px solid #8caec0; border-radius: 4px; outline: 0; selection-background-color: #e1f2f5; selection-color: #085562; padding: 4px; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 4px 8px; border-radius: 3px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; border-left: 1px solid #d5e0e7; border-bottom: 1px solid #d5e0e7; background: #f6f9fb; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border-left: 1px solid #d5e0e7; background: #f6f9fb; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: #e6f3f6; }
QSpinBox::up-button:disabled, QSpinBox::down-button:disabled, QDoubleSpinBox::up-button:disabled, QDoubleSpinBox::down-button:disabled { background: #edf2f5; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@UI@/arrow-up.svg"); width: 8px; height: 5px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@UI@/arrow-down.svg"); width: 8px; height: 5px; }
QTabWidget::pane { border: 1px solid #c8d5df; background: #ffffff; border-radius: 0 0 4px 4px; }
QTabBar::tab { padding: 11px 24px; color: #586c7d; background: #e6edf2; border: 0; border-top: 2px solid transparent; border-bottom: 3px solid transparent; font-weight: 500; font-size: 13px; }
QTabBar::tab:hover { color: #1c2834; background: #eff5f7; }
QTabBar::tab:selected { color: #006f7b; background: #ffffff; border-bottom: 3px solid #0093a2; font-weight: 700; }
QTabBar::tab:disabled { color: #82939f; }
QTreeView, QTableView, QListView, QTextBrowser, QTextEdit, QPlainTextEdit { background: #ffffff; color: #1c2834; border: 1px solid #c8d5df; border-radius: 4px; alternate-background-color: #f7fafc; gridline-color: #e4edf2; selection-background-color: #e1f2f5; selection-color: #064b56; }
QTreeView:focus, QTableView:focus, QListView:focus, QTextBrowser:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #0093a2; }
QTreeView::item, QTableView::item, QListView::item { min-height: 28px; padding: 3px 6px; }
QTreeView::item:hover, QTableView::item:hover, QListView::item:hover { background: #f0f7f9; }
QTreeView::item:selected, QTableView::item:selected, QListView::item:selected { background: #e1f2f5; color: #064b56; }
QTreeView::item:disabled, QTableView::item:disabled, QListView::item:disabled { color: #82939f; }
QHeaderView { background: #eaf0f5; }
QHeaderView::section { color: #2e495a; background: #eaf0f5; border: 0; border-right: 1px solid #d4dfe6; border-bottom: 1px solid #c8d5df; padding: 8px 10px; font-weight: 600; font-size: 12px; }
QHeaderView::section:hover { background: #dceef2; color: #00606b; }
QTableCornerButton::section { background: #eaf0f5; border: 0; border-right: 1px solid #d4dfe6; border-bottom: 1px solid #c8d5df; }
QGroupBox { background: #fafcfe; border: 1px solid #cbd7e0; border-radius: 6px; margin-top: 14px; padding: 16px 14px 14px 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; color: #1e3a4a; font-weight: 600; font-size: 12px; letter-spacing: 0.3px; }
QProgressBar { border: 1px solid #c8d5df; border-radius: 4px; background: #e5edf2; color: #1c2834; text-align: center; min-height: 18px; font-weight: 600; font-size: 11px; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0093a2, stop:1 #00b4c8); border-radius: 3px; }
QStatusBar { color: #3b5364; background: #e8eff4; border-top: 1px solid #d0dce4; font-size: 12px; padding: 3px 6px; }
QStatusBar::item { border: 0; }
QSplitter::handle { background: #f2f5f8; width: 6px; height: 6px; }
QSplitter::handle:hover { background: #b0d8e0; }
QCheckBox, QRadioButton { spacing: 8px; padding: 2px; border: 1px solid transparent; background: transparent; }
QCheckBox:focus, QRadioButton:focus { border: 1px dashed #0093a2; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator { border: 1px solid #8ca2b0; border-radius: 3px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #0093a2; background: #edf6f8; }
QCheckBox::indicator:checked { border-color: #0093a2; background: #0093a2; image: url("@UI@/check.svg"); }
QCheckBox::indicator:disabled { border-color: #c8d5df; background: #edf2f5; }
QCheckBox::indicator:checked:disabled { border-color: #b0c9ce; background: #b0c9ce; }
QRadioButton::indicator { border: 1px solid #8ca2b0; border-radius: 8px; background: #ffffff; }
QRadioButton::indicator:hover { border-color: #0093a2; }
QRadioButton::indicator:checked { border: 5px solid #0093a2; }
QScrollArea { border: 1px solid #c8d5df; border-radius: 4px; background: #edf2f5; }
QScrollArea > QWidget > QWidget { background: #f2f5f8; }
QLabel[imageCanvas="true"] { background: #e6edf2; }
QScrollBar:vertical { width: 10px; background: #edf2f5; margin: 0; }
QScrollBar::handle:vertical { min-height: 28px; background: #b8c8d3; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #7a98a8; }
QScrollBar:horizontal { height: 10px; background: #edf2f5; margin: 0; }
QScrollBar::handle:horizontal { min-width: 28px; background: #b8c8d3; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #7a98a8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenuBar, QMenu { background: #ffffff; color: #1c2834; }
QMenu { border: 1px solid #c4d2dc; border-radius: 4px; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 3px; }
QMenu::item:selected { background: #e1f2f5; color: #085562; }
QMenu::item:disabled { color: #82939f; }
QMenu::separator { height: 1px; background: #d4dfe6; margin: 4px 6px; }
QToolTip { color: #162430; background: #f8fafc; border: 1px solid #7ea3b7; border-radius: 4px; padding: 7px 10px; font-size: 12px; }
QDialogButtonBox, QMessageBox, QFileDialog { background: #f2f5f8; color: #1c2834; }
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
