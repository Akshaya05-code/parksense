import jetson_utils
import argparse
import sys
from pymavlink import mavutil
import time
import math
import os

class Rover:
    def __init__(self, serial_port="/dev/ttyUSB0", baud_rate=57600, input_uri="/dev/video0", output_uri="display://2", width=640, height=480):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.connection = None
        self.input_stream = None
        self.output_stream = None
        self.width = width
        self.height = height
        
        # Initialize camera
        try:
            self.input_stream = jetson_utils.videoSource(input_uri, argv=[f"--input-width={width}", f"--input-height={height}"])
            self.output_stream = jetson_utils.videoOutput(output_uri, argv=sys.argv)
            print("Camera initialized successfully.")
        except Exception as e:
            print(f"Camera error: {e}")
            sys.exit(1)
        
        # Connect to rover
        if not os.path.exists(serial_port):
            print(f"Error: Serial port {serial_port} does not exist.")
            sys.exit(1)
        
        try:
            with open(serial_port, 'r'):
                pass
        except PermissionError:
            print(f"Error: Permission denied for {serial_port}. Run with sudo or add user to 'dialout' group.")
            sys.exit(1)
        
        for attempt in range(3):
            try:
                self.connection = mavutil.mavlink_connection(serial_port, baud=baud_rate)
                self.connection.wait_heartbeat(timeout=10)
                print(f"Connected to rover on {serial_port}")
                break
            except Exception as e:
                print(f"Connection attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        if self.connection is None:
            print("Error: Could not connect to rover.")
            self.cleanup()
            sys.exit(1)
        
        # Set GUIDED mode
        self.connection.mav.set_mode_send(
            self.connection.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            15)  # GUIDED mode for ArduRover
        time.sleep(1)
        
        # Arm rover
        self.connection.mav.command_long_send(
            self.connection.target_system, self.connection.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 1, 0, 0, 0, 0, 0, 0)
        time.sleep(2)
        
        msg = self.connection.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
        if msg and msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
            print("Rover armed successfully.")
        else:
            print("Error: Rover failed to arm.")
            self.cleanup()
            sys.exit(1)
        
        # RC channel mappings and control parameters
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
        self.drift_threshold = 2
        self.angular_velocity = 30.0  # degrees per second for spinning

    def get_yaw(self):
        """Read current yaw in degrees."""
        msg = self.connection.recv_match(type='ATTITUDE', blocking=True, timeout=1)
        if msg:
            return math.degrees(msg.yaw)
        print("Warning: Could not retrieve yaw.")
        return None

    def send_rc_override(self, throttle, steering):
        """Send RC override commands to the rover."""
        self.connection.mav.rc_channels_override_send(
            self.connection.target_system, self.connection.target_component,
            steering, 0, throttle, 0, 0, 0, 0, 0)

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

    def capture_image(self, segment, distance):
        """Capture and save an image for inference."""
        img = self.input_stream.Capture()
        if img is not None:
            self.output_stream.Render(img)
            self.output_stream.SetStatus(f"Image Capture | Segment {segment} | {distance:.1f} meters")
            filename = f"captured_images/capture_segment_{segment}_{distance:.1f}m.jpg"
            try:
                jetson_utils.saveImage(filename, img)
                print(f"Image saved as {filename}")
                return filename
            except Exception as e:
                print(f"Failed to save image {filename}: {e}")
        return None

    def move_forward(self, distance, velocity=1.0, throttle_percent=50):
        """Move the rover forward by a specified distance."""
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
        
        # Stop the rover
        self.current_throttle = self.THROTTLE_NEUTRAL
        self.send_rc_override(self.current_throttle, self.CENTER)
        print("\nForward movement complete.")
        time.sleep(0.5)

    def move_backward(self, distance, velocity=1.0, throttle_percent=50):
        """Move the rover backward by a specified distance."""
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
        
        # Stop the rover
        self.current_throttle = self.THROTTLE_NEUTRAL
        self.send_rc_override(self.current_throttle, self.CENTER)
        print("\nBackward movement complete.")
        time.sleep(0.5)

    def spin_left(self, angle, angular_velocity=None):
        """Spin the rover left by a specified angle (in degrees)."""
        if angular_velocity is None:
            angular_velocity = self.angular_velocity
        duration = abs(angle) / angular_velocity
        self.current_steering = max(self.CENTER - self.TURN_AMOUNT * 2, 1000)  # Increase turn intensity for spinning
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
            # Normalize yaw difference
            yaw_diff = (current_yaw - target_yaw) % 360
            if yaw_diff > 180:
                yaw_diff -= 360
            if abs(yaw_diff) < 2:  # Stop if within 2 degrees of target
                break
            print(f"\rCurrent Yaw: {current_yaw:.2f}°, Target Yaw: {target_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        # Stop spinning
        self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.CENTER)
        print("\nLeft spin complete.")
        time.sleep(0.5)

    def spin_right(self, angle, angular_velocity=None):
        """Spin the rover right by a specified angle (in degrees)."""
        if angular_velocity is None:
            angular_velocity = self.angular_velocity
        duration = abs(angle) / angular_velocity
        self.current_steering = min(self.CENTER + self.TURN_AMOUNT * 2, 2000)  # Increase turn intensity for spinning
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
            # Normalize yaw difference
            yaw_diff = (current_yaw - target_yaw) % 360
            if yaw_diff > 180:
                yaw_diff -= 360
            if abs(yaw_diff) < 2:  # Stop if within 2 degrees of target
                break
            print(f"\rCurrent Yaw: {current_yaw:.2f}°, Target Yaw: {target_yaw:.2f}°", end='')
            time.sleep(0.1)
        
        # Stop spinning
        self.current_steering = self.CENTER
        self.send_rc_override(self.current_throttle, self.CENTER)
        print("\nRight spin complete.")
        time.sleep(0.5)

    def cleanup(self):
        """Disarm the rover and close camera streams."""
        self.connection.mav.rc_channels_override_send(
            self.connection.target_system, self.connection.target_component,
            0, 0, 0, 0, 0, 0, 0, 0)
        self.connection.mav.command_long_send(
            self.connection.target_system, self.connection.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 0, 0, 0, 0, 0, 0, 0)
        print("Rover disarmed.")
        self.connection.close()
        self.input_stream.Close()
        self.output_stream.Close()
        print("Camera streams closed.")