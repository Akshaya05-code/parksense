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
        
        self.THROTTLE_CH = 3
        self.STEERING_CH = 1
        self.CENTER = 1500
        self.TURN_AMOUNT = 100
        self.THROTTLE_NEUTRAL = 1500
        self.THROTTLE_MAX = 2000
        self.THROTTLE_MIN = 1000
        self.current_throttle = self.THROTTLE_NEUTRAL
        self.current_steering = self.CENTER
        self.initial_yaw = None
        self.drift_threshold = 2.0
        
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
            
            print("Basic pre-arm checks...")
            while not self.vehicle.is_armable:
                print(" Waiting for vehicle to initialise...")
                time.sleep(1)
            
            print("Setting GUIDED mode...")
            self.vehicle.mode = VehicleMode("GUIDED")
            while not self.vehicle.mode.name == "GUIDED":
                print(f" Waiting for GUIDED mode... Current mode: {self.vehicle.mode.name}")
                time.sleep(1)
            
            print("Arming motors...")
            self.vehicle.armed = True
            while not self.vehicle.armed:
                print(" Waiting for arming...")
                time.sleep(1)
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
            return math.degrees(self.vehicle.attitude.yaw)
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
            self.current_steering = max(self.CENTER - self.TURN_AMOUNT, 1000)
            print(f"Correcting left. Yaw deviation: {yaw_deviation:.2f}°")
        elif yaw_deviation < -self.drift_threshold:
            self.current_steering = min(self.CENTER + self.TURN_AMOUNT, 2000)
            print(f"Correcting right. Yaw deviation: {yaw_deviation:.2f}°")
        else:
            self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.current_steering)

    def move_rover(self, direction, throttle_percent, duration):
        """Move the rover in the given direction with yaw correction."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        if direction == 'forward':
            self.current_throttle = int(self.THROTTLE_NEUTRAL + (self.THROTTLE_MAX - self.THROTTLE_NEUTRAL) * (throttle_percent / 100))
        elif direction == 'backward':
            self.current_throttle = int(self.THROTTLE_NEUTRAL - (self.THROTTLE_NEUTRAL - self.THROTTLE_MIN) * (throttle_percent / 100))
        else:
            print("Invalid direction. Use 'forward' or 'backward'.")
            return
        
        self.initial_yaw = self.get_yaw()
        if self.initial_yaw is not None:
            print(f"Starting movement. Initial Yaw: {self.initial_yaw:.2f}°")
        else:
            print("Starting movement. Initial yaw could not be determined.")
        
        print(f"Moving {direction} with throttle {throttle_percent}% for {duration:.1f} seconds...")
        start_time = time.time()
        while time.time() - start_time < duration:
            self.correct_drift()
            current_yaw = self.get_yaw()
            if current_yaw is not None:
                print(f"\rTime: {time.time() - start_time:.1f}s, Yaw: {current_yaw:.2f}°", end='')
            else:
                print(f"\rTime: {time.time() - start_time:.1f}s, Yaw: Unavailable", end='')
            time.sleep(0.1)
        
        print("\nMovement duration complete.")
        self.current_throttle = self.THROTTLE_NEUTRAL
        self.send_rc_override(self.current_throttle, self.CENTER)
        self.vehicle.channels.overrides = {}
        print("Rover stopped.")
        time.sleep(0.5)

    def forward(self, distance, velocity=1.0, throttle_percent=50):
        """Move the rover forward by a specified distance."""
        duration = distance / velocity
        self.move_rover('forward', throttle_percent, duration)

    def backward(self, distance, velocity=1.0, throttle_percent=50):
        """Move the rover backward by a specified distance."""
        duration = distance / velocity
        self.move_rover('backward', throttle_percent, duration)

    def reverse(self, distance, velocity=1.0, throttle_percent=50):
        """Reverse the rover by a specified distance (alias for backward)."""
        self.backward(distance, velocity, throttle_percent)

    def spin_left(self, duration):
        """Spin the rover left for a specified duration."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        spin_throttle = self.THROTTLE_NEUTRAL + 100
        self.current_steering = max(self.CENTER - self.TURN_AMOUNT * 2, 1000)
        
        print(f"Spinning left for {duration:.1f} seconds...")
        start_time = time.time()
        while time.time() - start_time < duration:
            self.send_rc_override(spin_throttle, self.current_steering)
            current_yaw = self.get_yaw()
            if current_yaw is not None:
                print(f"\rTime: {time.time() - start_time:.1f}s, Yaw: {current_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        print("\nSpin stopped.")
        self.current_steering = self.CENTER
        self.send_rc_override(self.THROTTLE_NEUTRAL, self.CENTER)
        self.vehicle.channels.overrides = {}
        time.sleep(0.5)

    def spin_right(self, duration):
        """Spin the rover right for a specified duration."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        spin_throttle = self.THROTTLE_NEUTRAL + 100
        self.current_steering = min(self.CENTER + self.TURN_AMOUNT * 2, 2000)
        
        print(f"Spinning right for {duration:.1f} seconds...")
        start_time = time.time()
        while time.time() - start_time < duration:
            self.send_rc_override(spin_throttle, self.current_steering)
            current_yaw = self.get_yaw()
            if current_yaw is not None:
                print(f"\rTime: {time.time() - start_time:.1f}s, Yaw: {current_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        print("\nSpin stopped.")
        self.current_steering = self.CENTER
        self.send_rc_override(self.THROTTLE_NEUTRAL, self.CENTER)
        self.vehicle.channels.overrides = {}
        time.sleep(0.5)

    def pause(self, duration):
        """Pause the rover for a specified duration."""
        if not self.vehicle or not self.vehicle.armed:
            print("Error: Rover not connected or not armed.")
            return
        
        print(f"Pausing rover for {duration:.1f} seconds...")
        self.send_rc_override(self.THROTTLE_NEUTRAL, self.CENTER)
        time.sleep(duration)
        print("Resuming control.")

    def cleanup(self):
        """Disarm the rover and close camera and vehicle connections."""
        if self.vehicle:
            self.vehicle.channels.overrides = {}
            self.vehicle.armed = False
            print("Rover disarmed.")
            self.vehicle.close()
            self.vehicle = None
        self.dismount_camera()
