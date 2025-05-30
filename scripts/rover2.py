import collections
from collections.abc import MutableMapping
collections.MutableMapping = MutableMapping
from dronekit import connect, VehicleMode
from pymavlink import mavutil
from pynput import keyboard
import time
import math

# Connect to the Pixhawk (Adjust COM port or connection method as needed)
try:
    vehicle = connect('/dev/ttyUSB0', baud=57600, wait_ready=False)  # For Linux/macOS
    print("Connected to vehicle on /dev/ttyUSB0")
except Exception as e:
    print(f"Error connecting to /dev/ttyUSB0: {e}")
    try:
        vehicle = connect('/dev/ttyUSB0', baud=57600, wait_ready=False)  # For Windows (example COM port)
        print("Connected to vehicle on COM3")
    except Exception as e:
        print(f"Error connecting to COM3: {e}")
        print("Please check your connection settings and try again.")
        exit()

# RC channel mappings
THROTTLE_CH = 3  # Forward/Backward
STEERING_CH = 1  # Left/Right steering

# Steering values
CENTER = 1500
TURN_AMOUNT = 100  # Adjust for more pronounced steering correction

# Throttle values
THROTTLE_NEUTRAL = 1500
THROTTLE_MAX = 2000
THROTTLE_MIN = 1000

current_throttle = THROTTLE_NEUTRAL
current_steering = CENTER
initial_yaw = None  # Stores the reference yaw
drift_threshold = 2  # Degrees of yaw deviation before correction

def arm_and_takeoff(aTargetAltitude):
    """Arms vehicle and fly to aTargetAltitude."""

    print("Basic pre-arm checks...")
    # Don't let the user try to arm until autopilot is ready
    while not vehicle.is_armable:
        print(" Waiting for vehicle to initialise...")
        time.sleep(1)

    print("Arming motors")
    # Copter should arm in GUIDED mode
    vehicle.mode = VehicleMode("GUIDED")
    vehicle.armed = True

    while not vehicle.armed:
        print(" Waiting for arming...")
        time.sleep(1)

    print("Taking off!")
    vehicle.simple_takeoff(aTargetAltitude)  # Take off to target altitude

    # Wait until the vehicle reaches a safe height before processing the goto (otherwise the goto will trigger immediately.
    while True:
        print(f" Altitude: {vehicle.location.global_relative_frame.alt:.2f}m")
        # Break and return from function just below target altitude.
        if vehicle.location.global_relative_frame.alt >= aTargetAltitude * 0.95:
            print("Reached target altitude")
            break
        time.sleep(1)

def send_rc_override(throttle, steering):
    """Sends RC override commands to Pixhawk"""
    vehicle.channels.overrides = {
        THROTTLE_CH: throttle,
        STEERING_CH: steering
    }

def get_yaw():
    """Reads current yaw from Pixhawk in degrees"""
    try:
        return math.degrees(vehicle.attitude.yaw)
    except AttributeError:
        print("Warning: Could not retrieve attitude information. Yaw correction might be affected.")
        return None

def correct_drift():
    """Corrects rover drift based on yaw deviation"""
    global current_steering
    yaw = get_yaw()

    if initial_yaw is None or yaw is None:
        return  # No correction needed if no reference yaw is set or yaw is unavailable

    yaw_deviation = yaw - initial_yaw
    # Normalize the angle difference to be within -180 to 180 degrees
    if yaw_deviation > 180:
        yaw_deviation -= 360
    elif yaw_deviation < -180:
        yaw_deviation += 360

    if yaw_deviation > drift_threshold:  # Drifting right, correct left
        current_steering = max(CENTER - TURN_AMOUNT, 1000)  # Ensure within bounds
        print(f"Correcting left. Yaw deviation: {yaw_deviation:.2f}°")
    elif yaw_deviation < -drift_threshold:  # Drifting left, correct right
        current_steering = min(CENTER + TURN_AMOUNT, 2000)  # Ensure within bounds
        print(f"Correcting right. Yaw deviation: {yaw_deviation:.2f}°")
    else:
        current_steering = CENTER  # Stay centered if within threshold

    send_rc_override(current_throttle, current_steering)

def move_rover(direction, throttle_percent, duration):
    """Moves the rover in the given direction with yaw correction and prints updates."""
    global current_throttle, initial_yaw

    if direction == 'forward':
        current_throttle = int(THROTTLE_NEUTRAL + (THROTTLE_MAX - THROTTLE_NEUTRAL) * (throttle_percent / 100))
    elif direction == 'backward':
        current_throttle = int(THROTTLE_NEUTRAL - (THROTTLE_NEUTRAL - THROTTLE_MIN) * (throttle_percent / 100))
    else:
        print("Invalid direction. Use 'forward' or 'backward'.")
        return

    # Store initial yaw when movement starts
    initial_yaw = get_yaw()
    if initial_yaw is not None:
        print(f"Starting movement. Initial Yaw: {initial_yaw:.2f}°")
    else:
        print("Starting movement. Initial yaw could not be determined.")

    print(f"Moving {direction} with throttle {throttle_percent}% for {duration:.1f} seconds...")
    start_time = time.time()
    while time.time() - start_time < duration:
        correct_drift()  # Continuously adjust steering to maintain direction
        current_yaw = get_yaw()
        if current_yaw is not None:
            print(f"\rTime: {time.time() - start_time:.1f}s, Current Yaw: {current_yaw:.2f}°", end='')
        else:
            print(f"\rTime: {time.time() - start_time:.1f}s, Yaw: Unavailable", end='')
        time.sleep(0.1)
    print("\nMovement duration complete.")

    # Stop movement after duration
    print("Stopping rover...")
    current_throttle = THROTTLE_NEUTRAL
    send_rc_override(current_throttle, CENTER)
    time.sleep(0.5)
    vehicle.channels.overrides = {}  # Clear overrides
    print("Rover stopped.")

def spin_rover(direction, duration):
    """Spins the rover left or right for a specified duration."""
    global current_throttle, current_steering
    spin_throttle = THROTTLE_NEUTRAL + 100  # Slightly forward to overcome inertia

    if direction == 'left':
        print(f"Spinning left for {duration:.1f} seconds...")
        current_steering = max(CENTER + TURN_AMOUNT * 2, 1000) # More aggressive turn
        send_rc_override(spin_throttle, current_steering)
    elif direction == 'right':
        print(f"Spinning right for {duration:.1f} seconds...")
        current_steering = min(CENTER - TURN_AMOUNT * 2, 2000) # More aggressive turn
        send_rc_override(spin_throttle, current_steering)
    else:
        print("Invalid spin direction. Use 'left' or 'right'.")
        return

    start_time = time.time()
    while time.time() - start_time < duration:
        time.sleep(0.1)

    # Stop spinning
    print("Stopping spin...")
    current_steering = CENTER
    send_rc_override(THROTTLE_NEUTRAL, current_steering)
    time.sleep(0.5)
    vehicle.channels.overrides = {}
    print("Spin stopped.")

def pause_rover(duration):
    """Pauses the rover for a specified duration."""
    print(f"Pausing rover for {duration:.1f} seconds...")
    send_rc_override(THROTTLE_NEUTRAL, CENTER)
    time.sleep(duration)
    print("Resuming control.")

def main():
    """Main function with more interactive moments."""
    print("\n--- Rover Control Interface ---")
    print("Yaw-based auto-correction is active.")
    print("Type commands to control the rover:")
    print("  forward <throttle%> <duration>")
    print("  backward <throttle%> <duration>")
    print("  spin <left/right> <duration>")
    print("  pause <duration>")
    print("  status")
    print("  exit")

    while True:
        command = input("> ").strip().lower().split()

        if not command:
            continue

        action = command[0]

        if action == 'forward':
            if len(command) == 3:
                try:
                    throttle = int(command[1])
                    duration = float(command[2])
                    if 0 <= throttle <= 100 and duration > 0:
                        move_rover('forward', throttle, duration)
                    else:
                        print("Invalid throttle or duration.")
                except ValueError:
                    print("Invalid throttle or duration format.")
            else:
                print("Usage: forward <throttle%> <duration>")

        elif action == 'backward':
            if len(command) == 3:
                try:
                    throttle = int(command[1])
                    duration = float(command[2])
                    if 0 <= throttle <= 100 and duration > 0:
                        move_rover('backward', throttle, duration)
                    else:
                        print("Invalid throttle or duration.")
                except ValueError:
                    print("Invalid throttle or duration format.")
            else:
                print("Usage: backward <throttle%> <duration>")

        elif action == 'spin':
            if len(command) == 2:
                direction = command[1]
                try:
                    duration = float(input("Enter spin duration in seconds: "))
                    if direction in ['left', 'right'] and duration > 0:
                        spin_rover(direction, duration)
                    else:
                        print("Invalid spin direction or duration.")
                except ValueError:
                    print("Invalid duration format.")
            else:
                print("Usage: spin <left/right>")

        elif action == 'pause':
            if len(command) == 2:
                try:
                    duration = float(command[1])
                    if duration > 0:
                        pause_rover(duration)
                    else:
                        print("Invalid duration.")
                except ValueError:
                    print("Invalid duration format.")
            else:
                print("Usage: pause <duration>")

        elif action == 'status':
            print("\n--- Rover Status ---")
            print(f"Mode: {vehicle.mode.name}")
            print(f"Armed: {vehicle.armed}")
            attitude = vehicle.attitude
            print(f"Roll: {math.degrees(attitude.roll):.2f}°")
            print(f"Pitch: {math.degrees(attitude.pitch):.2f}°")
            yaw = get_yaw()
            if yaw is not None:
                print(f"Yaw: {yaw:.2f}°")
            else:
                print("Yaw: Unavailable")
            print(f"Groundspeed: {vehicle.groundspeed:.2f} m/s")
            print("----------------------\n")

        elif action == 'exit':
            break

        else:
            print("Invalid command. Please use one of the available commands.")

    print("Exiting rover control...")
    vehicle.channels.overrides = {}  # Clear overrides
    vehicle.close()
    print("Vehicle connection closed.")

if __name__ == "__main__":
    main()
