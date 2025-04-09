class UKF:
    def __init__(self, n_states, n_measurements, process_noise_matrix, measurement_noise_matrix, alpha=0.001, beta=2.0, kappa=0):
        self.n = n_states # State vector dimension
        self.m = n_measurements # Measurement vector dimension
        self.x = np.zeros(self.n) # State vector
        self.P = np.eye(self.n)  # State covariance matrix
        self.Q = process_noise_matrix
        self.R = measurement_noise_matrix
        
        # Common parameters for UKF https://groups.seas.harvard.edu/courses/cs281/papers/unscented.pdf
        self.alpha = alpha
        self.beta = beta
        self.kappa = kappa
        self.lambd = alpha**2 * (self.n + kappa) - self.n
        
        self.Wm = np.full(2 * self.n + 1, 0.5 / (self.n + self.lambd))
        self.Wc = np.full(2 * self.n + 1, 0.5 / (self.n + self.lambd))
        self.Wm[0] = self.lambd / (self.n + self.lambd)
        self.Wc[0] = (self.lambd / (self.n + self.lambd)) + (1 - self.alpha**2 + self.beta)


    def generate_sigma_points(self):
        self.sigma_points = np.zeros((2 * self.n + 1, self.n))
        S = cholesky((self.n + self.lambd) * self.P)
        self.sigma_points[0] = self.x
        for i in range(self.n):
            self.sigma_points[i + 1] = self.x + S[i]
            self.sigma_points[i + 1 + self.n] = self.x - S[i]
        return self.sigma_points

    def predict(self, process_model, dt):
        sigma_points = self.generate_sigma_points()
        transformed_sigma_points = np.zeros_like(sigma_points)
        for i in range(2 * self.n + 1):
            transformed_sigma_points[i] = process_model(sigma_points[i], dt)

        x_pred = np.dot(self.Wm, transformed_sigma_points)
        P_pred = np.zeros((self.n, self.n))
        for i in range(2 * self.n + 1):
            diff = transformed_sigma_points[i] - x_pred
            P_pred += self.Wc[i] * np.outer(diff, diff)

        # Add process noise covariance
        P_pred += self.Q
        self.x = x_pred
        self.P = P_pred
        self.sigma_points = transformed_sigma_points
    
    def update(self, measurement_model, measurement):
        transformed_sigma_points = np.zeros((2 * self.n + 1, self.m))
        for i in range(2 * self.n + 1):
            transformed_sigma_points[i] = measurement_model(self.sigma_points[i])

        y_pred = np.dot(self.Wm, transformed_sigma_points)
        Pyy = np.zeros((self.m, self.m))
        for i in range(2 * self.n + 1):
            diff = transformed_sigma_points[i] - y_pred
            Pyy += self.Wc[i] * np.outer(diff, diff)

        # Add measurement noise covariance
        Pyy += self.R

        # Cross-covariance matrix
        Pxy = np.zeros((self.n, self.m))
        for i in range(2 * self.n + 1):
            diff_x = self.sigma_points[i] - self.x
            diff_y = transformed_sigma_points[i] - y_pred
            Pxy += self.Wc[i] * np.outer(diff_x, diff_y)

        # Calculate Kalman gain
        K = Pxy @ np.linalg.inv(Pyy)

        # Update state and covariance
        self.x += K @ (measurement - y_pred)
        self.P -= K @ Pyy @ K.T