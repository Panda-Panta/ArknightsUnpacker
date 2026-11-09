"""Entry point for the portable map preview application and its workers."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .jobs import worker_command
from .paths import atomic_json, program_root, resource_root, validate_data_root, validate_output


def main() -> int:
    if (result := worker_command(sys.argv)) is not None:
        return result

    parser = argparse.ArgumentParser(description='明日方舟关卡预览器')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--game-root', default='')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--runtime-dir', type=Path)
    parser.add_argument('--smoke-test', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .application import AppServices
    from .ui.level_preview_window import LevelPreviewWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName('ArknightsLevelPreview')
    app.setApplicationVersion(__version__)
    app.setOrganizationName('ArknightsLevelPreview')
    app.setWindowIcon(QIcon(str(resource_root() / 'resources/ui/app-icon.png')))
    frozen = bool(getattr(sys, 'frozen', False))
    root = program_root() if frozen else program_root() / '.work/level-preview'
    data = args.data_dir or root / 'data'
    exports = args.output_dir or root / 'exports'
    receipt = None
    try:
        services = AppServices(data, output_root=exports)
        app.aboutToQuit.connect(services.shutdown)
        if args.smoke_test:
            receipt = validate_output(validate_data_root(args.smoke_test),
                                      args.game_root or services.config.get('game_root'))
        if args.runtime_dir:
            runtime = args.runtime_dir.expanduser().resolve(strict=True)
            if not runtime.is_dir():
                raise ValueError('播放组件路径必须是目录。')
            services.config['level_preview_runtime'] = str(runtime)
            services.save_config()
        window = LevelPreviewWindow(services, initial_root=args.game_root)
    except (OSError, ValueError) as error:
        if args.smoke_test:
            if receipt:
                atomic_json(receipt, {'error': str(error)})
            elif sys.stderr is not None:
                print(str(error), file=sys.stderr)
        else:
            QMessageBox.critical(None, '无法启动关卡预览器', str(error))
        return 1

    window.show()
    if receipt:
        def record_startup():
            atomic_json(receipt, {
                'application': app.applicationName(), 'frozen': frozen, 'title': window.windowTitle(),
                'visible': window.isVisible(), 'data_root': str(services.data_root),
                'game_root': window.root_edit.text(), 'tabs': window.tabs.count(),
                'native_replay': window.page._native_preloader is not None,
            })
            window.close()

        QTimer.singleShot(100, record_startup)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
