import numpy as np
from scipy.spatial.transform import Rotation as R
from propbackend.state_estimator.ukf import UKF


class HopperStateEstimator:
    def __init__(self):
        # Define state vector:
        # [x, y, z, vx, vy, vz, qw, qx, qy, qz, wx, wy, wz, m]
        # where:
        # - x,y,z: position in ENU frame (meters)
        # - vx,vy,vz: velocity in ENU frame (m/s)
        # - qw,qx,qy,qz: quaternion representing orientation
        # - wx,wy,wz: angular velocity (rad/s)
        # - m (rocket mass)
        self.n_states = 14

        # Define process noise covariance matrix (Q) (THIS NEEDS TUNING)
        self.Q = np.eye(self.n_states) * 0.01
        self.Q[0:3, 0:3] *= 0.001 # Position noise is smaller (GPT said so)
        self.Q[6:10, 6:10] *= 0.001 # Quaternion noise is smaller (GPT said so)
        self.Q[13, 13] *= 10 # Mass noise is very high

        # Define measurement vector:
        # [gnss_x, gnss_y, gnss_z,
        # accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z, mag_x, mag_y, mag_z,
        #  baro_alt, chamber_pressure]
        self.n_measurements = 14

        # Define measurement noise covariance matrix (R) (THIS NEEDS TUNING)
        self.R = np.eye(self.n_measurements)
        self.R[0:3, 0:3] *= 0.01 #GNSS Noise (in meters)
        self.R[3:6, 3:6] *= 0.1 #Accelerometer noise (in m/s^2)
        self.R[6:9, 6:9] *= 0.01 #Gyro noise (in rad/s)
        self.R[9:12, 9:12] *= 0.01 #Magnetometer noise (in uT)
        self.R[12, 12] *= 0.1 #Barometer noise (in meters)
        self.R[13, 13] *= 0.1 #Chamber pressure noise (in bar)

        #TODO MAKE THIS A FUNCTION OF MASS
        self.inertia = {
            'Ixx': 1.0,  # kg·m²
            'Iyy': 1.0,  # kg·m²
            'Izz': 0.5,  # kg·m²
            'dIxx_dt': 0.0,  # Time derivative of Ixx
            'dIyy_dt': 0.0,  # Time derivative of Iyy
            'dIzz_dt': 0.0,  # Time derivative of Izz
            'dm_dt': -0.1,   # Mass flow rate (kg/s)
        }

        self.thrust_pos = np.array([0.0, 0.0, -0.5])  # Thrust position relative to rocket body
        self.cg = np.array([0.0, 0.0, 0.0])  # Center of gravity TODO WILL CHANGE OVER TIME

        self.ukf = UKF(self.n_states, self.n_measurements, self.Q, self.R)

        self.ukf.x = np.zeros(self.n_states) # Initialize state vector to zeros
        self.ukf.x[6] = 1.0 # Set initial quaternion to identity (no rotation)
        self.ukf.x[13] = 50.0 # Set initial mass to 50 kg (arbitrary)

        self.ukf.P = np.eye(self.n_states) * 10 # Initialize covariance matrix (High uncertainty)

        # Control inputs (will be updated from sensors/commands)
        self.tvc_x_angle = 0.0  # Gimbal angle 1 (rad)
        self.tvc_y_angle = 0.0   # Gimbal angle 2 (rad)
        self.thrust = 0.0  # Thrust (N)
    
    def process_model(self, state, dt):
        new_state = np.copy(state)

        x, y, z = state[0:3]
        vx, vy, vz = state[3:6]
        qw, qx, qy, qz = state[6:10]
        wx, wy, wz = state[10:13]
        m = state[13]

        # Update position based on velocity
        new_state[0:3] += state[3:6] * dt
        
        # Update quaternion based on angular velocity
        q = np.array([qw, qx, qy, qz])
        q = q / np.linalg.norm(q)  # Normalize quaternion
        rot = R.from_quat(q, scalar_first=True)
        R_e2b = rot.as_matrix()  # Rotation matrix from ENU to body frame

        vel_enu = np.array([vx, vy, vz])
        vel_body = R_e2b @ vel_enu
        U, V, W = vel_body

        p, q, r = wx, wy, wz

        # euler = rot.as_euler('xyz')  # roll, pitch, yaw
        # phi, theta, psi = euler

        thrust_magnitude = 0 #TODO: Get from chamber pressure
        tvc_x_angle = 0 #TODO: Get from ODrive
        tvc_y_angle = 0 #TODO: Get from ODrive

        thrust_x = thrust_magnitude * np.sin(tvc_x_angle)
        thrust_y = thrust_magnitude * np.cos(tvc_x_angle) * np.sin(tvc_y_angle)
        thrust_z = thrust_magnitude * np.cos(tvc_x_angle) * np.cos(tvc_y_angle)

        g_earth = np.array([0, 0, -9.81])  # Gravity vector in ENU frame
        g_body = R_e2b @ g_earth  # Gravity vector in body frame
        g_x, g_y, g_z = g_body

        F_x = thrust_x + m * g_x
        F_y = thrust_y + m * g_y
        F_z = thrust_z + m * g_z

        #Thrust position from CG
        l_x = self.thrust_pos[0] - self.cg[0]
        l_y = self.thrust_pos[1] - self.cg[1]
        l_z = self.thrust_pos[2] - self.cg[2]

        thrust_vector = np.array([thrust_x, thrust_y, thrust_z])
        lever_arm = np.array([l_x, l_y, l_z])
        moments = np.cross(lever_arm, thrust_vector)
        L, M, N = moments
        N += self.rcs_roll #TODO Get from control system

        # Extract inertia parameters
        Ixx = self.inertia['Ixx']
        Iyy = self.inertia['Iyy']
        Izz = self.inertia['Izz']
        dIxx_dt = self.inertia['dIxx_dt']
        dIyy_dt = self.inertia['dIyy_dt']
        dIzz_dt = self.inertia['dIzz_dt']
        dm_dt = self.inertia['dm_dt']
        
        # Body-frame accelerations
        Udot = F_x/m - (W*q-V*r) + dm_dt*U/m
        Vdot = F_y/m - (U*r-p*W) + dm_dt*V/m
        Wdot = F_z/m - (V*p-U*q) + dm_dt*W/m
        
        # Angular accelerations
        pdot = (L - q*r*(Izz-Iyy) - dIxx_dt*p)/Ixx
        qdot = (M - r*p*(Ixx-Izz) - dIyy_dt*q)/Iyy
        rdot = (N - p*q*(Iyy-Ixx) + dIzz_dt*r)/Izz
                
        # Convert body accelerations to ENU accelerations
        accel_body = np.array([Udot, Vdot, Wdot])
        accel_enu = R_e2b.T @ accel_body  # Transpose of R_e2b converts body to ENU
        
        # Update position based on velocity
        new_state[0:3] += state[3:6] * dt
        
        # Update velocity based on acceleration
        new_state[3:6] += accel_enu * dt
        
        # Update quaternion
        omega = np.array([0, p, q, r])
        # https://aero.us.es/dve/Apuntes/Lesson4.pdf page 13
        q_dot = 0.5 * self.quaternion_multiply(q, omega)  # Quaternion derivative (using quaternion kinematics)
        new_state[6:10] += q_dot * dt
        new_state[6:10] /= np.linalg.norm(new_state[6:10])  # Normalize
        
        # Update angular velocity
        new_state[10] += pdot * dt
        new_state[11] += qdot * dt
        new_state[12] += rdot * dt
        
        # Update mass
        new_state[13] += dm_dt * dt
        
        return new_state
    
    def quaternion_multiply(self, q1, q2):
        """Multiply two quaternions"""
        w1, x1, y1, z1 = q1
        w2, x2, y2, z2 = q2
        
        w = w1*w2 - x1*x2 - y1*y2 - z1*z2
        x = w1*x2 + x1*w2 + y1*z2 - z1*y2
        y = w1*y2 - x1*z2 + y1*w2 + z1*x2
        z = w1*z2 + x1*y2 - y1*x2 + z1*w2
        
        return np.array([w, x, y, z])

    def measurement_model(self, state):
        x, y, z = state[0:3]
        vx, vy, vz = state[3:6]
        qw, qx, qy, qz = state[6:10]
        wx, wy, wz = state[10:13]
        m = state[13]

        # This is a function that converts the state vector to a measurement vector

        # For simplicity, assume:
        # - GNSS directly measures position in ENU frame
        # - Accelerometer measures gravity plus linear acceleration in body frame
        # - Gyroscope directly measures angular velocity in body frame
        # - Magnetometer measures the Earth's magnetic field rotated in the body frame
        # - Barometer directly measures altitude (positive z in ENU frame)

        # TODO In a real implementation, these would use proper quaternion rotations
        # to transform between body and NED frames

        rot = R.from_quat([qw, qx, qy, qz], scalar_first=True)
        R_e2b = rot.as_matrix()  # Rotation matrix from ENU to body frame

        measurement = np.zeros(self.n_measurements)

        measurement[0:3] = state[0:3] # GNSS position in ENU frame

        thrust_magnitude = 0 #TODO: Get from chamber pressure
        tvc_x_angle = 0 #TODO: Get from ODrive
        tvc_y_angle = 0 #TODO: Get from ODrive

        thrust_x = thrust_magnitude * np.sin(tvc_x_angle)
        thrust_y = thrust_magnitude * np.cos(tvc_x_angle) * np.sin(tvc_y_angle)
        thrust_z = thrust_magnitude * np.cos(tvc_x_angle) * np.cos(tvc_y_angle)

        g_earth = np.array([0, 0, -9.81])  # Gravity vector in ENU frame
        g_body = R_e2b @ g_earth  # Gravity vector in body frame
        thrust_body = np.array([thrust_x, thrust_y, thrust_z])
        accel_body = thrust_body / m - g_body  # Accelerometer measures thrust minus gravity in body frame
        measurement[3:6] = accel_body

        measurement[6:9] = state[10:13] # Gyroscope angular velocity

        mag_field_enu = np.array([0, np.cos(np.radians(67)), -np.sin(np.radians(67))])  # Earth's magnetic field in ENU frame
        mag_field_enu = mag_field_enu / np.linalg.norm(mag_field_enu)  # Normalize
        mag_field_body = R_e2b @ mag_field_enu  # Rotate to body frame
        measurement[9:12] = mag_field_body  # Magnetometer measures Earth's magnetic field in body frame

        measurement[12] = state[2]  # Barometer measures altitude (positive z in ENU frame)

        measurement[13] = 0  # Chamber pressure TODO add C_f and c_star, needs to come from PT sensor

        return measurement
    
    def predict(self, dt):
        self.ukf.predict(self.process_model, dt)

    def update_with_sensors(self, gnss=None, accel=None, gyro=None, mag=None, baro=None, chamber_pressure=None):
        """
        Update state with sensor measurements
        Each sensor can be None if not available
        """
        # Construct measurement vector from available sensors
        measurement = np.zeros(self.n_measurements)
        measurement_mask = np.zeros(self.n_measurements, dtype=bool)
        
        # GNSS position
        if gnss is not None:
            measurement[0:3] = gnss
            measurement_mask[0:3] = True
            
        # Accelerometer
        if accel is not None:
            measurement[3:6] = accel
            measurement_mask[3:6] = True

        # Gyroscope
        if gyro is not None:
            measurement[6:9] = gyro
            measurement_mask[6:9] = True
            
        # Magnetometer
        if mag is not None:
            measurement[9:12] = mag
            measurement_mask[9:12] = True
            
        # Barometer
        if baro is not None:
            measurement[12] = baro
            measurement_mask[12] = True

        # Chamber pressure
        if chamber_pressure is not None:
            measurement[13] = chamber_pressure
            measurement_mask[13] = True
            
        # Create a new measurement vector and model with only available sensors
        n_available = np.sum(measurement_mask)
        if n_available > 0:
            available_measurement = measurement[measurement_mask]
            
            # Filter R to only use available measurements
            R_available = self.ukf.R[np.ix_(measurement_mask, measurement_mask)]
            
            # Create a temporary measurement model that matches available sensors
            def available_measurement_model(state):
                full_measurement = self.measurement_model(state)
                return full_measurement[measurement_mask]
            
            # Update the UKF with available measurements
            self.ukf.update(available_measurement, available_measurement_model)
            
        return self.get_state()
    
    def get_state(self):
        """Return the current state estimate"""
        return {
            'position': self.ukf.x[0:3],
            'velocity': self.ukf.x[3:6],
            'quaternion': self.ukf.x[6:10],
            'angular_velocity': self.ukf.x[10:13]
        }
    def update_control_inputs(self, thrust, tvc_x_angle, tvc_y_angle):
        self.thrust = thrust
        self.tvc_x_angle = tvc_x_angle
        self.tvc_y_angle = tvc_y_angle

    def update_inertia_and_cg(self, mass):
        pass