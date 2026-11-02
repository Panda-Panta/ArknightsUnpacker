"""Opt-in native acceptance using an explicitly supplied disposable installation."""
from pathlib import Path
import sys
import time
import traceback

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView

from .. import __version__
from ..paths import atomic_json


class ResourceSortingSmoke:
    def __init__(self, app, window, receipt):
        self.app, self.window, self.receipt = app, window, Path(receipt)
        app.setQuitOnLastWindowClosed(False)
        self.started, self.stage = time.monotonic(), 'start'
        self.result = {'version': __version__, 'qt_platform': app.platformName(),
                       'frozen': bool(getattr(sys, 'frozen', False))}
        self.timer = QTimer(window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    @staticmethod
    def column(view, label):
        return next(index for index, column in enumerate(view.model.columns) if column[0] == label)

    def click_sort(self, view, label, order):
        column = self.column(view, label)
        # Start from the other direction, then exercise the actual header click.
        other = Qt.SortOrder.DescendingOrder if order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        view.table.sortByColumn(column, other)
        view.table.scrollTo(view.model.index(0, column), QAbstractItemView.ScrollHint.PositionAtCenter)
        self.app.processEvents()
        header = view.table.horizontalHeader()
        point = QPoint(header.sectionViewportPosition(column) + header.sectionSize(column) // 2,
                       header.height() // 2)
        assert header.viewport().rect().contains(point), (label, point)
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert header.sortIndicatorSection() == column and header.sortIndicatorOrder() == order

    def check_order(self, view, label, key):
        observed = {row['path']: row[key] for row in view.model.rows}
        assert observed and all(value is not None for value in observed.values())
        for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
            self.click_sort(view, label, order)
            values = [row[key] for row in view.model.rows]
            assert values == sorted(values, reverse=order == Qt.SortOrder.DescendingOrder), (label, values)
            view.search.setText('SORT-')
            assert [row[key] for row in view.model.rows] == values, 'Filtering lost the active order'
            view.search.setText('sort-')
            assert [row[key] for row in view.model.rows] == values

    def tick(self):
        try:
            if time.monotonic() - self.started > 40:
                raise TimeoutError('Resource sorting acceptance timed out: ' + self.stage)
            if self.window.queue.busy or self.window._restore_pending:
                return
            if self.stage == 'start':
                # This option is used only against an explicit disposable fixture.
                assert Path(self.window.root_edit.text(), '.sorting-fixture').is_file()
                self.window.scan_priority.setCurrentIndex(self.window.scan_priority.findData('files_only'))
                self.window.scan()
                self.stage = 'scanned'
                return
            services = self.window.services
            scan = services.scan_snapshot
            assert scan is not None and scan.complete, 'Fixture file scan did not finish'
            resources = [record for record in scan.files if Path(record.path).name.startswith('sort-')]
            assert len(resources) == 4
            for record in resources:
                info = (Path(scan.root) / record.path).stat()
                assert record.created_ns == info.st_birthtime_ns
                assert record.mtime_ns == info.st_mtime_ns
            if self.stage == 'scanned':
                self.first_seen = {record.path: record.first_seen_at for record in resources}
                self.window.scan()
                self.stage = 'verified'
                return
            assert {record.path: record.first_seen_at for record in resources} == self.first_seen
            stored = services.store.latest_scan(scan.profile_id)
            assert {record.path: record.created_ns for record in stored.files} == {
                record.path: record.created_ns for record in scan.files}
            view = self.window.explorer
            self.window.pages.select('explorer')
            self.window.resize(1650, 950)
            view.splitter.setSizes([160, 1200, 260])
            view.recursive.setChecked(True)
            view.search.setText('sort-')
            assert len(view.model.rows) == 4
            self.check_order(view, '大小', 'size')
            # Restrict again after check_order clears the search.
            for label, key in (('修改时间', 'mtime_ns'), ('创建时间', 'created_ns'), ('首次观测', 'first_seen_at')):
                view.search.setText('sort-')
                self.check_order(view, label, key)
            view.search.setText('sort-')
            view.table.selectRow(0)
            selected = view.selected_paths()
            self.click_sort(view, '大小', Qt.SortOrder.AscendingOrder)
            assert view.selected_paths() == selected
            assert '创建时间' in view.details.toPlainText() and '首次观测' in view.details.toPlainText()
            original = {record.path: record for record in resources}
            view.layer.setCurrentIndex(1)
            assert len(view.model.rows) == 4
            for row in view.model.rows:
                assert row['created_ns'] == original[row['path']].created_ns
                assert row['first_seen_at'] == original[row['path']].first_seen_at
            updates = self.window.updates
            self.window.pages.select('updates')
            updates.search.setText('sort-')
            self.check_order(updates, '大小', 'size')
            for label, key in (('修改时间', 'mtime_ns'), ('首次观测', 'first_seen_at')):
                updates.search.setText('sort-')
                self.check_order(updates, label, key)
            self.window.pages.select('explorer')
            view.search.setText('sort-')
            view.layer.setCurrentIndex(0)
            view.table.scrollTo(view.model.index(0, self.column(view, '创建时间')))
            image = self.receipt.with_suffix('.png')
            assert self.window.grab().save(str(image))
            self.result.update(success=True, scanned_resource_count=4,
                               header_click_orders_verified=True, filter_order_preserved=True,
                               selected_file_preserved=True, precise_filesystem_creation_time=True,
                               first_observation_preserved=True, saved_times_round_trip=True,
                               effective_resource_times_match=True, updates_raw_order_verified=True,
                               screenshot=str(image), elapsed_seconds=round(time.monotonic() - self.started, 2))
            self.finish(0)
        except Exception:
            self.result.update(success=False, stage=self.stage, traceback=traceback.format_exc())
            self.finish(1)

    def finish(self, code):
        self.timer.stop()
        atomic_json(self.receipt, self.result)
        self.window.close()
        QTimer.singleShot(150, lambda: self.app.exit(code))
