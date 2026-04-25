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
    is_adc: bool


class BoardStateLogger:
    ACTUATOR_HW_TYPES = {"servos", "solenoids", "pyros", "tvcs"}

    def __init__(self, name, hardware_handler: HardwareHandler, log_dir="/mnt/proppi_data/logs", notes: str | None = None):
        self.name = name
        self.base_log_dir = log_dir
        self.hardware_handler = hardware_handler
        self.notes = notes or ""

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
                        if self._is_adc_item(hw_type) and isinstance(item_data, dict):
                            gain = item_data.get('gain')
                            offset = item_data.get('offset')
                            if gain is not None or offset is not None:
                                comment_test += f"ADC_{hw_type}_{item_name}_gain:{gain}_offset:{offset} "

        comment_test += "\n"
        self.current_csv.write(comment_test)
        self.start_time = time.perf_counter()

        self.state_defaults = config_reader.get_state_defaults()
        self.logging_config = config_reader.get_logging_config()
        self.schema_version = self.logging_config.get('schema_version', '1.2')
        self.status_state_names = {'armed', 'powered', 'state'}

        self.channel_datasets: dict[str, dict[str, h5py.Dataset]] = {}
        self.channel_meta: dict[str, dict[str, str]] = {}
        self.channel_name_counts: dict[str, int] = {}
        self.status_datasets: dict[str, dict[str, h5py.Dataset]] = {}
        self.status_specs: list[ChannelSpec] = []
        self.state_channel_map: dict[tuple[str, str, str, str], str] = {}
        self.demand_channel_map: dict[tuple[str, str, str, str], str] = {}
        self.state_status_map: dict[tuple[str, str, str, str], str] = {}
        self.demand_status_map: dict[tuple[str, str, str, str], str] = {}
        self.channel_specs: list[ChannelSpec] = []

        self.h5_channels = self.h5_file.create_group('channels')
        self.h5_status = self.h5_file.create_group('status')
        self.h5_config = self.h5_file.create_group('config')
        self.h5_calibration: h5py.Group | None = None
        self.h5_channel_units: h5py.Group | None = None

        self._init_config_groups()

    def _init_config_groups(self) -> None:
        string_dt = h5py.string_dtype(encoding='utf-8')
        self.h5_config.create_dataset('notes', data=self.notes, dtype=string_dt)
        self.h5_config.create_dataset('schema_version', data=self.schema_version, dtype=string_dt)
        self.h5_config.create_dataset('hardware_json', data=json.dumps(config_reader.get_config()), dtype=string_dt)
        self.h5_calibration = self.h5_config.create_group('calibration')
        self.h5_channel_units = self.h5_config.create_group('channel_units')

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

    def _signal_type_for(self, hw_type: str, is_demand: bool) -> str:
        if is_demand:
            return 'actuator_demand'
        if hw_type in self.ACTUATOR_HW_TYPES:
            return 'actuator_actual'
        return 'sensor'

    def _is_status_state(self, state_name: str) -> bool:
        return state_name in self.status_state_names

    def _plot_group_for(self, hw_type: str, unit: str) -> str:
        if isinstance(unit, str) and unit.strip():
            return unit.strip().lower()
        return hw_type or 'misc'

    def _create_channel(self, channel_name: str, unit: str, signal_type: str, hw_type: str, is_adc: bool, plot_group: str) -> None:
        if channel_name in self.channel_datasets:
            return

        channel_group = self.h5_channels.create_group(channel_name)
        channel_group.attrs['unit'] = unit
        channel_group.attrs['signal_type'] = signal_type
        channel_group.attrs['plot_group'] = plot_group

        time_ds = channel_group.create_dataset('time', shape=(0,), maxshape=(None,), dtype='f8')
        data_ds = channel_group.create_dataset('data', shape=(0,), maxshape=(None,), dtype='f8')

        datasets: dict[str, h5py.Dataset] = {
            'time': time_ds,
            'data': data_ds,
        }
        if is_adc:
            datasets['raw'] = channel_group.create_dataset('raw', shape=(0,), maxshape=(None,), dtype='f8')

        self.channel_datasets[channel_name] = datasets
        self.channel_meta[channel_name] = {
            'unit': unit,
            'signal_type': signal_type,
            'hw_type': hw_type,
            'is_adc': '1' if is_adc else '0',
            'plot_group': plot_group,
        }

        if self.h5_channel_units is not None:
            self.h5_channel_units.attrs[channel_name] = unit

    def _get_unit(self, board: Board, hw_type: str, item_name: str, item_data: dict) -> str:
        if isinstance(item_data, dict) and 'unit' in item_data and item_data['unit'] is not None:
            return str(item_data['unit'])

        board_bucket = board.board_config.get(hw_type)
        if isinstance(board_bucket, dict):
            board_item = board_bucket.get(item_name)
            if isinstance(board_item, dict) and board_item.get('unit') is not None:
                return str(board_item['unit'])

        return ''

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

    def _get_calibrated_value(self, item_data: dict, raw_value):
        if not isinstance(raw_value, (int, float)):
            return raw_value

        if not isinstance(item_data, dict):
            return raw_value

        gain = item_data.get('gain')
        offset = item_data.get('offset')

        if isinstance(gain, (int, float)) and isinstance(offset, (int, float)):
            return (raw_value - offset) * gain
        return raw_value

    def _is_adc_item(self, hw_type: str) -> bool:
        return hw_type == 'adc'

    def _register_channel_metadata(self, board: Board, hw_type: str, item_name: str, state_name: str, channel_name: str, item_data: dict) -> None:
        if not isinstance(item_data, dict):
            return

        source_channel = item_data.get('channel')
        if not isinstance(source_channel, int):
            source_channel = None

        if self._is_adc_item(hw_type):
            if self.h5_calibration is not None:
                calibration_group = self.h5_calibration.require_group(channel_name)
                if 'gain' in item_data:
                    calibration_group.attrs['gain'] = item_data['gain']
                if 'offset' in item_data:
                    calibration_group.attrs['offset'] = item_data['offset']

    def _append_channel_sample(self, channel_name: str, t: float, raw_value, data_value) -> None:
        datasets = self.channel_datasets[channel_name]
        self._append_scalar(datasets['time'], t)
        if 'raw' in datasets:
            self._append_scalar(datasets['raw'], self._to_numeric_or_nan(raw_value))
        self._append_scalar(datasets['data'], self._to_numeric_or_nan(data_value))

    def _status_name(self, board_name: str, hw_type: str, item_name: str, state_name: str, is_demand: bool) -> str:
        suffix = '_demand' if is_demand else ''
        return self._normalize_channel_name(f"{board_name}_{hw_type}_{item_name}_{state_name}{suffix}")

    def _get_or_create_status_name(self, board_name: str, hw_type: str, item_name: str, state_name: str, is_demand: bool) -> str:
        key = (board_name, hw_type, item_name, state_name)
        status_map = self.demand_status_map if is_demand else self.state_status_map
        if key in status_map:
            return status_map[key]
        status_name = self._status_name(board_name, hw_type, item_name, state_name, is_demand)
        status_map[key] = status_name
        return status_name

    def _create_status_dataset(self, status_name: str) -> None:
        if status_name in self.status_datasets:
            return
        status_group = self.h5_status.create_group(status_name)
        time_ds = status_group.create_dataset('time', shape=(0,), maxshape=(None,), dtype='f8')
        value_ds = status_group.create_dataset('value', shape=(0,), maxshape=(None,), dtype='f8')
        self.status_datasets[status_name] = {
            'time': time_ds,
            'value': value_ds,
        }

    def _append_status_sample(self, status_name: str, t: float, value) -> None:
        datasets = self.status_datasets.get(status_name)
        if datasets is None:
            return
        self._append_scalar(datasets['time'], t)
        self._append_scalar(datasets['value'], self._to_numeric_or_nan(value))

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
        unit = self._get_unit(board, hw_type, item_name, item_data)
        signal_type = self._signal_type_for(hw_type, is_demand)
        plot_group = self._plot_group_for(hw_type, unit)
        self._create_channel(channel_name, unit, signal_type, hw_type, self._is_adc_item(hw_type), plot_group)
        self._register_channel_metadata(board, hw_type, item_name, state_name, channel_name, item_data)
        return channel_name

    def _register_status_spec(self, board: Board, hw_type: str, item_name: str, item_data: dict, state_name: str, is_demand: bool) -> ChannelSpec:
        status_name = self._get_or_create_status_name(board.name, hw_type, item_name, state_name, is_demand)
        self._create_status_dataset(status_name)
        return ChannelSpec(
            board_name=board.name,
            hw_type=hw_type,
            item_name=item_name,
            state_name=state_name,
            is_demand=is_demand,
            channel_name=status_name,
            unit=self._get_unit(board, hw_type, item_name, item_data),
            signal_type='status',
            is_adc=False,
        )

    def _append_entry_sample(self, channel_name: str, t: float, item_data: dict, value, is_demand: bool, is_adc: bool) -> None:
        if channel_name not in self.channel_datasets:
            return
        if is_demand or not is_adc:
            self._append_channel_sample(channel_name, t, float('nan'), value)
        else:
            raw_value = value
            calibrated_value = self._get_calibrated_value(item_data, raw_value)
            self._append_channel_sample(channel_name, t, raw_value, calibrated_value)

    def _build_channel_specs(self, boards: list[Board]) -> list[ChannelSpec]:
        specs: list[ChannelSpec] = []
        self.status_specs = []
        for board in boards:
            for hw_type, item_name, item_data, state_name in self._iter_tree_entries(board, 'state'):
                if self._is_status_state(state_name):
                    self.status_specs.append(
                        self._register_status_spec(board, hw_type, item_name, item_data, state_name, is_demand=False)
                    )
                    continue
                channel_name = self._register_entry_channel(board, hw_type, item_name, item_data, state_name, is_demand=False)
                specs.append(
                    ChannelSpec(
                        board_name=board.name,
                        hw_type=hw_type,
                        item_name=item_name,
                        state_name=state_name,
                        is_demand=False,
                        channel_name=channel_name,
                        unit=self._get_unit(board, hw_type, item_name, item_data),
                        signal_type=self._signal_type_for(hw_type, False),
                        is_adc=self._is_adc_item(hw_type),
                    )
                )

            for hw_type, item_name, item_data, state_name in self._iter_tree_entries(board, 'desired_state'):
                if self._is_status_state(state_name):
                    self.status_specs.append(
                        self._register_status_spec(board, hw_type, item_name, item_data, state_name, is_demand=True)
                    )
                    continue
                channel_name = self._register_entry_channel(board, hw_type, item_name, item_data, state_name, is_demand=True)
                specs.append(
                    ChannelSpec(
                        board_name=board.name,
                        hw_type=hw_type,
                        item_name=item_name,
                        state_name=state_name,
                        is_demand=True,
                        channel_name=channel_name,
                        unit=self._get_unit(board, hw_type, item_name, item_data),
                        signal_type=self._signal_type_for(hw_type, True),
                        is_adc=False,
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

    def write_headers(self, boards: list[Board]):
        self.channel_specs = self._build_channel_specs(boards)
        headers: list[str] = ["timestamp", *[spec.channel_name for spec in self.channel_specs]]
        
        if self.csv_writer is not None:
            self.csv_writer.writerow(headers)

    def write_data(self, boards: list[Board], timestamp_override: float | None = None):
        if not self.channel_specs:
            self.write_headers(boards)

        t = timestamp_override if timestamp_override is not None else (time.perf_counter() - self.start_time)
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
            self._append_entry_sample(spec.channel_name, t, item_data, value, spec.is_demand, spec.is_adc)

        for spec in self.status_specs:
            board = boards_by_name.get(spec.board_name)
            if board is None:
                status_value = None
            else:
                status_value, _ = self._get_value_from_spec(board, spec)
            self._append_status_sample(spec.channel_name, t, status_value)

        if self.current_csv and self.csv_writer is not None:
            self.csv_writer.writerow(data)
            self.current_csv.flush()

        if self.h5_file:
            self.h5_file.flush()

    def log_event(self, event_type: str, source: str, target: str, message: str) -> None:
        # Events are intentionally not persisted in H5 for current schema.
        return

    def close(self):
        if self.current_csv:
            self.current_csv.close()
            print(f"BoardStateLogger: Closed CSV file {self.file_name}")

        if self.h5_file:
            self.h5_file.flush()
            self.h5_file.close()

        self.current_csv = None
        self.csv_writer = None
        self.h5_file = None

