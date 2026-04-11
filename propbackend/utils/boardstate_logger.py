from propbackend.hardware.hardware_handler import HardwareHandler
from propbackend.hardware.board import Board
import os
from datetime import datetime
import csv
import time
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

import h5py

from propbackend.utils import config_reader


@dataclass(frozen=True)
class ChannelSpec:
    board_name: str
    hw_type: str
    item_name: str
    state_name: str
    is_demand: bool
    channel_name: str
    unit: str
    signal_type: str


class BoardStateLogger:
    def __init__(self, name, hardware_handler: HardwareHandler, log_dir="/mnt/proppi_data/logs", auto_generate_report: bool = False):
        self.name = name
        self.base_log_dir = log_dir
        self.hardware_handler = hardware_handler
        self.auto_generate_report = auto_generate_report

        self.log_date = datetime.now().strftime('%Y-%m-%d')
        logger_folder = ''.join(ch.lower() if ch.isalnum() else '_' for ch in self.name).strip('_') or 'logger'
        self.log_dir = os.path.join(self.base_log_dir, self.log_date, logger_folder)

        os.makedirs(self.log_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.base_name = f"test_{timestamp}_{self.name}"

        self.file_name = f"{self.base_name}.csv"
        self.csv_path = os.path.join(self.log_dir, self.file_name)
        self.h5_file_name = f"{self.base_name}.h5"
        self.h5_path = os.path.join(self.log_dir, self.h5_file_name)

        self.current_csv = open(self.csv_path, 'w', newline='')
        self.csv_writer = csv.writer(self.current_csv)
        self.h5_file = h5py.File(self.h5_path, 'w')
    
        comment_test = f"#Test started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        for board in self.hardware_handler.boards:
            for hw_type in config_reader.get_hardware_types():
                if hw_type in board.board_config:
                    for item_name, item_data in board.board_config[hw_type].items():
                        if item_data.get("adc"):
                            comment_test += f"ADC_{hw_type}_{item_name}_gain:{item_data['gain']}_offset:{item_data['offset']} "

        comment_test += "\n"
        self.current_csv.write(comment_test)
        self.start_time = time.perf_counter()

        self.state_defaults = config_reader.get_state_defaults()
        self.logging_config = config_reader.get_logging_config()
        self.units_by_state = self.logging_config.get('units_by_state', {})
        self.groups_by_hw_type = self.logging_config.get('groups_by_hw_type', {})
        self.signal_type_by_hw_type = self.logging_config.get('signal_type_by_hw_type', {})
        self.default_signal_type = self.logging_config.get('default_signal_type', 'sensor')
        self.demand_signal_type = self.logging_config.get('demand_signal_type', 'actuator_demand')
        self.unknown_unit = self.logging_config.get('unknown_unit', 'unknown')
        self.schema_version = self.logging_config.get('schema_version', '1.0')

        self.channel_datasets: dict[str, dict[str, h5py.Dataset]] = {}
        self.channel_meta: dict[str, dict[str, str]] = {}
        self.channel_name_counts: dict[str, int] = {}
        self.state_channel_map: dict[tuple[str, str, str, str], str] = {}
        self.demand_channel_map: dict[tuple[str, str, str, str], str] = {}
        self.channel_specs: list[ChannelSpec] = []

        self.h5_channels = self.h5_file.create_group('channels')
        self.h5_config = self.h5_file.create_group('config')
        self.h5_groups = self.h5_file.create_group('groups')
        self.h5_events = self.h5_file.create_group('events')
        self.h5_debug = self.h5_file.create_group('debug')
        self.h5_calibration: h5py.Group | None = None
        self.h5_channel_units: h5py.Group | None = None

        self._init_config_groups()
        self._init_events_datasets()
        self._channel_source_rows: list[tuple[str, str, str, str, str, int | None]] = []

    def _generate_report(self) -> None:
        if not self.auto_generate_report:
            return

        try:
            from propbackend.utils.h5_run_diagnostics import generate_run_report

            reports_dir = os.path.join(self.base_log_dir, self.log_date, 'reports')
            generate_run_report(
                h5_path=self.h5_path,
                output_dir=reports_dir,
                include_plots=True,
            )
        except Exception as exc:
            print(f"BoardStateLogger: report generation failed for {self.h5_file_name}: {exc}")

    def _init_config_groups(self) -> None:
        string_dt = h5py.string_dtype(encoding='utf-8')
        self.h5_config.create_dataset('schema_version', data=self.schema_version, dtype=string_dt)
        self.h5_config.create_dataset('hardware_json', data=json.dumps(config_reader.get_config()), dtype=string_dt)
        self.h5_calibration = self.h5_config.create_group('calibration')
        self.h5_channel_units = self.h5_config.create_group('channel_units')

    def _init_events_datasets(self) -> None:
        string_dt = h5py.string_dtype(encoding='utf-8')
        self.events_time = self.h5_events.create_dataset('time', shape=(0,), maxshape=(None,), dtype='f8')
        self.events_type = self.h5_events.create_dataset('type', shape=(0,), maxshape=(None,), dtype=string_dt)
        self.events_source = self.h5_events.create_dataset('source', shape=(0,), maxshape=(None,), dtype=string_dt)
        self.events_target = self.h5_events.create_dataset('target', shape=(0,), maxshape=(None,), dtype=string_dt)
        self.events_message = self.h5_events.create_dataset('message', shape=(0,), maxshape=(None,), dtype=string_dt)

    def _append_scalar(self, dataset: h5py.Dataset, value):
        next_index = dataset.shape[0]
        dataset.resize((next_index + 1,))
        dataset[next_index] = value

    def _normalize_channel_name(self, raw_name: str) -> str:
        normalized = ''.join(ch.lower() if ch.isalnum() else '_' for ch in raw_name)
        while '__' in normalized:
            normalized = normalized.replace('__', '_')
        normalized = normalized.strip('_')
        if normalized == '':
            normalized = 'unnamed_channel'

        if normalized not in self.channel_name_counts:
            self.channel_name_counts[normalized] = 0
            return normalized

        self.channel_name_counts[normalized] += 1
        return f"{normalized}_{self.channel_name_counts[normalized]}"

    def _get_or_create_state_channel_name(self, board_name: str, hw_type: str, item_name: str, state_name: str) -> str:
        key = (board_name, hw_type, item_name, state_name)
        if key in self.state_channel_map:
            return self.state_channel_map[key]

        channel_name = self._normalize_channel_name(f"{hw_type}_{item_name}_{state_name}")
        self.state_channel_map[key] = channel_name
        return channel_name

    def _get_or_create_demand_channel_name(self, board_name: str, hw_type: str, item_name: str, state_name: str) -> str:
        key = (board_name, hw_type, item_name, state_name)
        if key in self.demand_channel_map:
            return self.demand_channel_map[key]

        channel_name = self._normalize_channel_name(f"{hw_type}_{item_name}_{state_name}_demand")
        self.demand_channel_map[key] = channel_name
        return channel_name

    def _classify_group(self, hw_type: str) -> str:
        return self.groups_by_hw_type.get(hw_type, 'misc')

    def _signal_type_for(self, hw_type: str, is_demand: bool) -> str:
        if is_demand:
            return self.demand_signal_type
        return self.signal_type_by_hw_type.get(hw_type, self.default_signal_type)

    def _create_channel(self, channel_name: str, unit: str, signal_type: str, hw_type: str) -> None:
        if channel_name in self.channel_datasets:
            return

        channel_group = self.h5_channels.create_group(channel_name)
        channel_group.attrs['unit'] = unit
        channel_group.attrs['signal_type'] = signal_type

        time_ds = channel_group.create_dataset('time', shape=(0,), maxshape=(None,), dtype='f8')
        raw_ds = channel_group.create_dataset('raw', shape=(0,), maxshape=(None,), dtype='f8')
        data_ds = channel_group.create_dataset('data', shape=(0,), maxshape=(None,), dtype='f8')

        self.channel_datasets[channel_name] = {
            'time': time_ds,
            'raw': raw_ds,
            'data': data_ds,
        }
        self.channel_meta[channel_name] = {
            'unit': unit,
            'signal_type': signal_type,
            'hw_type': hw_type,
        }

        if self.h5_channel_units is not None:
            self.h5_channel_units.attrs[channel_name] = unit

    def _get_unit(self, item_data: dict, state_name: str) -> str:
        if isinstance(item_data, dict) and 'unit' in item_data and item_data['unit'] is not None:
            return str(item_data['unit'])
        return str(self.units_by_state.get(state_name, self.unknown_unit))

    def _to_numeric_or_nan(self, value):
        if value is None:
            return float('nan')
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            if isinstance(value, float) and math.isnan(value):
                return float('nan')
            return float(value)
        return float('nan')

    def _get_raw_value(self, item_data: dict, data_value):
        if not isinstance(data_value, (int, float)):
            return data_value

        if not isinstance(item_data, dict):
            return data_value

        gain = item_data.get('gain')
        offset = item_data.get('offset')

        if isinstance(gain, (int, float)) and isinstance(offset, (int, float)) and gain != 0:
            return (data_value - offset) / gain
        return data_value

    def _register_channel_metadata(self, board: Board, hw_type: str, item_name: str, state_name: str, channel_name: str, item_data: dict) -> None:
        if not isinstance(item_data, dict):
            return

        source_channel = item_data.get('channel')
        if not isinstance(source_channel, int):
            source_channel = None

        self._channel_source_rows.append((channel_name, board.name, hw_type, item_name, state_name, source_channel))

        if item_data.get('adc'):
            if self.h5_calibration is not None:
                calibration_group = self.h5_calibration.require_group(channel_name)
                if 'gain' in item_data:
                    calibration_group.attrs['gain'] = item_data['gain']
                if 'offset' in item_data:
                    calibration_group.attrs['offset'] = item_data['offset']

    def _append_channel_sample(self, channel_name: str, t: float, raw_value, data_value) -> None:
        datasets = self.channel_datasets[channel_name]
        self._append_scalar(datasets['time'], t)
        self._append_scalar(datasets['raw'], self._to_numeric_or_nan(raw_value))
        self._append_scalar(datasets['data'], self._to_numeric_or_nan(data_value))

    def _iter_tree_entries(self, board: Board, tree_name: str) -> Iterable[tuple[str, str, dict[str, Any], str]]:
        tree = getattr(board, tree_name, {})
        for hw_type, items in tree.items():
            if not isinstance(items, dict):
                continue
            if hw_type not in self.state_defaults:
                continue
            for item_name, item_data in items.items():
                for state_name in self.state_defaults[hw_type].keys():
                    yield hw_type, item_name, item_data, state_name

    def _build_channel_name(self, board: Board, hw_type: str, item_name: str, state_name: str, is_demand: bool) -> str:
        if is_demand:
            return self._get_or_create_demand_channel_name(board.name, hw_type, item_name, state_name)
        return self._get_or_create_state_channel_name(board.name, hw_type, item_name, state_name)

    def _register_entry_channel(self, board: Board, hw_type: str, item_name: str, item_data: dict, state_name: str, is_demand: bool) -> str:
        channel_name = self._build_channel_name(board, hw_type, item_name, state_name, is_demand)
        unit = self._get_unit(item_data, state_name)
        signal_type = self._signal_type_for(hw_type, is_demand)
        self._create_channel(channel_name, unit, signal_type, hw_type)
        self._register_channel_metadata(board, hw_type, item_name, state_name, channel_name, item_data)
        return channel_name

    def _append_entry_sample(self, channel_name: str, t: float, item_data: dict, value, is_demand: bool) -> None:
        if channel_name not in self.channel_datasets:
            return
        if is_demand:
            self._append_channel_sample(channel_name, t, value, value)
        else:
            raw_value = self._get_raw_value(item_data, value)
            self._append_channel_sample(channel_name, t, raw_value, value)

    def _build_channel_specs(self, boards: list[Board]) -> list[ChannelSpec]:
        specs: list[ChannelSpec] = []
        for board in boards:
            for hw_type, item_name, item_data, state_name in self._iter_tree_entries(board, 'state'):
                channel_name = self._register_entry_channel(board, hw_type, item_name, item_data, state_name, is_demand=False)
                specs.append(
                    ChannelSpec(
                        board_name=board.name,
                        hw_type=hw_type,
                        item_name=item_name,
                        state_name=state_name,
                        is_demand=False,
                        channel_name=channel_name,
                        unit=self._get_unit(item_data, state_name),
                        signal_type=self._signal_type_for(hw_type, False),
                    )
                )

            for hw_type, item_name, item_data, state_name in self._iter_tree_entries(board, 'desired_state'):
                channel_name = self._register_entry_channel(board, hw_type, item_name, item_data, state_name, is_demand=True)
                specs.append(
                    ChannelSpec(
                        board_name=board.name,
                        hw_type=hw_type,
                        item_name=item_name,
                        state_name=state_name,
                        is_demand=True,
                        channel_name=channel_name,
                        unit=self._get_unit(item_data, state_name),
                        signal_type=self._signal_type_for(hw_type, True),
                    )
                )
        return specs

    def _get_value_from_spec(self, board: Board, spec: ChannelSpec):
        tree_name = 'desired_state' if spec.is_demand else 'state'
        tree = getattr(board, tree_name, {})
        hw_bucket = tree.get(spec.hw_type)
        if not isinstance(hw_bucket, dict):
            return None, {}

        item_data = hw_bucket.get(spec.item_name)
        if not isinstance(item_data, dict):
            return None, {}

        return item_data.get(spec.state_name), item_data

    def _write_debug_source_map(self) -> None:
        string_dt = h5py.string_dtype(encoding='utf-8')
        source_map = self.h5_debug.require_group('channel_source_map')

        for dataset_name in ('channel_name', 'board_name', 'hw_type', 'item_name', 'state_name', 'channel_number'):
            if dataset_name in source_map:
                del source_map[dataset_name]

        channel_names = [row[0] for row in self._channel_source_rows]
        board_names = [row[1] for row in self._channel_source_rows]
        hw_types = [row[2] for row in self._channel_source_rows]
        item_names = [row[3] for row in self._channel_source_rows]
        state_names = [row[4] for row in self._channel_source_rows]
        channel_numbers = [(-1 if row[5] is None else row[5]) for row in self._channel_source_rows]

        source_map.create_dataset('channel_name', data=channel_names, dtype=string_dt)
        source_map.create_dataset('board_name', data=board_names, dtype=string_dt)
        source_map.create_dataset('hw_type', data=hw_types, dtype=string_dt)
        source_map.create_dataset('item_name', data=item_names, dtype=string_dt)
        source_map.create_dataset('state_name', data=state_names, dtype=string_dt)
        source_map.create_dataset('channel_number', data=channel_numbers, dtype='i4')

    def _write_groups_index(self) -> None:
        group_channels: dict[str, list[str]] = {}
        for channel_name in self.channel_meta.keys():
            hw_type = self.channel_meta[channel_name].get('hw_type', 'misc')
            bucket = self._classify_group(hw_type)
            group_channels.setdefault(bucket, []).append(f"/channels/{channel_name}")

        string_dt = h5py.string_dtype(encoding='utf-8')
        for group_name, channels in group_channels.items():
            group = self.h5_groups.require_group(group_name)
            if 'channels' in group:
                del group['channels']
            group.create_dataset('channels', data=channels, dtype=string_dt)
    
    def write_headers(self, boards: list[Board]):
        self.channel_specs = self._build_channel_specs(boards)
        headers: list[str] = ["timestamp", *[spec.channel_name for spec in self.channel_specs]]
        
        if self.csv_writer is not None:
            self.csv_writer.writerow(headers)
        self._write_groups_index()

    def write_data(self, boards: list[Board]):
        if not self.channel_specs:
            self.write_headers(boards)

        t = time.perf_counter() - self.start_time
        data: list[object] = [t]
        boards_by_name = {board.name: board for board in boards}

        for spec in self.channel_specs:
            board = boards_by_name.get(spec.board_name)
            if board is None:
                value = None
                item_data: dict[str, Any] = {}
            else:
                value, item_data = self._get_value_from_spec(board, spec)

            data.append(value)
            self._append_entry_sample(spec.channel_name, t, item_data, value, spec.is_demand)

        if self.current_csv and self.csv_writer is not None:
            self.csv_writer.writerow(data)
            self.current_csv.flush()

        if self.h5_file:
            self.h5_file.flush()

    def log_event(self, event_type: str, source: str, target: str, message: str) -> None:
        if not self.h5_file:
            return
        t = time.perf_counter() - self.start_time
        self._append_scalar(self.events_time, t)
        self._append_scalar(self.events_type, event_type)
        self._append_scalar(self.events_source, source)
        self._append_scalar(self.events_target, target)
        self._append_scalar(self.events_message, message)

    def close(self):
        if self.current_csv:
            self.current_csv.close()
            print(f"BoardStateLogger: Closed CSV file {self.file_name}")

        if self.h5_file:
            self._write_debug_source_map()
            self.h5_file.flush()
            self.h5_file.close()

        self.current_csv = None
        self.csv_writer = None
        self.h5_file = None

        self._generate_report()

