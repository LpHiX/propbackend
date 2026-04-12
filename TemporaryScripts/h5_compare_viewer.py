import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import h5py
import numpy as np


try:
    from PySide6 import QtCore, QtWidgets
    import pyqtgraph as pg
except ImportError:
    QtCore = None
    QtWidgets = None
    pg = None


@dataclass
class ChannelData:
    time: np.ndarray
    data: np.ndarray
    raw: np.ndarray
    unit: str


@dataclass
class RunData:
    path: Path
    channels: Dict[str, ChannelData]
    events: Dict[str, List]


def _decode_array(dataset) -> List[str]:
    values = dataset[()]
    if np.isscalar(values):
        values = [values]
    out: List[str] = []
    for v in values:
        if isinstance(v, bytes):
            out.append(v.decode("utf-8", errors="replace"))
        else:
            out.append(str(v))
    return out


def load_run(path: Path) -> RunData:
    with h5py.File(path, "r") as h5:
        channels: Dict[str, ChannelData] = {}
        if "channels" in h5:
            for name in h5["channels"].keys():
                group = h5["channels"][name]
                if not isinstance(group, h5py.Group):
                    continue
                if not all(key in group for key in ("time", "data", "raw")):
                    continue
                channels[name] = ChannelData(
                    time=np.asarray(group["time"][:], dtype=float),
                    data=np.asarray(group["data"][:], dtype=float),
                    raw=np.asarray(group["raw"][:], dtype=float),
                    unit=str(group.attrs.get("unit", "")),
                )

        events = {"time": [], "type": [], "source": [], "target": [], "message": []}
        if "events" in h5 and isinstance(h5["events"], h5py.Group):
            eg = h5["events"]
            if "time" in eg:
                events["time"] = list(np.asarray(eg["time"][:], dtype=float))
            for key in ("type", "source", "target", "message"):
                if key in eg:
                    events[key] = _decode_array(eg[key])

    return RunData(path=path, channels=channels, events=events)


def first_event_time(run: RunData, event_type: str) -> Optional[float]:
    for t, et in zip(run.events.get("time", []), run.events.get("type", [])):
        if et == event_type:
            return float(t)
    return None


def safe_interp(x_target: np.ndarray, x_src: np.ndarray, y_src: np.ndarray) -> np.ndarray:
    if len(x_src) < 2:
        return np.full_like(x_target, np.nan, dtype=float)
    mask = ~np.isnan(x_src) & ~np.isnan(y_src)
    x = x_src[mask]
    y = y_src[mask]
    if len(x) < 2:
        return np.full_like(x_target, np.nan, dtype=float)

    order = np.argsort(x)
    x = x[order]
    y = y[order]

    y_interp = np.interp(x_target, x, y)
    out_of_range = (x_target < x[0]) | (x_target > x[-1])
    y_interp[out_of_range] = np.nan
    return y_interp


class CompareWindow(QtWidgets.QMainWindow):
    def __init__(self, run_a: RunData, run_b: RunData):
        super().__init__()
        self.run_a = run_a
        self.run_b = run_b

        self.setWindowTitle(f"H5 Compare Viewer: {run_a.path.name} vs {run_b.path.name}")
        self.resize(1400, 900)

        self.common_channels = sorted(set(run_a.channels.keys()) & set(run_b.channels.keys()))
        self.event_types = sorted(set(run_a.events.get("type", []) + run_b.events.get("type", [])))

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        controls = QtWidgets.QFrame()
        controls.setMaximumWidth(360)
        controls_layout = QtWidgets.QVBoxLayout(controls)
        root.addWidget(controls)

        self.channel_combo = QtWidgets.QComboBox()
        self.channel_combo.addItems(self.common_channels)
        controls_layout.addWidget(QtWidgets.QLabel("Channel"))
        controls_layout.addWidget(self.channel_combo)

        self.align_mode_combo = QtWidgets.QComboBox()
        self.align_mode_combo.addItems(["start", "event", "manual"])
        controls_layout.addWidget(QtWidgets.QLabel("Alignment mode"))
        controls_layout.addWidget(self.align_mode_combo)

        self.event_combo = QtWidgets.QComboBox()
        self.event_combo.addItems(self.event_types if self.event_types else ["state_transition"])
        controls_layout.addWidget(QtWidgets.QLabel("Reference event type"))
        controls_layout.addWidget(self.event_combo)

        self.manual_a = QtWidgets.QDoubleSpinBox()
        self.manual_a.setRange(-1e6, 1e6)
        self.manual_a.setDecimals(3)
        self.manual_a.setSingleStep(0.1)
        controls_layout.addWidget(QtWidgets.QLabel("Manual offset A (s)"))
        controls_layout.addWidget(self.manual_a)

        self.manual_b = QtWidgets.QDoubleSpinBox()
        self.manual_b.setRange(-1e6, 1e6)
        self.manual_b.setDecimals(3)
        self.manual_b.setSingleStep(0.1)
        controls_layout.addWidget(QtWidgets.QLabel("Manual offset B (s)"))
        controls_layout.addWidget(self.manual_b)

        self.show_raw = QtWidgets.QCheckBox("Use raw instead of data")
        controls_layout.addWidget(self.show_raw)

        self.event_lines = QtWidgets.QCheckBox("Show event lines")
        self.event_lines.setChecked(True)
        controls_layout.addWidget(self.event_lines)

        self.metrics_box = QtWidgets.QPlainTextEdit()
        self.metrics_box.setReadOnly(True)
        self.metrics_box.setMinimumHeight(260)
        controls_layout.addWidget(QtWidgets.QLabel("Metrics"))
        controls_layout.addWidget(self.metrics_box, 1)

        self.export_btn = QtWidgets.QPushButton("Export current view PNG")
        controls_layout.addWidget(self.export_btn)
        controls_layout.addStretch(1)

        plots = QtWidgets.QWidget()
        plots_layout = QtWidgets.QVBoxLayout(plots)
        root.addWidget(plots, 1)

        self.plot_overlay = pg.PlotWidget(title="Overlay")
        self.plot_delta = pg.PlotWidget(title="Delta (A - B)")
        self.plot_delta.setXLink(self.plot_overlay)
        plots_layout.addWidget(self.plot_overlay, 2)
        plots_layout.addWidget(self.plot_delta, 1)

        self._connect_signals()
        if self.common_channels:
            self._refresh_plots()

    def _connect_signals(self) -> None:
        self.channel_combo.currentIndexChanged.connect(self._refresh_plots)
        self.align_mode_combo.currentIndexChanged.connect(self._refresh_plots)
        self.event_combo.currentIndexChanged.connect(self._refresh_plots)
        self.manual_a.valueChanged.connect(self._refresh_plots)
        self.manual_b.valueChanged.connect(self._refresh_plots)
        self.show_raw.stateChanged.connect(self._refresh_plots)
        self.event_lines.stateChanged.connect(self._refresh_plots)
        self.export_btn.clicked.connect(self._export_png)

    def _alignment_offsets(self) -> Tuple[float, float]:
        mode = self.align_mode_combo.currentText()
        if mode == "start":
            return 0.0, 0.0

        if mode == "manual":
            return self.manual_a.value(), self.manual_b.value()

        event_type = self.event_combo.currentText()
        ta = first_event_time(self.run_a, event_type)
        tb = first_event_time(self.run_b, event_type)
        return (ta if ta is not None else 0.0, tb if tb is not None else 0.0)

    def _selected_channel(self) -> Optional[str]:
        if not self.common_channels:
            return None
        return self.channel_combo.currentText()

    def _series(self, run: RunData, channel_name: str, use_raw: bool) -> Tuple[np.ndarray, np.ndarray]:
        channel = run.channels[channel_name]
        y = channel.raw if use_raw else channel.data
        return channel.time.copy(), y.copy()

    def _refresh_plots(self) -> None:
        channel_name = self._selected_channel()
        if not channel_name:
            self.metrics_box.setPlainText("No common channels found between runs.")
            return

        use_raw = self.show_raw.isChecked()
        offset_a, offset_b = self._alignment_offsets()

        xa, ya = self._series(self.run_a, channel_name, use_raw)
        xb, yb = self._series(self.run_b, channel_name, use_raw)
        xa = xa - offset_a
        xb = xb - offset_b

        self.plot_overlay.clear()
        self.plot_delta.clear()

        pen_a = pg.mkPen((80, 150, 255), width=2)
        pen_b = pg.mkPen((255, 170, 80), width=2)
        pen_d = pg.mkPen((220, 100, 100), width=2)

        self.plot_overlay.plot(xa, ya, pen=pen_a, name="Run A")
        self.plot_overlay.plot(xb, yb, pen=pen_b, name="Run B")

        yb_interp = safe_interp(xa, xb, yb)
        delta = ya - yb_interp
        self.plot_delta.plot(xa, delta, pen=pen_d)

        if self.event_lines.isChecked():
            self._add_event_lines(self.plot_overlay, self.run_a.events, -offset_a, (100, 150, 255, 70))
            self._add_event_lines(self.plot_overlay, self.run_b.events, -offset_b, (255, 180, 100, 70))

        unit = self.run_a.channels[channel_name].unit
        self.plot_overlay.setLabel("left", f"value ({unit})" if unit else "value")
        self.plot_overlay.setLabel("bottom", "aligned_time_s")
        self.plot_delta.setLabel("left", f"delta ({unit})" if unit else "delta")
        self.plot_delta.setLabel("bottom", "aligned_time_s")

        self._update_metrics(channel_name, xa, ya, xb, yb, delta)

    def _add_event_lines(self, plot_widget: pg.PlotWidget, events: Dict[str, List], shift: float, color) -> None:
        times = events.get("time", [])
        types = events.get("type", [])
        for t, et in zip(times[:100], types[:100]):
            x = float(t) + shift
            line = pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen(color, width=1))
            line.setToolTip(et)
            plot_widget.addItem(line)

    def _update_metrics(self, channel_name: str, xa: np.ndarray, ya: np.ndarray, xb: np.ndarray, yb: np.ndarray, delta: np.ndarray) -> None:
        valid_a = ~np.isnan(ya)
        valid_b = ~np.isnan(yb)
        valid_d = ~np.isnan(delta)

        rms = float(np.sqrt(np.nanmean(delta[valid_d] ** 2))) if np.any(valid_d) else float("nan")
        max_abs = float(np.nanmax(np.abs(delta[valid_d]))) if np.any(valid_d) else float("nan")

        txt = []
        txt.append(f"Channel: {channel_name}")
        txt.append(f"Run A samples: {len(xa)} (valid={int(valid_a.sum())})")
        txt.append(f"Run B samples: {len(xb)} (valid={int(valid_b.sum())})")
        txt.append(f"Delta valid samples: {int(valid_d.sum())}")
        txt.append("")
        txt.append(f"RMS(A-B): {rms:.6g}")
        txt.append(f"Max |A-B|: {max_abs:.6g}")

        if np.any(valid_a):
            i = int(np.nanargmax(ya))
            txt.append(f"Run A peak: {ya[i]:.6g} at t={xa[i]:.3f}s")
        if np.any(valid_b):
            i = int(np.nanargmax(yb))
            txt.append(f"Run B peak: {yb[i]:.6g} at t={xb[i]:.3f}s")

        self.metrics_box.setPlainText("\n".join(txt))

    def _export_png(self) -> None:
        channel_name = self._selected_channel() or "channel"
        out = Path.cwd() / f"compare_{channel_name}.png"

        exporter = pg.exporters.ImageExporter(self.plot_overlay.plotItem)
        exporter.parameters()["width"] = 1800
        exporter.export(str(out))

        QtWidgets.QMessageBox.information(self, "Export complete", f"Saved: {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive viewer to compare two H5 run files")
    parser.add_argument("run_a", help="Path to first run .h5 file")
    parser.add_argument("run_b", help="Path to second run .h5 file")
    args = parser.parse_args()

    if QtWidgets is None or pg is None:
        print("This tool requires PySide6 and pyqtgraph.")
        print("Install with: pip install pyside6 pyqtgraph")
        return 1

    run_a = Path(args.run_a)
    run_b = Path(args.run_b)
    if not run_a.exists() or not run_b.exists():
        print("One or both input files do not exist.")
        return 1

    run_data_a = load_run(run_a)
    run_data_b = load_run(run_b)

    app = QtWidgets.QApplication([])
    window = CompareWindow(run_data_a, run_data_b)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
