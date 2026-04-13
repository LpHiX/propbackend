import argparse
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, cast

import h5py
import numpy as np

QtCore: Any
QtGui: Any
QtWidgets: Any
pg: Any

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    import pyqtgraph as pg
except ImportError:
    QtCore = None
    QtGui = None
    QtWidgets = None
    pg = None

BaseWindow: type = cast(type, QtWidgets.QMainWindow) if QtWidgets is not None else object


@dataclass(frozen=True)
class ChannelRecord:
    name: str
    unit: str
    signal_type: str
    samples: int
    time: np.ndarray
    values: np.ndarray


class H5ViewerWindow(BaseWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BoardState H5 Viewer")
        self.resize(1450, 900)

        self.current_file: Path | None = None
        self.channels: Dict[str, ChannelRecord] = {}
        self.selected_channels: set[str] = set()
        self.unit_plots: Dict[str, Any] = {}
        self.unit_curves: Dict[str, Dict[str, Any]] = {}
        self.color_cycle = itertools.cycle(
            [
                "#1f77b4",
                "#d62728",
                "#2ca02c",
                "#ff7f0e",
                "#17becf",
                "#e377c2",
                "#bcbd22",
                "#7f7f7f",
            ]
        )
        self.channel_color: Dict[str, str] = {}
        self._table_mutation = False

        self._build_ui()
        self._build_menu()
        self._connect_signals()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        left_panel = QtWidgets.QFrame()
        left_panel.setMinimumWidth(430)
        left_panel.setMaximumWidth(520)
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        self.file_label = QtWidgets.QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        left_layout.addWidget(self.file_label)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Filter channels (name / unit / signal type)")
        left_layout.addWidget(self.search_edit)

        self.use_raw_checkbox = QtWidgets.QCheckBox("Use raw data when available")
        self.use_raw_checkbox.setChecked(False)
        left_layout.addWidget(self.use_raw_checkbox)

        self.channel_table = QtWidgets.QTableWidget(0, 5)
        self.channel_table.setHorizontalHeaderLabels(["Plot", "Channel", "Unit", "Signal", "Samples"])
        self.channel_table.verticalHeader().setVisible(False)
        self.channel_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.channel_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.channel_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.channel_table.setAlternatingRowColors(True)
        self.channel_table.setSortingEnabled(True)
        header = self.channel_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        left_layout.addWidget(self.channel_table, 1)

        self.clear_button = QtWidgets.QPushButton("Clear all plotted channels")
        left_layout.addWidget(self.clear_button)

        root.addWidget(left_panel)

        self.plot_scroll = QtWidgets.QScrollArea()
        self.plot_scroll.setWidgetResizable(True)
        self.plot_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        self.plot_container = QtWidgets.QWidget()
        self.plot_layout = QtWidgets.QVBoxLayout(self.plot_container)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_layout.setSpacing(8)
        self.plot_layout.addStretch(1)

        self.plot_scroll.setWidget(self.plot_container)
        root.addWidget(self.plot_scroll, 1)

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("File")

        open_action = QtGui.QAction("Open...", self)
        open_action.setShortcut(QtGui.QKeySequence.Open)
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)

        close_action = QtGui.QAction("Close", self)
        close_action.triggered.connect(self._close_current_file)
        file_menu.addAction(close_action)

        file_menu.addSeparator()

        exit_action = QtGui.QAction("Exit", self)
        exit_action.setShortcut(QtGui.QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _connect_signals(self) -> None:
        self.search_edit.textChanged.connect(self._apply_table_filter)
        self.channel_table.cellClicked.connect(self._on_table_clicked)
        self.channel_table.itemChanged.connect(self._on_table_item_changed)
        self.use_raw_checkbox.stateChanged.connect(self._reload_current_file_data)
        self.clear_button.clicked.connect(self._clear_all_channels)

    def _open_file_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open BoardState H5 File",
            str(Path.cwd()),
            "HDF5 Files (*.h5 *.hdf5);;All Files (*)",
        )
        if not path:
            return
        self._load_file(Path(path))

    def _load_file(self, path: Path) -> None:
        try:
            self.channels = self._read_channels(path, use_raw=self.use_raw_checkbox.isChecked())
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Open failed", f"Failed to open file:\n{exc}")
            return

        self.current_file = path
        self.selected_channels.clear()
        self.unit_plots.clear()
        self.unit_curves.clear()
        self.channel_color.clear()
        self._clear_plot_widgets()

        self.file_label.setText(f"Loaded: {path}")
        self._populate_channel_table()
        self.statusBar().showMessage(f"Loaded {len(self.channels)} channels")

    def _reload_current_file_data(self) -> None:
        if self.current_file is None:
            return
        selected_before = set(self.selected_channels)
        self._load_file(self.current_file)
        for channel in selected_before:
            if channel in self.channels:
                self._set_table_checked(channel, True)
                self._set_channel_enabled(channel, True)

    def _close_current_file(self) -> None:
        self.current_file = None
        self.channels.clear()
        self.selected_channels.clear()
        self.unit_plots.clear()
        self.unit_curves.clear()
        self.channel_color.clear()
        self._clear_plot_widgets()
        self.channel_table.setRowCount(0)
        self.file_label.setText("No file loaded")
        self.statusBar().clearMessage()

    def _read_channels(self, path: Path, use_raw: bool) -> Dict[str, ChannelRecord]:
        channels: Dict[str, ChannelRecord] = {}

        with h5py.File(path, "r") as h5:
            if "channels" not in h5 or not isinstance(h5["channels"], h5py.Group):
                return channels

            for channel_name in h5["channels"].keys():
                group = h5["channels"][channel_name]
                if not isinstance(group, h5py.Group):
                    continue
                if "time" not in group or "data" not in group:
                    continue

                time_values = np.asarray(group["time"][:], dtype=float)
                if use_raw and "raw" in group:
                    data_values = np.asarray(group["raw"][:], dtype=float)
                else:
                    data_values = np.asarray(group["data"][:], dtype=float)

                if len(time_values) != len(data_values):
                    size = min(len(time_values), len(data_values))
                    time_values = time_values[:size]
                    data_values = data_values[:size]

                channels[channel_name] = ChannelRecord(
                    name=channel_name,
                    unit=str(group.attrs.get("unit", "unknown")) or "unknown",
                    signal_type=str(group.attrs.get("signal_type", "unknown")) or "unknown",
                    samples=len(time_values),
                    time=time_values,
                    values=data_values,
                )

        return channels

    def _populate_channel_table(self) -> None:
        self.channel_table.setSortingEnabled(False)
        self.channel_table.setRowCount(0)

        for row, name in enumerate(sorted(self.channels.keys())):
            channel = self.channels[name]
            self.channel_table.insertRow(row)

            check_item = QtWidgets.QTableWidgetItem("")
            check_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
            check_item.setCheckState(QtCore.Qt.Unchecked)
            check_item.setData(QtCore.Qt.UserRole, channel.name)
            self.channel_table.setItem(row, 0, check_item)

            self.channel_table.setItem(row, 1, QtWidgets.QTableWidgetItem(channel.name))
            self.channel_table.setItem(row, 2, QtWidgets.QTableWidgetItem(channel.unit))
            self.channel_table.setItem(row, 3, QtWidgets.QTableWidgetItem(channel.signal_type))
            self.channel_table.setItem(row, 4, QtWidgets.QTableWidgetItem(str(channel.samples)))

        self.channel_table.setSortingEnabled(True)
        self._apply_table_filter()

    def _apply_table_filter(self) -> None:
        query = self.search_edit.text().strip().lower()
        for row in range(self.channel_table.rowCount()):
            name_item = self.channel_table.item(row, 1)
            unit_item = self.channel_table.item(row, 2)
            signal_item = self.channel_table.item(row, 3)
            haystack = " ".join(
                [
                    name_item.text().lower() if name_item else "",
                    unit_item.text().lower() if unit_item else "",
                    signal_item.text().lower() if signal_item else "",
                ]
            )
            self.channel_table.setRowHidden(row, query not in haystack)

    def _on_table_clicked(self, row: int, column: int) -> None:
        if column == 0:
            return

        check_item = self.channel_table.item(row, 0)
        if check_item is None:
            return

        channel_name = check_item.data(QtCore.Qt.UserRole)
        if not isinstance(channel_name, str):
            return

        new_checked = check_item.checkState() != QtCore.Qt.Checked
        self._set_table_checked(channel_name, new_checked)

    def _on_table_item_changed(self, item) -> None:
        if self._table_mutation:
            return
        if item.column() != 0:
            return

        channel_name = item.data(QtCore.Qt.UserRole)
        if not isinstance(channel_name, str):
            return

        enabled = item.checkState() == QtCore.Qt.Checked
        self._set_channel_enabled(channel_name, enabled)

    def _set_table_checked(self, channel_name: str, checked: bool) -> None:
        self._table_mutation = True
        try:
            for row in range(self.channel_table.rowCount()):
                check_item = self.channel_table.item(row, 0)
                if check_item is None:
                    continue
                if check_item.data(QtCore.Qt.UserRole) == channel_name:
                    check_item.setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
                    break
        finally:
            self._table_mutation = False

        self._set_channel_enabled(channel_name, checked)

    def _set_channel_enabled(self, channel_name: str, enabled: bool) -> None:
        channel = self.channels.get(channel_name)
        if channel is None:
            return

        had_no_channels = len(self.selected_channels) == 0

        if enabled:
            self.selected_channels.add(channel_name)
            self._ensure_unit_plot(channel.unit)
            self._add_curve(channel)
            if had_no_channels:
                self._view_all_plots()
        else:
            self.selected_channels.discard(channel_name)
            self._remove_curve(channel)
            self._prune_empty_unit_plots()

    def _ensure_unit_plot(self, unit: str) -> None:
        if unit in self.unit_plots:
            return

        plot = pg.PlotWidget(title=f"Unit: {unit}")
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setLabel("left", f"Value ({unit})")
        plot.setLabel("bottom", "Time (s)")

        if self.unit_plots:
            first_plot = next(iter(self.unit_plots.values()))
            plot.setXLink(first_plot)

        self.plot_layout.insertWidget(max(0, self.plot_layout.count() - 1), plot, 1)
        self.unit_plots[unit] = plot
        self.unit_curves[unit] = {}

    def _add_curve(self, channel: ChannelRecord) -> None:
        if channel.name not in self.channel_color:
            self.channel_color[channel.name] = next(self.color_cycle)

        plot = self.unit_plots[channel.unit]
        pen = pg.mkPen(self.channel_color[channel.name], width=2)
        curve = plot.plot(channel.time, channel.values, pen=pen, name=channel.name)
        self.unit_curves[channel.unit][channel.name] = curve

    def _remove_curve(self, channel: ChannelRecord) -> None:
        curves = self.unit_curves.get(channel.unit, {})
        curve = curves.pop(channel.name, None)
        if curve is not None:
            self.unit_plots[channel.unit].removeItem(curve)

    def _prune_empty_unit_plots(self) -> None:
        for unit in list(self.unit_plots.keys()):
            if self.unit_curves.get(unit):
                continue
            plot = self.unit_plots.pop(unit)
            self.unit_curves.pop(unit, None)
            self.plot_layout.removeWidget(plot)
            plot.deleteLater()

    def _view_all_plots(self) -> None:
        for plot in self.unit_plots.values():
            plot.enableAutoRange(axis=pg.ViewBox.XYAxes)
            plot.autoRange()

    def _clear_all_channels(self) -> None:
        self.selected_channels.clear()
        self.unit_curves.clear()
        self.unit_plots.clear()
        self.channel_color.clear()

        self._clear_plot_widgets()

        for row in range(self.channel_table.rowCount()):
            self._table_mutation = True
            check_item = self.channel_table.item(row, 0)
            if check_item is not None:
                check_item.setCheckState(QtCore.Qt.Unchecked)
            self._table_mutation = False

    def _clear_plot_widgets(self) -> None:
        while self.plot_layout.count() > 1:
            item = self.plot_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


def main() -> int:
    parser = argparse.ArgumentParser(description="BoardStateLogger H5 interactive viewer")
    parser.add_argument("h5", nargs="?", help="Optional path to .h5 file")
    args = parser.parse_args()

    if QtWidgets is None or pg is None:
        print("This viewer requires PySide6 and pyqtgraph.")
        print("Install with: pip install pyside6 pyqtgraph")
        return 1

    app = QtWidgets.QApplication([])
    pg.setConfigOptions(antialias=True, foreground="#d8dee9", background="#111217")

    window = H5ViewerWindow()
    window.show()

    if args.h5:
        input_path = Path(args.h5)
        if input_path.exists():
            window._load_file(input_path)
        else:
            QtWidgets.QMessageBox.warning(window, "Missing file", f"File does not exist:\n{input_path}")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
