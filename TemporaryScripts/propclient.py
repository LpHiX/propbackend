import socket
import sys
import json
import signal

from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, 
                             QTextEdit, QVBoxLayout, QHBoxLayout, QWidget,
                             QLabel, QSlider, QGroupBox, QGridLayout, QLineEdit, QTabWidget)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtNetwork import QUdpSocket, QHostAddress
from PySide6.QtCore import QTimer, QByteArray, Slot
from PySide6.QtCore import Slot, QObject, Signal
from PySide6.QtCore import QDateTime
import pyqtgraph as pg
import numpy as np
from collections import deque

PLOT_SECONDS = 30

class UDPManager(QObject):
    dataReceived = Signal(str)
    hardwareJsonStatusChanged = Signal(bool)
    
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.socket = QUdpSocket(self)
        self.socket.readyRead.connect(self.process_datagrams)
        
        self.hardware_json_received = False
        
        QTimer.singleShot(0, self.request_hardware_json)
        
        # Timer to check if hardware JSON was received
        self.hardware_json_timer = QTimer(self)
        self.hardware_json_timer.timeout.connect(self.check_hardware_json)
        self.hardware_json_timer.start(1000)  # Check every 1 second    
    @Slot()
    def check_hardware_json(self):
        if not self.hardware_json_received:
            self.request_hardware_json()
    
    def set_hardware_json_received(self, received=True):
        if received != self.hardware_json_received:
            self.hardware_json_received = received
            self.hardwareJsonStatusChanged.emit(received)
            if received:
                # Stop checking once we've received it
                self.hardware_json_timer.stop()
                self.transmit_timer = QTimer(self)
                self.transmit_timer.timeout.connect(self.request_states)
                self.transmit_timer.start(10) #10ms = 100Hz
    
    @Slot()
    def request_states(self):
        #print("Requesting boards states from backend")
        data = json.dumps({"command":"get boards states", "data":{}})
        self.send(data)
        # ALso request desired states
        data = json.dumps({"command":"get boards desired states", "data":{}})
        self.send(data)

    @Slot()
    def request_hardware_json(self):
        data = json.dumps({"command":"get hardware json", "data":{}})
        self.send(data)

    @Slot()
    def process_datagrams(self):
        while self.socket.hasPendingDatagrams():
            datagram_size = self.socket.pendingDatagramSize()
            data, host, port = self.socket.readDatagram(datagram_size)
            self.dataReceived.emit(bytes(data).decode())

    @Slot()
    def send(self, data):
        self.socket.writeDatagram(QByteArray(data.encode()), QHostAddress(self.host), self.port)

    @Slot()
    def send_actuator_command(self, board_name, actuator_types, actuator_name, command, value):
        message = {
            "command": "update desired state",
            "data":{
                "board_name": board_name,
                "message": {
                    actuator_types: {
                        actuator_name: {
                            command: value
                        }
                    }
                }
            }
        }
        self.send(json.dumps(message))

class ActuatorControllerWidget(QWidget):
    """Base class for all actuator controller widgets"""
    def __init__(self, config, board_name, actuator_name, actuator_type, udpmanager):
        super().__init__()
        self.config = config
        self.board_name = board_name
        self.actuator_name = actuator_name
        self.actuator_type = actuator_type  # "servos", "solenoids", etc.
        self.udpmanager = udpmanager
        
        # Define standard widths
        self.LABEL_WIDTH = 100
        self.BUTTON_WIDTH = 50
        self.INPUT_WIDTH = 40
        
        # Create common layout
        self.layout = QHBoxLayout()
        self.setLayout(self.layout)
        
        # Create common UI elements
        self.name_label = QLabel(f"{self.get_actuator_type_name()}: {self.actuator_name}")
        self.name_label.setFixedWidth(self.LABEL_WIDTH)
        self.layout.addWidget(self.name_label)
        
        # Armed state is common to most actuators
        self.armed_label = QLabel(f"Armed: No data")
        self.armed_label.setFixedWidth(self.LABEL_WIDTH)
        self.layout.addWidget(self.armed_label)
        
        # Common arm/disarm buttons
        self.arm_button = QPushButton("Arm")
        self.arm_button.setFixedWidth(self.BUTTON_WIDTH)
        self.arm_button.clicked.connect(lambda: self.send_command("armed", True))
        
        self.disarm_button = QPushButton("Disarm")
        self.disarm_button.setFixedWidth(self.BUTTON_WIDTH)
        self.disarm_button.clicked.connect(lambda: self.send_command("armed", False))
        
        self.layout.addWidget(self.arm_button)
        self.layout.addWidget(self.disarm_button)
        
        # Add specific UI elements
        self.setup_specific_ui()
        self.layout.addStretch()
    
    def send_command(self, command, value):
        """Send command to the actuator"""
        self.udpmanager.send_actuator_command(
            self.board_name, 
            self.actuator_type, 
            self.actuator_name, 
            command, 
            value
        )
    
    def update_common_states(self, states):
        """Update common states like armed status"""
        try:
            armed = states[self.actuator_type][self.actuator_name]["armed"]
            self.armed_label.setText(f"Armed: {armed}")
        except KeyError:
            self.armed_label.setText("Armed: No data")
    
    def update_states(self, states):
        """Update widget with current states"""
        self.update_common_states(states)
        self.update_specific_states(states)

    def update_desired_states(self, desired_states):
        """Update widget with desired states"""
        self.update_specific_desired_states(desired_states)

    def setup_specific_ui(self):
        """Set up actuator-specific UI elements. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement setup_specific_ui()")
    
    def update_specific_states(self, states):
        """Update actuator-specific states. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement update_specific_states()")
    
    def get_actuator_type_name(self):
        """Return human-readable actuator type name. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement get_actuator_type_name()")

    def update_specific_desired_states(self, desired_states):
        """Update actuator-specific desired states. Override in subclasses. Does nothing if not implemented"""
        pass

class ServoControllerWidget(ActuatorControllerWidget):
    def __init__(self, config, board_name, servo_name, udpmanager):
        super().__init__(config, board_name, servo_name, "servos", udpmanager)
    
    def get_actuator_type_name(self):
        return "Servo"
    
    def setup_specific_ui(self):
        # Servo-specific UI elements
        self.angle_label = QLabel("Angle: No data")
        self.angle_label.setFixedWidth(self.LABEL_WIDTH)
        self.layout.addWidget(self.angle_label)

        self.desired_angle_label = QLabel("Desired Angle: No data")
        self.desired_angle_label.setFixedWidth(self.LABEL_WIDTH)
        self.layout.addWidget(self.desired_angle_label)
        
        self.manual_angle = QLineEdit(self)
        self.manual_angle.setFixedWidth(self.INPUT_WIDTH)
        self.manual_angle.setPlaceholderText("0")
        
        self.manual_angle_button = QPushButton("Set Angle")
        self.manual_angle_button.setFixedWidth(self.BUTTON_WIDTH)
        self.manual_angle_button.clicked.connect(self.set_manual_angle)

        self.zero_angle_button = QPushButton("Set 0")
        self.zero_angle_button.setFixedWidth(self.BUTTON_WIDTH)
        self.zero_angle_button.clicked.connect(self.set_zero_angle)
        
        self.layout.addWidget(self.manual_angle)
        self.layout.addWidget(self.manual_angle_button)
        self.layout.addWidget(self.zero_angle_button)
    
    def update_specific_states(self, states):
        try:
            angle = states[self.actuator_type][self.actuator_name]["angle"]
            self.angle_label.setText(f"Angle: {angle}")
        except KeyError:
            self.angle_label.setText("Angle: No data")
    
    def update_specific_desired_states(self, desired_states):
        try:
            desired_angle = desired_states[self.actuator_type][self.actuator_name]["angle"]
            self.desired_angle_label.setText(f"Desired Angle: {desired_angle}")
        except KeyError:
            self.desired_angle_label.setText("Desired Angle: No data")

    def set_manual_angle(self):
        try:
            angle = int(self.manual_angle.text())
            # if angle < 0 or angle > 180:
                # raise ValueError("Angle must be between 0 and 180")
            self.send_command("angle", angle)
        except ValueError as e:
            print(f"Invalid angle: {e}")

    def set_zero_angle(self):
        self.send_command("angle", 0)
        self.manual_angle.setText("0")

class SolenoidControllerWidget(ActuatorControllerWidget):
    def __init__(self, config, board_name, actuator_name, udpmanager):
        super().__init__(config, board_name, actuator_name, "solenoids", udpmanager)
    
    def get_actuator_type_name(self):
        return "Solenoid"
    
    def setup_specific_ui(self):
        # Solenoid-specific UI elements
        self.powered_label = QLabel("Powered: No data")
        self.powered_label.setFixedWidth(self.LABEL_WIDTH)
        self.layout.addWidget(self.powered_label)
        
        self.poweron_button = QPushButton("Power On")
        self.poweron_button.setFixedWidth(self.BUTTON_WIDTH)
        self.poweron_button.clicked.connect(lambda: self.send_command("powered", True))
        
        self.poweroff_button = QPushButton("Power Off")
        self.poweroff_button.setFixedWidth(self.BUTTON_WIDTH)
        self.poweroff_button.clicked.connect(lambda: self.send_command("powered", False))
        
        self.layout.addWidget(self.poweron_button)
        self.layout.addWidget(self.poweroff_button)
    
    def update_specific_states(self, states):
        #print(f"Updating states for {self.actuator_name}: {states}")
        try:
            powered = states[self.actuator_type][self.actuator_name]["powered"]
            self.powered_label.setText(f"Powered: {powered}")
        except KeyError:
            self.powered_label.setText("Powered: No data")

class PyroControllerWidget(ActuatorControllerWidget):
    def __init__(self, config, board_name, actuator_name, udpmanager):
        super().__init__(config, board_name, actuator_name, "pyros", udpmanager)
    
    def get_actuator_type_name(self):
        return "Pyro"
    
    def setup_specific_ui(self):
        # Pyro-specific UI elements
        self.powered_label = QLabel("Powered: No data")
        self.powered_label.setFixedWidth(self.LABEL_WIDTH)
        self.layout.addWidget(self.powered_label)
        
        self.poweron_button = QPushButton("Power On")
        self.poweron_button.setFixedWidth(self.BUTTON_WIDTH)
        self.poweron_button.clicked.connect(lambda: self.send_command("powered", True))
        
        self.poweroff_button = QPushButton("Power Off")
        self.poweroff_button.setFixedWidth(self.BUTTON_WIDTH)
        self.poweroff_button.clicked.connect(lambda: self.send_command("powered", False))
        
        self.layout.addWidget(self.poweron_button)
        self.layout.addWidget(self.poweroff_button)
    
    def update_specific_states(self, states):
        #print(f"Updating states for {self.actuator_name}: {states}")
        try:
            powered = states[self.actuator_type][self.actuator_name]["powered"]
            self.powered_label.setText(f"Powered: {powered}")
        except KeyError:
            self.powered_label.setText("Powered: No data")
colors = ['y', 'r', 'c', 'b', 'm', 'y', 'k']
pt_number = 0
class SensorControllerWidget(QWidget):
    """"Base class for all sensor controller widgets"""
    def __init__(self, config, sensor_default_data, board_name, sensor_name, sensor_type, udpmanager, testapp):
        global pt_number
        super().__init__()
        self.config = config
        self.sensor_default_data = sensor_default_data
        self.board_name = board_name
        self.sensor_name = sensor_name
        self.sensor_type = sensor_type  # "adc", "tcs", etc.
        self.udpmanager = udpmanager
        self.testapp = testapp
        
        # Define standard widths
        self.LABEL_WIDTH = 100
        
        # Create common layout
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        # Create common UI elements
        self.name_label = QLabel(f"{self.sensor_type}: {self.sensor_name}")
        self.name_label.setFixedWidth(self.LABEL_WIDTH + 20)
        self.layout.addWidget(self.name_label)

        self.values = {}
        self.pressure_curves = []
        self.MAX_HISTORY_SIZE = 10000
        
        for value_name, _ in self.sensor_default_data.items():
            self.values[value_name] = {"value": "No data"}
            self.values[value_name]["label"] = QLabel(f"{value_name}: No data")
            self.values[value_name]["label"].setStyleSheet("font-size: 40px;")
            self.values[value_name]["label"].setFixedWidth(self.LABEL_WIDTH + 100)
            self.values[value_name]["history"] = deque(maxlen=self.MAX_HISTORY_SIZE)
            
            # Preallocate arrays for improved performance
            self.values[value_name]["time_array"] = np.zeros(self.MAX_HISTORY_SIZE, dtype=np.float64)
            self.values[value_name]["value_array"] = np.zeros(self.MAX_HISTORY_SIZE, dtype=np.float64)
            self.values[value_name]["array_size"] = 0

            self.values[value_name]["plot"] = pg.PlotWidget(title=f"{self.sensor_type} {self.sensor_name} {value_name}")
            self.values[value_name]["curve"] = self.values[value_name]["plot"].plot(pen=pg.mkPen(colors[pt_number % len(colors)], width=2))
            if sensor_type == "adc":
                self.values[value_name]["pressurecurve"] = self.testapp.pressureplot.plot(pen=pg.mkPen(colors[pt_number % len(colors)], width=2), name=sensor_name)
                self.pressure_curves.append(self.values[value_name]["pressurecurve"])
            pt_number += 1

            self.vertical_layout = QVBoxLayout()
            self.vertical_layout.addWidget(self.values[value_name]["plot"])
            self.vertical_layout.addWidget(self.values[value_name]["label"])


            self.layout.addLayout(self.vertical_layout)
            
            self.value_timer = QTimer(self)
            self.value_timer.timeout.connect(lambda vn=value_name: self.update_history(vn))
            self.value_timer.start(50)
        self.layout.addStretch()

    def cleanup(self):
        if hasattr(self, "value_timer") and self.value_timer is not None:
            self.value_timer.stop()
        for curve in self.pressure_curves:
            try:
                self.testapp.pressureplot.removeItem(curve)
            except Exception:
                pass
        self.pressure_curves.clear()

    def update_history(self, value_name):
        value_history = self.values[value_name]["history"]
        time_array = self.values[value_name]["time_array"]
        value_array = self.values[value_name]["value_array"]

        if not value_history:
            return
        
        # Clean up old data points (older than 120 seconds)
        current_time = QDateTime.currentDateTime()
        cutoff_time = current_time.addSecs(-120)
        while value_history and value_history[0][0] < cutoff_time:
            value_history.popleft()
        
        if not value_history:   
            # Reset array size if history is empty
            self.values[value_name]["array_size"] = 0
            return
        
        # Copy data to preallocated arrays
        size = len(value_history)
        self.values[value_name]["array_size"] = size
        
        for i, (t, v) in enumerate(value_history):
            time_array[i] = t.toMSecsSinceEpoch()
            value_array[i] = v
        
        # Find index for the start of the window based on time
        start_time = time_array[size-1] - PLOT_SECONDS * 1000
        start_idx = np.searchsorted(time_array[:size], start_time)
        
        # Use accurate slice for plotting
        self.values[value_name]["curve"].setData(
            (time_array[start_idx:size] - time_array[size-1]) / 1000, 
            value_array[start_idx:size]
        )
        if self.sensor_type == "adc":
            self.values[value_name]["pressurecurve"].setData(
                (time_array[:size] - time_array[0]) / 1000, 
                value_array[:size]
            )

    def update_states(self, states):
        for value_name, value_dict in self.values.items():
            value_label = value_dict["label"]
            try:
                raw_value = states[self.sensor_type][self.sensor_name][value_name]
                value = raw_value
                
                
                # Apply calibration if available

                
                # Update the label
                if value is None:
                    value_label.setText("Value: No data")
                else:
                    sensor_cfg = self.config[self.sensor_type][self.sensor_name]
                    if self.sensor_type == "adc" and "gain" in sensor_cfg and "offset" in sensor_cfg:
                        gain = sensor_cfg["gain"]
                        offset = sensor_cfg["offset"]
                        value = (value - offset) * gain
                        unit = sensor_cfg.get("unit", "")
                        if isinstance(raw_value, (int, float)) and float(raw_value).is_integer():
                            raw_display = f"{int(raw_value)}"
                        else:
                            raw_display = f"{raw_value:.0f}"
                        unit_suffix = f" {unit}" if isinstance(unit, str) and unit else ""
                        value_label.setText(
                            f"<span>{value:.1f}</span> "
                            f"<span style='font-size: 24px;'> {raw_display}{unit_suffix}</span>"
                        )
                    else:
                        value_label.setText(f"{value:.2f}")
                
                # Add to the history deque
                if value is None:
                    continue
                value_dict["history"].append((QDateTime.currentDateTime(), float(value)))
                
            except KeyError:
                value_label.setText("Value: No data")

class PropertyTestApp(QMainWindow):
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.hardware_json = None
        self.state_defaults: dict = {}
        self.hardware_types: list[str] = []
        self.actuator_list = []
        self.sensor_list = []
        self.actuator_group_widget = None
        self.sensor_group_widget = None


        self.setWindowTitle("Property Test App")
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)  

        self.main_tab = QWidget()
        self.tab_widget.addTab(self.main_tab, "Main")
        self.main_layout = QHBoxLayout(self.main_tab)
        
        self.pressure_tab = QWidget()
        self.tab_widget.addTab(self.pressure_tab, "Pressure")
        self.pressure_layout = QVBoxLayout(self.pressure_tab)


        #container = QWidget()
        #container.setLayout(self.main_layout)


        self.data_waiting_label = QLabel("Waiting for data...")

        self.last_update_time = None
        self.last_state_update_label = QLabel("Last state update: Never")
        self.last_state_update_label.setFixedWidth(200)
        self.backend_state_timer = QTimer(self)
        self.backend_state_timer.timeout.connect(self.backend_state_coroutine)
        self.backend_state_timer.start(10)
        self.manual_command = QTextEdit(self)
        self.manual_response = QTextEdit(self)
        self.manual_response.setReadOnly(True)
        self.manual_command_button = QPushButton("Send Command")
        self.manual_command_button.clicked.connect(self.send_manual_command)
        self.manual_command_layout = QVBoxLayout()
        self.manual_command_layout.addWidget(self.last_state_update_label)
        self.manual_command_layout.addWidget(self.manual_command)
        self.manual_command_layout.addWidget(self.manual_command_button)
        self.manual_command_layout.addWidget(self.manual_response)

        self.preset_commands_layout = QVBoxLayout()

        self.statemachine_str = "Request timer didn't load"
        self.statemachine_label = QLabel("Machine state: {self.statemachine_str}")
        self.preset_commands_layout.addWidget(self.statemachine_label)

        self.abort_button = QPushButton("Abort")
        self.abort_button.setStyleSheet("font-size: 60px;")
        self.abort_button.setFixedHeight(300)
        self.abort_button.clicked.connect(lambda: self.udp_manager.send(json.dumps({"command":"abort engine", "data":{}})))
        self.preset_commands_layout.addWidget(self.abort_button)

        self.hotfire_button = QPushButton("Hotfire")
        self.hotfire_button.clicked.connect(lambda: self.udp_manager.send(json.dumps({"command":"start hotfire sequence", "data":{}})))
        self.preset_commands_layout.addWidget(self.hotfire_button)

        self.return_from_idle_button = QPushButton("Return to Idle")
        self.return_from_idle_button.clicked.connect(lambda: self.udp_manager.send(json.dumps({"command":"return to idle", "data":{}})))
        self.preset_commands_layout.addWidget(self.return_from_idle_button)

        self.reload_hardware_json = QPushButton("Reload Hardware JSON")
        self.reload_hardware_json.clicked.connect(lambda: self.udp_manager.send(json.dumps({"command":"reload hardware json", "data":{}})))
        self.preset_commands_layout.addWidget(self.reload_hardware_json)

        self.get_new_hardware_json = QPushButton("Get New Hardware JSON (DOESNT WORK)")
        self.get_new_hardware_json.clicked.connect(lambda: self.udp_manager.send(json.dumps({"command":"get hardware json", "data":{}})))
        self.preset_commands_layout.addWidget(self.get_new_hardware_json)



        self.hotfiretime_str = "Request timer didn't load"
        self.hotfiretime_label = QLabel(self.hotfiretime_str)
        self.hotfiretime_label.setStyleSheet("font-size: 60px;")
        self.preset_commands_layout.addWidget(self.hotfiretime_label)

        self.datetime_str = "Request timer didn't load"
        self.datetime_label = QLabel(f"Backend Time: {self.datetime_str}")
        self.preset_commands_layout.addWidget(self.datetime_label)

        self.preset_commands_layout.addStretch()

        self.commands_layout = QHBoxLayout()
        self.commands_layout.addLayout(self.preset_commands_layout)

        self.control_area = QVBoxLayout()
        self.sensor_area = QVBoxLayout()

        self.temp_layout = QHBoxLayout()

        self.actuators_sensors_area = QVBoxLayout()
        self.actuators_sensors_area.addLayout(self.control_area)
        self.actuators_sensors_area.addLayout(self.sensor_area)

        self.temp_layout.addLayout(self.actuators_sensors_area)
        self.temp_layout.addLayout(self.manual_command_layout)

        self.main_layout.addLayout(self.commands_layout)
        self.main_layout.addWidget(self.data_waiting_label)
        self.main_layout.addLayout(self.temp_layout)
        # self.main_layout.addLayout(self.actuators_sensors_area)
        

        


        self.pressureplot = pg.PlotWidget(title="Pressure")
        self.pressureplot.addLegend()
        self.pressure_layout.addWidget(self.pressureplot)


        self.udp_manager = UDPManager(self.host, self.port)
        self.udp_manager.dataReceived.connect(self.handle_data_received)

        self.commands_responses = {
            "get hardware json": self.hardware_json_received,
            "reload hardware json": self.reload_hardware_json_received,
            "get boards states": self.boards_states_received,
            "get boards desired states": self.boards_desired_states_received,
            "get state": self.machinestate_received,
            "get time": self.time_received
        }

    def _clear_dynamic_ui(self):
        for actuator in self.actuator_list:
            actuator.setParent(None)
            actuator.deleteLater()
        self.actuator_list.clear()

        for sensor in self.sensor_list:
            try:
                sensor.cleanup()
            except Exception:
                pass
            sensor.setParent(None)
            sensor.deleteLater()
        self.sensor_list.clear()

        if self.actuator_group_widget is not None:
            self.control_area.removeWidget(self.actuator_group_widget)
            self.actuator_group_widget.setParent(None)
            self.actuator_group_widget.deleteLater()
            self.actuator_group_widget = None

        if self.sensor_group_widget is not None:
            self.sensor_area.removeWidget(self.sensor_group_widget)
            self.sensor_group_widget.setParent(None)
            self.sensor_group_widget.deleteLater()
            self.sensor_group_widget = None

        self.pressureplot.clear()
        if self.pressureplot.plotItem.legend is None:
            self.pressureplot.addLegend()

    def _build_dynamic_ui_from_hardware(self):
        if self.hardware_json is None:
            return
        hardware_json = self.hardware_json

        actuator_group = QGroupBox("Actuators")
        actuator_layout = QVBoxLayout()

        default_actuator_types = {
            "servos": ServoControllerWidget,
            "solenoids": SolenoidControllerWidget,
            "pyros": PyroControllerWidget
        }

        for board_name, board_config in hardware_json["boards"].items():
            if board_config.get("is_actuator", False):
                for actuator_type, actuator_widget_class in default_actuator_types.items():
                    if actuator_type in board_config:
                        for actuator_name, _ in board_config[actuator_type].items():
                            actuator_controller_widget = actuator_widget_class(board_config, board_name, actuator_name, self.udp_manager)
                            actuator_layout.addWidget(actuator_controller_widget)
                            self.actuator_list.append(actuator_controller_widget)
        actuator_layout.addStretch()
        actuator_group.setLayout(actuator_layout)
        self.control_area.addWidget(actuator_group)
        self.actuator_group_widget = actuator_group

        sensor_group = QGroupBox("Sensors")
        sensor_mainlayout = QVBoxLayout()
        for board_name, board_config in hardware_json["boards"].items():
            if not board_config.get("is_actuator", False):
                for sensor_type, sensor_default_data in self.state_defaults.items():
                    if sensor_type in board_config and isinstance(board_config[sensor_type], dict):
                        sensor_layout = QHBoxLayout()
                        sensor_mainlayout.addLayout(sensor_layout)
                        for sensor_name, _ in board_config[sensor_type].items():
                            sensor_controller_widget = SensorControllerWidget(board_config, sensor_default_data, board_name, sensor_name, sensor_type, self.udp_manager, self)
                            sensor_layout.addWidget(sensor_controller_widget)
                            self.sensor_list.append(sensor_controller_widget)
        sensor_mainlayout.addStretch()
        sensor_group.setLayout(sensor_mainlayout)
        self.sensor_area.addWidget(sensor_group)
        self.sensor_group_widget = sensor_group

    def reload_hardware_json_received(self, response):
        try:
            response_json = json.loads(response)
            if "response" not in response_json:
                return
        except json.JSONDecodeError:
            return
        self.udp_manager.request_hardware_json()
    def time_received(self, responsestr):
        try:
            response = json.loads(responsestr)["response"]
        except json.JSONDecodeError:
            print("Time is not valid JSON")
            return
        if "date_time" in response:
            self.datetime_str = response["date_time"]
            self.datetime_label.setText(f"Backend Time: {self.datetime_str}")
        else:
            print("No date_time in response")
        if "hotfire_time" in response:
            self.hotfiretime_str = response["hotfire_time"]
            self.hotfiretime_label.setText(f"{self.hotfiretime_str}")
        else:
            print("No hotfire_time in response")

    def machinestate_received(self, response):
        try:
            self.statemachine_str = json.loads(response)["response"]
            self.statemachine_label.setText(f"Machine state: {self.statemachine_str}")
        except json.JSONDecodeError:
            print("Machine state is not valid JSON")
            return
    def handle_data_received(self, data):
        try:
            data = json.loads(data)
            #print(f"Decoded data: {data}")
            if "command" not in data:
                print("No command in data json, backend is being weird")
                return
            if "response" not in data:
                print("No response in data json, backend is being weird")
                return
            
            command = data["command"]
            response = data["response"]
            #print(type(response))
            if command in self.commands_responses:
                self.commands_responses[command](response)
            else:
                self.manual_response.append(json.dumps(data, indent=4))
        except json.JSONDecodeError:
            print("Failed to decode JSON data")
    def hardware_json_received(self, response):
        global pt_number
        pt_number = 0
        self.udp_manager.set_hardware_json_received(True)
        if self.data_waiting_label is not None:
            self.main_layout.removeWidget(self.data_waiting_label)
            self.data_waiting_label.setParent(None)
            self.data_waiting_label.deleteLater()
            self.data_waiting_label = None
        try :
            response = json.loads(response)
        except json.JSONDecodeError:
            print("Hardware json is not valid JSON")
            return
        
        self.hardware_json = response
        if "boards" not in self.hardware_json:
            print("No boards in hardware json")
            return
        
        if "state_defaults" not in self.hardware_json:
            print("No state defaults in hardware json")
            return
        
        self.state_defaults: dict = self.hardware_json['state_defaults']
        self.hardware_types = list(self.state_defaults.keys())

        self._clear_dynamic_ui()
        self._build_dynamic_ui_from_hardware()

    def boards_desired_states_received(self, response):
        if self.hardware_json is None:
            return
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            print("Boards desired states is not valid JSON")
            return
        
        for board_name, states in response.items():
            if board_name in self.hardware_json["boards"]:
                for actuator in self.actuator_list:
                    if actuator.board_name == board_name:
                        actuator.update_desired_states(states)
            else:
                print(f"Board {board_name} not found in hardware json")

    def boards_states_received(self, response):
        if self.hardware_json is None:
            return
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            print("Boards states is not valid JSON")
            return
        
        for board_name, states in response.items():
            if board_name in self.hardware_json["boards"]:
                for actuator in self.actuator_list:
                    if actuator.board_name == board_name:
                        actuator.update_states(states)
                for sensor in self.sensor_list:
                    if sensor.board_name == board_name:
                        sensor.update_states(states)
            else:
                print(f"Board {board_name} not found in hardware json")
        self.last_update_time = QDateTime.currentDateTime()
    def send_manual_command(self):
        command = self.manual_command.toPlainText()
        if not command:
            return
        #self.manual_response.clear()
        try:
            command_json = json.loads(command)
            if "command" not in command_json:
                self.manual_response.append("No command in JSON")
                return
            if "data" not in command_json:
                self.manual_response.append("No data in JSON")
                return
            self.udp_manager.send(command)
        except json.JSONDecodeError:
            self.manual_response.append("Invalid JSON format")
    def backend_state_coroutine(self):
        self.udp_manager.send(json.dumps({"command":"get state", "data":{}}))
        self.udp_manager.send(json.dumps({"command":"get time", "data":{}}))
        if self.last_update_time is not None:
            current_time = QDateTime.currentDateTime()
            elapsed_time = self.last_update_time.msecsTo(current_time)
            self.last_state_update_label.setText(f"Last state update: {elapsed_time/1000:.1f} seconds ago")
            if elapsed_time > 5000:
                self.last_state_update_label.setStyleSheet("color: red")
            else:
                self.last_state_update_label.setStyleSheet("color: white")
        else:
            self.last_state_update_label.setStyleSheet("color: red")

if __name__ == "__main__":
    host = "192.168.137.179"

    # find with:
    # hostname -I
    #
    # output:
    # martin@raspberrypi:~/propbackend $ hostname -I
    # 192.168.137.179 172.26.163.215 2a0c:5bc0:40:2e26:deda:e82b:ed5e:b0b2 

    # host = "127.0.0.1"
    port = 8888

    app = QApplication(sys.argv)
    window = PropertyTestApp(host, port)
    window.show()

    def signal_handler(sig, frame):
        print("Exiting...")
        app.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    timer = QTimer()
    timer.start(100)  # Small interval to check signals
    timer.timeout.connect(lambda: None)

    sys.exit(app.exec())