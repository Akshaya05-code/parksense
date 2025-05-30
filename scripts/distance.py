import collections
from collections.abc import MutableMapping
collections.MutableMapping = MutableMapping
from dronekit import connect, VehicleMode
from pymavlink import mavutil
from pynput import keyboard
import time
import math

try:
    vehicle = connect('/dev/ttyUSB0', baud=57600, wait_ready=False)
    print("Connected to vehicle on /dev/ttyUSB0")
except Exception as e:
    print(f"Error connecting to /dev/ttyUSB0: {e}")
    try:
        vehicle = connect('COM3', baud=57600, wait_ready=False)
        print("Connected to vehicle on COM3")
    except Exception as e:
        print(f"Error connecting to COM3: {e}")
        print("Please check your connection settings and try again.")
        exit()

THROTTLE_CH = 3
STEERING_CH = 1

CENTER = 1500
TURN_AMOUNT = 100

THROTTLE_NEUTRAL = 1500
THROTTLE_MAX = 2000
THROTTLE_MIN = 1000

current_throttle = THROTTLE_NEUTRAL
current_steering = CENTER
initial_yaw = None
drift_threshold = 2

def send_rc_override(throttle, steering):
    vehicle.channels.overrides = {
        THROTTLE_CH: throttle,
        STEERING_CH: steering
    }

def get_yaw():
    try:
        return math.degrees(vehicle.attitude.yaw)
    except AttributeError:
        print("Warning: Could not retrieve attitude information.")
        return None

def correct_drift():
    global current_steering
    yaw = get_yaw()

    if initial_yaw is None or yaw is None:
        return

    yaw_deviation = yaw - initial_yaw
    if yaw_deviation > 180:
        yaw_deviation -= 360
    elif yaw_deviation < -180:
        yaw_deviation += 360

    if yaw_deviation > drift_threshold:
        current_steering = max(CENTER - TURN_AMOUNT, 1000)
        print(f"Correcting left. Yaw deviation: {yaw_deviation:.2f}°")
    elif yaw_deviation < -drift_threshold:
        current_steering = min(CENTER + TURN_AMOUNT, 2000)
        print(f"Correcting right. Yaw deviation: {yaw_deviation:.2f}°")
    else:
        current_steering = CENTER

    send_rc_override(current_throttle, current_steering)

def move_rover(direction, throttle_percent, duration):
    global current_throttle, initial_yaw

    if direction == 'forward':
        current_throttle = int(THROTTLE_NEUTRAL + (THROTTLE_MAX - THROTTLE_NEUTRAL) * (throttle_percent / 100))
    elif direction == 'backward':
        current_throttle = int(THROTTLE_NEUTRAL - (THROTTLE_NEUTRAL - THROTTLE_MIN) * (throttle_percent / 100))
    else:
        print("Invalid direction. Use 'forward' or 'backward'.")
        return

    initial_yaw = get_yaw()
    if initial_yaw is not None:
        print(f"Starting movement. Initial Yaw: {initial_yaw:.2f}°")
    else:
        print("Starting movement. Initial yaw could not be determined.")

    print(f"Moving {direction} with throttle {throttle_percent}% for {duration:.1f} seconds...")

    speed_samples = []
    start_time = time.time()

    while time.time() - start_time < duration:
        correct_drift()
        current_yaw = get_yaw()
        current_speed = vehicle.groundspeed
        speed_samples.append(current_speed)

        if current_yaw is not None:
            print(f"\rTime: {time.time() - start_time:.1f}s | Yaw: {current_yaw:.2f}° | Speed: {current_speed:.2f} m/s", end='')
        else:
            print(f"\rTime: {time.time() - start_time:.1f}s | Yaw: Unavailable | Speed: {current_speed:.2f} m/s", end='')

        time.sleep(0.1)

    print("\nMovement duration complete. Stopping rover...")
    current_throttle = THROTTLE_NEUTRAL
    send_rc_override(current_throttle, CENTER)
    time.sleep(0.5)
    vehicle.channels.overrides = {}
    print("Rover stopped.")

    if speed_samples:
        avg_speed = sum(speed_samples) / len(speed_samples)
        distance = avg_speed * duration
        print(f"Estimated distance covered: {distance:.2f} meters.\n")
    else:
        print("No speed data to estimate distance.\n")

def spin_rover(direction, duration):
    global current_throttle, current_steering
    spin_throttle = THROTTLE_NEUTRAL + 100

    if direction == 'left':
        print(f"Spinning left for {duration:.1f} seconds...")
        current_steering = max(CENTER + TURN_AMOUNT * 2, 1000)
    elif direction == 'right':
        print(f"Spinning right for {duration:.1f} seconds...")
        current_steering = min(CENTER - TURN_AMOUNT * 2, 2000)
    else:
        print("Invalid spin direction.")
        return

    send_rc_override(spin_throttle, current_steering)

    start_time = time.time()
    while time.time() - start_time < duration:
        time.sleep(0.1)

    print("Stopping spin...")
    current_steering = CENTER
    send_rc_override(THROTTLE_NEUTRAL, current_steering)
    time.sleep(0.5)
    vehicle.channels.overrides = {}
    print("Spin stopped.")

def pause_rover(duration):
    print(f"Pausing rover for {duration:.1f} seconds...")
    send_rc_override(THROTTLE_NEUTRAL, CENTER)
    time.sleep(duration)
    print("Resuming control.")

def main():
    print("\n--- Rover Control Interface ---")
    print("Yaw-based auto-correction is active.")
    print("Commands:")
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

        if action in ['forward', 'backward']:
            if len(command) == 3:
                try:
                    throttle = int(command[1])
                    duration = float(command[2])
                    if 0 <= throttle <= 100 and duration > 0:
                        move_rover(action, throttle, duration)
                    else:
                        print("Invalid throttle or duration.")
                except ValueError:
                    print("Invalid number format.")
            else:
                print(f"Usage: {action} <throttle%> <duration>")

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
                    print("Invalid duration.")
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
            print(f"Yaw: {yaw:.2f}°" if yaw is not None else "Yaw: Unavailable")
            print(f"Groundspeed: {vehicle.groundspeed:.2f} m/s")
            print("----------------------\n")

        elif action == 'exit':
            break

        else:
            print("Invalid command.")

    print("Exiting rover control...")
    vehicle.channels.overrides = {}
    vehicle.close()
    print("Vehicle connection closed.")

if __name__ == "__main__":
    main()

