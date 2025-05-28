import jetson_utils
import sys
import os
import time
import math
from dronekit import connect, VehicleMode

class Rover:
    def __init__(self, serial_port="/dev/ttyUSB0", baud_rate=57600, input_uri="/dev/video0", output_uri="display://0", width=640, height=480):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.vehicle = None
        self.input_stream = None
        self.output_stream = None
        self.width = width
        self.height = height
        
        # RC channel mappings and control parameters
        self.THROTTLE_CH = 3
        self.STEERING_CH = 1
        self.CENTER = 1500
        self.TURN_AMOUNT = 85
        self.THROTTLE_NEUTRAL = 1500
        self.THROTTLE_MAX = 2000
        self.THROTTLE_MIN = 1000
        self.current_throttle = self.THROTTLE_NEUTRAL
        self.current_steering = self.CENTER
        self.initial_yaw = None
        self.drift_threshold = 1.0
        self.angular_velocity = 30.0

        # Connect to the rover
        self._connect_rover()

    def _connect_rover(self):
        """Initialize connection to the rover using DroneKit."""
        if not os.path.exists(self.serial_port):
            print(f"Error: Serial port {self.serial_port} does not exist.")
            sys.exit(1)
        
        try:
            with open(self.serial_port, 'r'):
                pass
        except PermissionError:
            print(f"Error: Permission denied for {self.serial_port}. Run with sudo or add user to 'dialout' group.")
            sys.exit(1)
        
        try:
            self.vehicle = connect(self.serial_port, baud=self.baud_rate, wait_ready=False)
            print(f"Connected to rover on {self.serial_port}")
            
            # Set GUIDED mode
            self.vehicle.mode = VehicleMode("GUIDED")
            timeout = 10
            start_time = time.time()
            while not self.vehicle.mode.name == "GUIDED" and time.time() - start_time < timeout:
                print("Waiting for GUIDED mode...")
                time.sleep(1)
            if self.vehicle.mode.name != "GUIDED":
                print("Error: Failed to set GUIDED mode.")
                self.cleanup()
                sys.exit(1)
            
            # Arm the rover
            self.vehicle.armed = True
            start_time = time.time()
            while not self.vehicle.armed and time.time() - start_time < timeout:
                print("Waiting for arming...")
                time.sleep(1)
            if not self.vehicle.armed:
                print("Error: Failed to arm rover.")
                self.cleanup()
                sys.exit(1)
            print("Rover armed successfully.")
        except Exception as e:
            print(f"Connection failed: {e}")
            self.cleanup()
            sys.exit(1)

    def mount_camera(self, input_uri="/dev/video0", output_uri="display://0"):
        """Mount and initialize the USB camera with specified input and output URIs."""
        if self.input_stream is not None or self.output_stream is not None:
            print("Camera already mounted.")
            return False
        
        if not os.path.exists(input_uri):
            print(f"Error: USB camera device {input_uri} does not exist. Check available devices with 'ls /dev/video*'.")
            return False
        
        try:
            self.input_stream = jetson_utils.videoSource(input_uri, argv=[f"--input-width={self.width}", f"--input-height={self.height}"])
            self.output_stream = jetson_utils.videoOutput(output_uri, argv=sys.argv)
            print(f"USB camera mounted and initialized successfully on {input_uri}.")
            return True
        except Exception as e:
            print(f"Camera mount error: {e}")
            self.input_stream = None
            self.output_stream = None
            return False

    def dismount_camera(self):
        """Dismount and close the camera streams."""
        if self.input_stream is None and self.output_stream is None:
            print("No camera mounted.")
            return False
        try:
            if self.input_stream:
                self.input_stream.Close()
                self.input_stream = None
            if self.output_stream:
                self.output_stream.Close()
                self.output_stream = None
            print("Camera dismounted and streams closed.")
            return True
        except Exception as e:
            print(f"Camera dismount error: {e}")
            return False

    def capture_image(self, segment, distance):
        """Capture and save an image for inference."""
        if self.input_stream is None or self.output_stream is None:
            print("Error: Camera not mounted. Call mount_camera() first.")
            return None
        
        try:
            img = self.input_stream.Capture()
            if img is not None:
                self.output_stream.Render(img)
                self.output_stream.SetStatus(f"Image Capture | Segment {segment} | {distance:.1f} meters")
                filename = f"captured_images/capture_segment_{segment}_{distance:.1f}m.jpg"
                os.makedirs("captured_images", exist_ok=True)
                jetson_utils.saveImage(filename, img)
                print(f"Image saved as {filename}")
                return filename
            else:
                print("Error: Failed to capture image.")
                return None
        except Exception as e:
            print(f"Failed to save image: {e}")
            return None

    def get_yaw(self):
        """Read current yaw in degrees."""
        try:
            attitude = self.vehicle.attitude
            yaw_degrees = attitude.yaw * (180.0 / math.pi)
            return yaw_degrees
        except Exception as e:
            print(f"Warning: Could not retrieve yaw: {e}")
            return None

    def send_rc_override(self, throttle, steering):
        """Send RC override commands to the rover."""
        try:
            self.vehicle.channels.overrides = {
                self.STEERING_CH: steering,
                self.THROTTLE_CH: throttle
            }
        except Exception as e:
            print(f"Error sending RC override: {e}")

    def correct_drift(self):
        """Correct rover drift based on yaw deviation."""
        yaw = self.get_yaw()
        if self.initial_yaw is None or yaw is None:
            return
        
        yaw_deviation = yaw - self.initial_yaw
        if yaw_deviation > 180:
            yaw_deviation -= 360
        elif yaw_deviation < -180:
            yaw_deviation += 360
        
        if yaw_deviation > self.drift_threshold:
            self.current_steering = self.CENTER + self.TURN_AMOUNT
            print(f"Correcting left. Yaw deviation: {yaw_deviation:.2f}°")
        elif yaw_deviation < -self.drift_threshold:
            self.current_steering = self.CENTER - self.TURN_AMOUNT
            print(f"Correcting right. Yaw deviation: {yaw_deviation:.2f}°")
        else:
            self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.current_steering)

    def forward(self, distance, velocity=1.0, throttle_percent=50):
        """Move the rover forward by a specified distance."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        segment_duration = distance / velocity
        self.current_throttle = int(self.THROTTLE_NEUTRAL + (self.THROTTLE_MAX - self.THROTTLE_NEUTRAL) * (throttle_percent / 100))
        self.initial_yaw = self.get_yaw()
        
        print(f"Moving forward {distance} meters...")
        start_time = time.time()
        while time.time() - start_time < segment_duration:
            self.correct_drift()
            current_yaw = self.get_yaw()
            if current_yaw is not None:
                print(f"\rTime: {time.time() - start_time:.1f}s, Yaw: {current_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        self.current_throttle = self.THROTTLE_NEUTRAL
        self.send_rc_override(self.current_throttle, self.CENTER)
        self.vehicle.channels.overrides = {}
        print("\nForward movement complete.")
        time.sleep(0.5)

    def backward(self, distance, velocity=1.0, throttle_percent=50):
        """Move the rover backward by a specified distance."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        segment_duration = distance / velocity
        self.current_throttle = int(self.THROTTLE_NEUTRAL - (self.THROTTLE_NEUTRAL - self.THROTTLE_MIN) * (throttle_percent / 100))
        self.initial_yaw = self.get_yaw()
        
        print(f"Moving backward {distance} meters...")
        start_time = time.time()
        while time.time() - start_time < segment_duration:
            self.correct_drift()
            current_yaw = self.get_yaw()
            if current_yaw is not None:
                print(f"\rTime: {time.time() - start_time:.1f}s, Yaw: {current_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        self.current_throttle = self.THROTTLE_NEUTRAL
        self.send_rc_override(self.current_throttle, self.CENTER)
        self.vehicle.channels.overrides = {}
        print("\nBackward movement complete.")
        time.sleep(0.5)

    def reverse(self, distance, velocity=1.0, throttle_percent=50):
        """Reverse the rover by a specified distance (alias for backward)."""
        self.backward(distance, velocity, throttle_percent)

    def left(self, angle, angular_velocity=None):
        """Turn the rover left by a specified angle with gentle steering."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        if angular_velocity is None:
            angular_velocity = self.angular_velocity / 2
        duration = abs(angle) / angular_velocity
        self.current_steering = self.CENTER - self.TURN_AMOUNT
        self.current_throttle = self.THROTTLE_NEUTRAL
        
        print(f"Turning left by {angle} degrees...")
        start_yaw = self.get_yaw()
        if start_yaw is None:
            print("Cannot turn: Yaw unavailable.")
            return
        
        start_time = time.time()
        target_yaw = (start_yaw - angle) % 360
        while time.time() - start_time < duration:
            self.send_rc_override(self.current_throttle, self.current_steering)
            current_yaw = self.get_yaw()
            if current_yaw is None:
                continue
            yaw_diff = (current_yaw - target_yaw) % 360
            if yaw_diff > 180:
                yaw_diff -= 360
            if abs(yaw_diff) < 2:
                break
            print(f"\rCurrent Yaw: {current_yaw:.2f}°, Target Yaw: {target_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.CENTER)
        self.vehicle.channels.overrides = {}
        print("\nLeft turn complete.")
        time.sleep(0.5)

    def right(self, angle, angular_velocity=None):
        """Turn the rover right by a specified angle with gentle steering."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        if angular_velocity is None:
            angular_velocity = self.angular_velocity / 2
        duration = abs(angle) / angular_velocity
        self.current_steering = self.CENTER + self.TURN_AMOUNT
        self.current_throttle = self.THROTTLE_NEUTRAL
        
        print(f"Turning right by {angle} degrees...")
        start_yaw = self.get_yaw()
        if start_yaw is None:
            print("Cannot turn: Yaw unavailable.")
            return
        
        start_time = time.time()
        target_yaw = (start_yaw + angle) % 360
        while time.time() - start_time < duration:
            self.send_rc_override(self.current_throttle, self.current_steering)
            current_yaw = self.get_yaw()
            if current_yaw is None:
                continue
            yaw_diff = (current_yaw - target_yaw) % 360
            if yaw_diff > 180:
                yaw_diff -= 360
            if abs(yaw_diff) < 2:
                break
            print(f"\rCurrent Yaw: {current_yaw:.2f}°, Target Yaw: {target_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.CENTER)
        self.vehicle.channels.overrides = {}
        print("\nRight turn complete.")
        time.sleep(0.5)

    def spin_left(self, angle, angular_velocity=None):
        """Spin the rover left by a specified angle (faster than turn)."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        if angular_velocity is None:
            angular_velocity = self.angular_velocity
        duration = abs(angle) / angular_velocity
        self.current_steering = self.CENTER - self.TURN_AMOUNT * 2
        self.current_throttle = self.THROTTLE_NEUTRAL
        
        print(f"Spinning left by {angle} degrees...")
        start_yaw = self.get_yaw()
        if start_yaw is None:
            print("Cannot spin: Yaw unavailable.")
            return
        
        start_time = time.time()
        target_yaw = (start_yaw - angle) % 360
        while time.time() - start_time < duration:
            self.send_rc_override(self.current_throttle, self.current_steering)
            current_yaw = self.get_yaw()
            if current_yaw is None:
                continue
            yaw_diff = (current_yaw - target_yaw) % 360
            if yaw_diff > 180:
                yaw_diff -= 360
            if abs(yaw_diff) < 2:
                break
            print(f"\rCurrent Yaw: {current_yaw:.2f}°, Target Yaw: {target_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.CENTER)
        self.vehicle.channels.overrides = {}
        print("\nLeft spin complete.")
        time.sleep(0.5)

    def spin_right(self, angle, angular_velocity=None):
        """Spin the rover right by a specified angle (faster than turn)."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        if angular_velocity is None:
            angular_velocity = self.angular_velocity
        duration = abs(angle) / angular_velocity
        self.current_steering = self.CENTER + self.TURN_AMOUNT * 2
        self.current_throttle = self.THROTTLE_NEUTRAL
        
        print(f"Spinning right by {angle} degrees...")
        start_yaw = self.get_yaw()
        if start_yaw is None:
            print("Cannot spin: Yaw unavailable.")
            return
        
        start_time = time.time()
        target_yaw = (start_yaw + angle) % 360
        while time.time() - start_time < duration:
            self.send_rc_override(self.current_throttle, self.current_steering)
            current_yaw = self.get_yaw()
            if current_yaw is None:
                continue
            yaw_diff = (current_yaw - target_yaw) % 360
            if yaw_diff > 180:
                yaw_diff -= 360
            if abs(yaw_diff) < 2:
                break
            print(f"\rCurrent Yaw: {current_yaw:.2f}°, Target Yaw: {target_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.CENTER)
        self.vehicle.channels.overrides = {}
        print("\nRight spin complete.")
        time.sleep(0.5)

    def cleanup(self):
        """Disarm the rover and close camera and vehicle connections."""
        if self.vehicle:
            self.vehicle.channels.overrides = {}
            self.vehicle.armed = False
            print("Rover disarmed.")
            self.vehicle.close()
            self.vehicle = None
        self.dismount_camera()

if __name__ == "__main__":
    try:
        rover = Rover()
        rover.mount_camera()
        rover.forward(2.0)
        rover.backward(1.0)
        rover.reverse(1.0)
        rover.left(45)
        rover.right(45)
        rover.spin_left(90)
        rover.capture_image(1, 2.0)
    finally:
        rover.cleanup()