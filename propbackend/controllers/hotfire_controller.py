import json    

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
            desired_state = self.start_end_desiredstate
        else:
            time_index = 0
            while T > self.sorted_times[time_index]:
                time_index += 1
            desired_state = self.sequencejson["sequence"][self.sorted_timestr[time_index]]
        
        return desired_state #THIS A DICT OF BOARDS, WITH THEIR DESIRED STATES INSIDE
    
    def get_abort_desiredstate(self):
        return self.start_end_desiredstate