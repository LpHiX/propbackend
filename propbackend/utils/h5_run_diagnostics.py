import argparse
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

import h5py
import numpy as np


try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover
    plt = None


STATUS_SUFFIXES = ("_armed", "_armed_demand", "_powered", "_powered_demand", "_state", "_state_demand")

MAX_CHANNELS_PER_PLOT = 12


def is_status_channel(name: str) -> bool:
    return name.endswith(STATUS_SUFFIXES)


def load_channels(h5: h5py.File) -> Dict[str, Dict[str, np.ndarray]]:
    channels = {}
    if "channels" not in h5:
        return channels
    channels_root = h5["channels"]
    if not isinstance(channels_root, h5py.Group):
        return channels

    for channel_name in channels_root.keys():
        group = channels_root[channel_name]
        if not isinstance(group, h5py.Group):
            continue
        if not all(key in group for key in ("time", "data")):
            continue
        time_ds = group["time"]
        data_ds = group["data"]
        raw_ds = group["raw"] if "raw" in group else None
        if not isinstance(time_ds, h5py.Dataset):
            continue
        if not isinstance(data_ds, h5py.Dataset):
            continue
        if raw_ds is not None and not isinstance(raw_ds, h5py.Dataset):
            continue

        data_np = np.asarray(data_ds[:], dtype=float)
        if raw_ds is None:
            raw_np = np.full(data_np.shape, np.nan, dtype=float)
        else:
            raw_np = np.asarray(raw_ds[:], dtype=float)

        channels[channel_name] = {
            "time": np.asarray(time_ds[:], dtype=float),
            "raw": raw_np,
            "data": data_np,
            "unit": str(group.attrs.get("unit", "")),
            "signal_type": str(group.attrs.get("signal_type", "")),
            "plot_group": str(group.attrs.get("plot_group", "")),
        }
    return channels


def summarize_channels(channels: Dict[str, Dict[str, np.ndarray]]) -> List[str]:
    lines = []
    lines.append(f"Channels discovered: {len(channels)}")
    lines.append(f"Status-like channels in /channels: {sum(1 for name in channels if is_status_channel(name))}")

    mismatched = []
    nan_heavy = []
    raw_populated_non_sensor = []
    signal_type_counter: Counter[str] = Counter()
    plot_group_counter: Counter[str] = Counter()
    sensor_unit_counter: Counter[str] = Counter()

    for name, payload in channels.items():
        t_len = len(payload["time"])
        r_len = len(payload["raw"])
        d_len = len(payload["data"])
        signal_type = str(payload.get("signal_type", "") or "<missing>")
        plot_group = str(payload.get("plot_group", "") or "<missing>")

        signal_type_counter[signal_type] += 1
        plot_group_counter[plot_group] += 1
        if signal_type == "sensor":
            unit_key = str(payload.get("unit", "") or "<missing>")
            sensor_unit_counter[unit_key] += 1

        if not (t_len == r_len == d_len):
            mismatched.append((name, t_len, r_len, d_len))

        if d_len > 0:
            nan_ratio = float(np.isnan(payload["data"]).sum()) / float(d_len)
            if nan_ratio > 0.5:
                nan_heavy.append((name, nan_ratio))

        if payload.get("signal_type") != "sensor" and d_len > 0:
            raw = payload["raw"]
            if np.isfinite(raw).any():
                raw_populated_non_sensor.append(name)

    lines.append(f"Channels with length mismatch: {len(mismatched)}")
    for name, t_len, r_len, d_len in mismatched[:10]:
        lines.append(f"  - {name}: time={t_len}, raw={r_len}, data={d_len}")

    lines.append(f"Channels with >50% NaN in data: {len(nan_heavy)}")
    for name, ratio in sorted(nan_heavy, key=lambda x: x[1], reverse=True)[:10]:
        lines.append(f"  - {name}: nan_ratio={ratio:.2f}")

    lines.append(f"Non-sensor channels with finite raw values: {len(raw_populated_non_sensor)}")
    for name in raw_populated_non_sensor[:10]:
        lines.append(f"  - {name}")

    lines.append("Signal type counts:")
    for key, count in signal_type_counter.most_common():
        lines.append(f"  - {key}: {count}")

    lines.append("Plot group counts:")
    for key, count in plot_group_counter.most_common():
        lines.append(f"  - {key}: {count}")

    lines.append("Sensor unit counts:")
    for key, count in sensor_unit_counter.most_common():
        lines.append(f"  - {key}: {count}")

    return lines


def build_actuator_pairs(channels: Dict[str, Dict[str, np.ndarray]]) -> List[Tuple[str, str]]:
    names = set(channels.keys())
    pairs = []
    for name in sorted(names):
        if is_status_channel(name):
            continue
        if not name.endswith("_demand"):
            continue
        if channels[name]["signal_type"] != "actuator_demand":
            continue

        base = name[:-7]
        candidates = [f"{base}_actual", base]
        for candidate in candidates:
            if candidate in names and channels[candidate]["signal_type"] == "actuator_actual":
                pairs.append((name, candidate))
                break
    return pairs


def plot_channel_set(ax, channels: Dict[str, Dict[str, np.ndarray]], names: List[str], title: str) -> None:
    plotted = 0
    for name in names:
        if name not in channels:
            continue
        x = channels[name]["time"]
        y = channels[name]["data"]
        n = min(len(x), len(y))
        if n == 0:
            continue
        ax.plot(x[:n], y[:n], label=name, linewidth=1.3)
        plotted += 1
    ax.set_title(title)
    ax.set_xlabel("time_s")
    ax.grid(alpha=0.25)
    if plotted:
        ax.legend(fontsize=8, ncols=2)


def filename_safe_token(text: str) -> str:
    out = []
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    token = "".join(out).strip("_")
    while "__" in token:
        token = token.replace("__", "_")
    return token or "unitless"


def group_sensor_channels_by_unit(channels: Dict[str, Dict[str, np.ndarray]]) -> List[Tuple[str, List[str]]]:
    groups: Dict[str, List[str]] = {}
    for name, payload in channels.items():
        if is_status_channel(name):
            continue
        if payload.get("signal_type") != "sensor":
            continue
        unit = str(payload.get("unit", "") or "unitless")
        groups.setdefault(unit, []).append(name)

    grouped = []
    for unit, names in groups.items():
        grouped.append((unit, sorted(names)))

    grouped.sort(key=lambda x: x[0].lower())
    return grouped


def make_plots(channels: Dict[str, Dict[str, np.ndarray]], output_dir: Path) -> List[Path]:
    if plt is None:
        return []

    output_files = []

    sensor_groups = group_sensor_channels_by_unit(channels)
    actuator_pairs = build_actuator_pairs(channels)
    plot_index = 1

    for unit, names in sensor_groups:
        unit_token = filename_safe_token(unit)
        sensor_plot_path = output_dir / f"{plot_index:02d}_sensor_unit_{unit_token}.png"
        fig, ax = plt.subplots(figsize=(12, 4.5))
        plot_channel_set(ax, channels, names[:MAX_CHANNELS_PER_PLOT], f"Sensor channels (unit: {unit})")
        fig.tight_layout()
        fig.savefig(sensor_plot_path, dpi=140)
        plt.close(fig)
        output_files.append(sensor_plot_path)
        plot_index += 1

    servo_pairs = [(demand, actual) for demand, actual in actuator_pairs if demand.startswith("servos_")]
    solenoid_pairs = [(demand, actual) for demand, actual in actuator_pairs if demand.startswith("solenoids_")]

    if servo_pairs:
        servo_plot_path = output_dir / f"{plot_index:02d}_servos_demand_vs_actual.png"
        fig, ax = plt.subplots(figsize=(12, 5.0))
        for demand_name, actual_name in servo_pairs[:MAX_CHANNELS_PER_PLOT]:
            d = channels[demand_name]
            a = channels[actual_name]
            if len(d["time"]) > 0:
                ax.plot(d["time"], d["data"], linestyle="--", linewidth=1.2, label=demand_name)
            if len(a["time"]) > 0:
                ax.plot(a["time"], a["data"], linewidth=1.2, label=actual_name)
        ax.set_title("Servo demand vs actual")
        ax.set_xlabel("time_s")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, ncols=2)
        fig.tight_layout()
        fig.savefig(servo_plot_path, dpi=140)
        plt.close(fig)
        output_files.append(servo_plot_path)
        plot_index += 1

    if solenoid_pairs:
        solenoid_plot_path = output_dir / f"{plot_index:02d}_solenoids_demand_vs_actual.png"
        fig, ax = plt.subplots(figsize=(12, 5.0))
        for demand_name, actual_name in solenoid_pairs[:MAX_CHANNELS_PER_PLOT]:
            d = channels[demand_name]
            a = channels[actual_name]
            if len(d["time"]) > 0:
                ax.plot(d["time"], d["data"], linestyle="--", linewidth=1.2, label=demand_name)
            if len(a["time"]) > 0:
                ax.plot(a["time"], a["data"], linewidth=1.2, label=actual_name)
        ax.set_title("Solenoid demand vs actual")
        ax.set_xlabel("time_s")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, ncols=2)
        fig.tight_layout()
        fig.savefig(solenoid_plot_path, dpi=140)
        plt.close(fig)
        output_files.append(solenoid_plot_path)

    return output_files


def clear_old_plots(output_dir: Path) -> None:
    for png_path in output_dir.glob("*.png"):
        png_path.unlink(missing_ok=True)


def write_summary(output_dir: Path, summary_lines: List[str], actuator_pairs: List[Tuple[str, str]], plots: List[Path]) -> Path:
    summary_path = output_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("Run diagnostics summary\n")
        f.write("======================\n\n")
        for line in summary_lines:
            f.write(f"{line}\n")
        f.write(f"\nActuator demand/actual pairs: {len(actuator_pairs)}\n")
        for demand_name, actual_name in actuator_pairs[:20]:
            f.write(f"  - {demand_name} <-> {actual_name}\n")
        f.write(f"\nPlots generated: {len(plots)}\n")
        for plot_path in plots:
            f.write(f"  - {plot_path.name}\n")
    return summary_path


def generate_run_report(h5_path: str | Path, output_dir: str | Path | None = None, include_plots: bool = True) -> Path:
    h5_path = Path(h5_path)
    if not h5_path.exists():
        raise FileNotFoundError(f"Run file not found: {h5_path}")

    if output_dir is None:
        output_dir_path = Path(str(h5_path.with_suffix("")) + "_report")
    else:
        output_dir_path = Path(output_dir) / f"{h5_path.stem}_report"

    output_dir_path.mkdir(parents=True, exist_ok=True)

    with h5py.File(h5_path, "r") as h5:
        channels = load_channels(h5)

        summary_lines = summarize_channels(channels)
        actuator_pairs = build_actuator_pairs(channels)
        plots: List[Path] = []

        if include_plots:
            clear_old_plots(output_dir_path)
            plots = make_plots(channels, output_dir_path)

        summary_path = write_summary(output_dir_path, summary_lines, actuator_pairs, plots)

    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate quick diagnostics plots for a run H5 file")
    parser.add_argument("h5_path", help="Path to run .h5 file")
    parser.add_argument("--out", default=None, help="Output directory for report artifacts")
    parser.add_argument("--summary-only", action="store_true", help="Generate only summary.txt")
    args = parser.parse_args()

    try:
        summary_path = generate_run_report(
            h5_path=args.h5_path,
            output_dir=args.out,
            include_plots=not args.summary_only,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Summary written: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
