import json    
from propbackend.utils import backend_logger
import copy

class HotfireController():
    def __init__(self):
        with open('configs/hotfiresequence.json', 'r') as file:
            sequencejson = json.load(file)

        self.set_hotfire_sequence(sequencejson)

        with open('configs/hotfiresequence.json', 'w') as file:
            json.dump(self.sequencejson, file, indent=4)

    def set_hotfire_sequence(self, sequencejson):
        self.sequencejson = sequencejson
        with open('configs/hotfiresequence.json', 'w') as file:
            json.dump(self.sequencejson, file, indent=4)

        self.time_before_ignition = self.sequencejson["time_before_ignition"]
        self.hotfire_safing_time = self.sequencejson["hotfire_safing_time"]
        self.start_end_desiredstate = self.sequencejson["start_end_desiredstate"]
        sequence = self.sequencejson["sequence"]
        times = []
        timestrs = []
        for timestr, _ in sequence.items():
            time = float(timestr)
            times.append(time)
            timestrs.append(timestr)
        
        self.sorted_times, self.sorted_timestr = (list(t) for t in zip(*sorted(zip(times, timestrs))))

        self.hotfire_end_time = self.sorted_times[-1] + self.hotfire_safing_time

    def is_hotfire_complete(self, time_since_statechange):
        T = self.get_T(time_since_statechange)
        #print(f"Hotfire complete check: T = {T}, hotfire_end_time = {self.hotfire_end_time}")
        if T > self.hotfire_end_time:
            return True
        else:
            return False

    def get_T(self, time_since_statechange):
        T = time_since_statechange - self.time_before_ignition
        return T


    def get_hotfire_sequence(self):
        return self.sequencejson
    
    def get_hotfire_desiredstate(self, time_since_statechange):
        T = self.get_T(time_since_statechange)
        if T < self.sorted_times[0] or T > self.sorted_times[-1]:
            new_desired_state = self.start_end_desiredstate
        else:
            time_index = 0
            while T > self.sorted_times[time_index+1]: #HOLY SHIT HOW DID I FORGET THIS +1 A SECOND TIME
                time_index += 1
            desired_state = self.sequencejson["sequence"][self.sorted_timestr[time_index]]


            #Ramping logic ----
            new_desired_state = copy.deepcopy(desired_state)
            for board_name, board_data in desired_state.items():
                for hw_type, hw_data in board_data.items():
                    if hw_type == "servos":
                        for servo_name, servo_data in hw_data.items():
                            if "ramp_to_next" in servo_data and servo_data["ramp_to_next"]:
                                try:
                                    current_angle = desired_state[board_name][hw_type][servo_name]["angle"]
                                    next_desired_state = self.sequencejson["sequence"][self.sorted_timestr[time_index+1]]
                                    next_desired_angle = next_desired_state[board_name][hw_type][servo_name]["angle"]
                                    last_time = self.sorted_times[time_index]
                                    next_time = self.sorted_times[time_index+1]
                                    weighted_angle = (current_angle * (next_time - T) + next_desired_angle * (T - last_time)) / (next_time - last_time)
                                    # backend_logger.info(f"Ramping servo {servo_name} on board {board_name} from {current_angle} to {next_desired_angle}. Current time: {T}, last_time: {last_time}, next_time: {next_time}, weighted_angle: {weighted_angle}")
                                    new_desired_state[board_name][hw_type][servo_name]["angle"] = weighted_angle
                                    new_desired_state[board_name][hw_type][servo_name].pop("ramp_to_next") #Remove this key so it doesn't interfere with actuation logic
                                except IndexError:
                                    backend_logger.critical("IndexError: Hotfire sequence is not long enough to apply ramping logic.")

        # backend_logger.info(f"Yeah{json.dumps(new_desired_state)}")
        return new_desired_state #THIS A DICT OF BOARDS, WITH THEIR DESIRED STATES INSIDE

    def get_abort_desiredstate(self):
        return self.start_end_desiredstate