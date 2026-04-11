import argparse
from pathlib import Path
from typing import Dict, List, Tuple

import h5py
import numpy as np


try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover
    plt = None


def read_text_array(dataset) -> List[str]:
    values = dataset[()]
    if isinstance(values, (bytes, str)):
        return [values.decode("utf-8") if isinstance(values, bytes) else values]
    result = []
    for value in values:
        if isinstance(value, bytes):
            result.append(value.decode("utf-8"))
        else:
            result.append(str(value))
    return result


def load_channels(h5: h5py.File) -> Dict[str, Dict[str, np.ndarray]]:
    channels = {}
    if "channels" not in h5:
        return channels

    for channel_name in h5["channels"].keys():
        group = h5["channels"][channel_name]
        if not isinstance(group, h5py.Group):
            continue
        if not all(key in group for key in ("time", "raw", "data")):
            continue

        channels[channel_name] = {
            "time": np.asarray(group["time"][:], dtype=float),
            "raw": np.asarray(group["raw"][:], dtype=float),
            "data": np.asarray(group["data"][:], dtype=float),
            "unit": str(group.attrs.get("unit", "")),
            "signal_type": str(group.attrs.get("signal_type", "")),
        }
    return channels


def load_events(h5: h5py.File) -> Dict[str, List]:
    events = {"time": [], "type": [], "source": [], "target": [], "message": []}
    if "events" not in h5:
        return events

    event_group = h5["events"]
    required = ("time", "type", "source", "target", "message")
    if not all(name in event_group for name in required):
        return events

    events["time"] = list(np.asarray(event_group["time"][:], dtype=float))
    for key in ("type", "source", "target", "message"):
        events[key] = read_text_array(event_group[key])
    return events


def channel_names_from_group(h5: h5py.File, group_path: str) -> List[str]:
    if group_path not in h5:
        return []
    group = h5[group_path]
    if not isinstance(group, h5py.Group) or "channels" not in group:
        return []

    raw_paths = read_text_array(group["channels"])
    return [path.split("/")[-1] for path in raw_paths]


def summarize_channels(channels: Dict[str, Dict[str, np.ndarray]]) -> List[str]:
    lines = []
    lines.append(f"Channels discovered: {len(channels)}")

    mismatched = []
    nan_heavy = []

    for name, payload in channels.items():
        t_len = len(payload["time"])
        r_len = len(payload["raw"])
        d_len = len(payload["data"])
        if not (t_len == r_len == d_len):
            mismatched.append((name, t_len, r_len, d_len))

        if d_len > 0:
            nan_ratio = float(np.isnan(payload["data"]).sum()) / float(d_len)
            if nan_ratio > 0.5:
                nan_heavy.append((name, nan_ratio))

    lines.append(f"Channels with length mismatch: {len(mismatched)}")
    for name, t_len, r_len, d_len in mismatched[:10]:
        lines.append(f"  - {name}: time={t_len}, raw={r_len}, data={d_len}")

    lines.append(f"Channels with >50% NaN in data: {len(nan_heavy)}")
    for name, ratio in sorted(nan_heavy, key=lambda x: x[1], reverse=True)[:10]:
        lines.append(f"  - {name}: nan_ratio={ratio:.2f}")

    return lines


def build_actuator_pairs(channels: Dict[str, Dict[str, np.ndarray]]) -> List[Tuple[str, str]]:
    names = set(channels.keys())
    pairs = []
    for name in sorted(names):
        if not name.endswith("_demand"):
            continue
        base = name[:-7]
        candidates = [f"{base}_actual", base]
        for candidate in candidates:
            if candidate in names:
                pairs.append((name, candidate))
                break
    return pairs


def add_event_lines(ax, events: Dict[str, List], max_lines: int = 50) -> None:
    if not events["time"]:
        return
    for t in events["time"][:max_lines]:
        ax.axvline(t, color="gray", alpha=0.15, linewidth=0.8)


def plot_channel_set(ax, channels: Dict[str, Dict[str, np.ndarray]], names: List[str], title: str, events: Dict[str, List]) -> None:
    for name in names:
        if name not in channels:
            continue
        x = channels[name]["time"]
        y = channels[name]["data"]
        if len(x) == 0:
            continue
        ax.plot(x, y, label=name, linewidth=1.3)
    add_event_lines(ax, events)
    ax.set_title(title)
    ax.set_xlabel("time_s")
    ax.grid(alpha=0.25)
    if names:
        ax.legend(fontsize=8, ncols=2)


def make_plots(h5: h5py.File, channels: Dict[str, Dict[str, np.ndarray]], events: Dict[str, List], output_dir: Path) -> List[Path]:
    if plt is None:
        return []

    output_files = []

    pressure_names = channel_names_from_group(h5, "/groups/pressure")
    if not pressure_names:
        pressure_names = [name for name in channels.keys() if name.startswith("pts_") or "pt_" in name]

    actuator_pairs = build_actuator_pairs(channels)

    rotational_names = channel_names_from_group(h5, "/groups/rotational")
    if not rotational_names:
        rotational_names = [name for name in channels.keys() if "rpm" in name or "tacho" in name]

    event_plot_path = output_dir / "01_events_timeline.png"
    fig, ax = plt.subplots(figsize=(12, 3.5))
    if events["time"]:
        event_types = sorted(set(events["type"]))
        event_y = {event_type: idx for idx, event_type in enumerate(event_types)}
        yvals = [event_y[event_type] for event_type in events["type"]]
        ax.scatter(events["time"], yvals, s=22)
        ax.set_yticks(range(len(event_types)))
        ax.set_yticklabels(event_types)
    ax.set_title("Event timeline")
    ax.set_xlabel("time_s")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(event_plot_path, dpi=140)
    plt.close(fig)
    output_files.append(event_plot_path)

    pressure_plot_path = output_dir / "02_pressure_channels.png"
    fig, ax = plt.subplots(figsize=(12, 4.5))
    plot_channel_set(ax, channels, pressure_names[:10], "Pressure channels", events)
    fig.tight_layout()
    fig.savefig(pressure_plot_path, dpi=140)
    plt.close(fig)
    output_files.append(pressure_plot_path)

    actuator_plot_path = output_dir / "03_actuator_demand_vs_actual.png"
    fig, ax = plt.subplots(figsize=(12, 5.0))
    for demand_name, actual_name in actuator_pairs[:12]:
        d = channels[demand_name]
        a = channels[actual_name]
        if len(d["time"]) > 0:
            ax.plot(d["time"], d["data"], linestyle="--", linewidth=1.2, label=demand_name)
        if len(a["time"]) > 0:
            ax.plot(a["time"], a["data"], linewidth=1.2, label=actual_name)
    add_event_lines(ax, events)
    ax.set_title("Actuator demand vs actual")
    ax.set_xlabel("time_s")
    ax.grid(alpha=0.25)
    if actuator_pairs:
        ax.legend(fontsize=8, ncols=2)
    fig.tight_layout()
    fig.savefig(actuator_plot_path, dpi=140)
    plt.close(fig)
    output_files.append(actuator_plot_path)

    rotational_plot_path = output_dir / "04_rotational_and_misc.png"
    fig, ax = plt.subplots(figsize=(12, 4.5))
    plot_channel_set(ax, channels, rotational_names[:10], "Rotational channels", events)
    fig.tight_layout()
    fig.savefig(rotational_plot_path, dpi=140)
    plt.close(fig)
    output_files.append(rotational_plot_path)

    return output_files


def write_summary(output_dir: Path, summary_lines: List[str], event_count: int, actuator_pairs: List[Tuple[str, str]]) -> Path:
    summary_path = output_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("Run diagnostics summary\n")
        f.write("======================\n\n")
        for line in summary_lines:
            f.write(f"{line}\n")
        f.write(f"\nEvent count: {event_count}\n")
        f.write(f"Actuator demand/actual pairs: {len(actuator_pairs)}\n")
        for demand_name, actual_name in actuator_pairs[:20]:
            f.write(f"  - {demand_name} <-> {actual_name}\n")
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
        events = load_events(h5)

        summary_lines = summarize_channels(channels)
        actuator_pairs = build_actuator_pairs(channels)
        summary_path = write_summary(output_dir_path, summary_lines, len(events["time"]), actuator_pairs)

        if include_plots:
            make_plots(h5, channels, events, output_dir_path)

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
