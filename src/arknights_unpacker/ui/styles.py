"""Quiet slate workbench with a teal scan rail; compact native desktop density."""

STYLE = '''
QMainWindow, QDialog { background: #edf2f5; }
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 12px; color: #243543; }
QLabel#appTitle { font-size: 19px; font-weight: 700; color: #203c4b; }
QLabel#subtitle { color: #607786; }
QFrame#header { background: #ffffff; border-bottom: 3px solid #168b86; }
QPushButton { padding: 7px 12px; border: 1px solid #bccbd4; border-radius: 4px; background: #ffffff; }
QPushButton:hover { background: #e3f0f0; border-color: #168b86; }
QPushButton:pressed { background: #d0e6e4; }
QPushButton:disabled { color: #94a2ac; background: #edf1f3; border-color: #d5dfe5; }
QPushButton[primary="true"] { background: #147c78; border-color: #147c78; color: white; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #116a67; }
QPushButton[primary="true"]:disabled { background: #a4bcbb; border-color: #a4bcbb; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: white; padding: 6px; border: 1px solid #c4d1d9; border-radius: 3px; selection-background-color: #167e79; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 2px solid #168b86; }
QTabWidget::pane { border: 1px solid #ced9df; background: #f7fafb; }
QTabBar::tab { padding: 11px 22px; background: #e3ebf0; border-bottom: 3px solid transparent; }
QTabBar::tab:selected { background: #f7fafb; border-bottom: 3px solid #168b86; font-weight: 600; }
QTreeView, QTableView, QTextBrowser, QPlainTextEdit { background: #ffffff; border: 1px solid #cbd7df; alternate-background-color: #f2f6f8; selection-background-color: #d7eeeb; selection-color: #134b48; }
QHeaderView::section { background: #e8eff3; border: 0; border-right: 1px solid #d6e0e6; border-bottom: 1px solid #c5d2da; padding: 8px; font-weight: 600; }
QTreeView::item, QTableView::item { min-height: 26px; }
QGroupBox { background: #f8fbfc; border: 1px solid #c9d6df; border-radius: 5px; margin-top: 13px; padding: 15px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; font-weight: 600; }
QProgressBar { border: 1px solid #c4d2da; border-radius: 3px; background: #e4edf1; text-align: center; min-height: 15px; }
QProgressBar::chunk { background: #168b86; }
QStatusBar { background: #e0e9ee; }
QSplitter::handle { background: #edf2f5; width: 7px; }
QCheckBox { spacing: 5px; }
'''
