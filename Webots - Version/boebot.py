# boe_bot_controller.py (Challenge 1 Adaptation - No GPS)

from controller import Robot, Motor, DistanceSensor, InertialUnit # Removed GPS, added Recognition
import socket
import json
import threading
import time
import queue

# --- Configuration ---
IPC_HOST = 'localhost'
IPC_PORT = 10001
BUFFER_SIZE = 4096
MAX_SPEED = 6.28
OBSTACLE_THRESHOLD_FRONT = 0.3 # meters - TUNE THIS! Stop/turn if closer than this
OBSTACLE_THRESHOLD_SIDE = 0.3 # meters - TUNE THIS! Used for wall following/turning
WALL_FOLLOW_DISTANCE = 0.4  # meters - TUNE THIS! Target distance for wall following
SURVIVOR_RECOGNITION_COLOR = [1, 0, 0] # Example: Detect RED objects as survivors

# --- Device Names (****** MUST MATCH YOUR WEBOTS MODEL ******) ---
LEFT_MOTOR_NAME = "left wheel motor"
RIGHT_MOTOR_NAME = "right wheel motor"
# Add more sensors for better navigation
FRONT_DS_NAME = "ds_front"
LEFT_DS_NAME = "ds_left"   # Example side sensor
RIGHT_DS_NAME = "ds_right"  # Example side sensor
IMU_NAME = "imu"            # For orientation/tilt (Accelerometer proxy)
# Removed GPS_NAME
# Removed BATTERY_SENSOR_NAME (using simulation below)
# Removed specific RFID/IR sensor names - using recognition on DS

# --- Global Variables ---
command_queue = queue.Queue(maxsize=1)
state_queue = queue.Queue(maxsize=1)
client_socket = None
ipc_thread_running = True
current_left_speed = 0.0
current_right_speed = 0.0
simulated_battery = 100.0
battery_drain_rate = 0.05 # Example % per second

# --- IPC Server Thread (Largely unchanged - handles comms) ---
def handle_client_connection(conn, addr):
    # ... (Keep the IPC handling code from the previous version) ...
    # ... (Ensure it sends state from state_queue when "get_state" is received) ...
    global client_socket, ipc_thread_running
    client_socket = conn
    print(f"IPC Server: Connection established with {addr}")
    conn.settimeout(10.0)

    received_buffer = b""

    while ipc_thread_running:
        try:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                print("IPC Server: Client disconnected.")
                break

            received_buffer += data
            while b'\n' in received_buffer:
                message_bytes, received_buffer = received_buffer.split(b'\n', 1)
                message_str = message_bytes.decode('utf-8').strip()
                if not message_str: continue

                # print(f"IPC Server: Received command JSON: {message_str}") # Debug
                try:
                    command = json.loads(message_str)
                    if command_queue.full():
                        try: command_queue.get_nowait()
                        except queue.Empty: pass
                    command_queue.put(command)

                    if command.get("command") == "get_state":
                        try:
                            current_state = state_queue.get(timeout=0.5)
                            state_json = json.dumps(current_state)
                            response = (state_json + '\n').encode('utf-8')
                            conn.sendall(response)
                            # print("IPC Server: Sent state data.") # Debug
                        except queue.Empty:
                            print("IPC Server: Warning - State data not ready.")
                            conn.sendall(json.dumps({"error": "State not available"}).encode('utf-8') + b'\n')
                        except Exception as e: print(f"IPC Server: Error sending state - {e}")
                except json.JSONDecodeError: print(f"IPC Server: Error - Invalid JSON: {message_str}")
                except Exception as e: print(f"IPC Server: Error processing command - {e}")
        except socket.timeout: continue
        except socket.error as e:
            print(f"IPC Server: Socket error - {e}. Closing connection.")
            break
        except Exception as e:
            print(f"IPC Server: Unexpected error - {e}. Closing connection.")
            break

    print(f"IPC Server: Closing connection with {addr}")
    try: conn.close()
    except: pass
    client_socket = None

def ipc_server_thread():
    # ... (Keep the IPC server setup code from the previous version) ...
    global ipc_thread_running
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((IPC_HOST, IPC_PORT))
        server_socket.listen(1)
        print(f"IPC Server: Listening on {IPC_HOST}:{IPC_PORT}...")
        while ipc_thread_running:
            try:
                server_socket.settimeout(1.0)
                conn, addr = server_socket.accept()
                handle_client_connection(conn, addr)
                print("IPC Server: Client disconnected, waiting for new connection...")
            except socket.timeout: continue
            except Exception as e:
                if ipc_thread_running: # Avoid error message during shutdown
                     print(f"IPC Server: Error accepting connection - {e}")
                time.sleep(1)
    except Exception as e: print(f"IPC Server: Failed to bind or listen - {e}")
    finally:
        print("IPC Server: Shutting down...")
        server_socket.close()


# --- Motor Control Functions (Unchanged) ---
def set_speeds(left, right):
    global current_left_speed, current_right_speed
    current_left_speed = max(-MAX_SPEED, min(MAX_SPEED, left))
    current_right_speed = max(-MAX_SPEED, min(MAX_SPEED, right))

def handle_move_command(direction):
    if direction == "forward": set_speeds(MAX_SPEED, MAX_SPEED)
    elif direction == "backward": set_speeds(-MAX_SPEED, -MAX_SPEED)
    elif direction == "left" or direction == "turn_left": set_speeds(-MAX_SPEED * 0.5, MAX_SPEED * 0.5)
    elif direction == "right" or direction == "turn_right": set_speeds(MAX_SPEED * 0.5, -MAX_SPEED * 0.5)
    else: handle_stop_command()

def handle_stop_command():
    set_speeds(0.0, 0.0)

# --- Main Controller Logic ---
if __name__ == "__main__":
    robot = Robot()
    timestep = int(robot.getBasicTimeStep())
    print(f"Controller using timestep: {timestep} ms")

    # --- Get Devices ---
    devices = {}
    motor_names = [LEFT_MOTOR_NAME, RIGHT_MOTOR_NAME]
    ds_names = [FRONT_DS_NAME, LEFT_DS_NAME, RIGHT_DS_NAME] # Include side sensors
    imu_name = IMU_NAME

    # Motors
    for name in motor_names:
        motor = robot.getDevice(name)
        if motor is None: print(f"ERROR: Motor '{name}' not found!")
        else: devices[name] = motor

    if LEFT_MOTOR_NAME not in devices or RIGHT_MOTOR_NAME not in devices:
        print("CRITICAL ERROR: Cannot operate without wheel motors. Exiting.")
        exit()

    # Distance Sensors
    for name in ds_names:
        ds = robot.getDevice(name)
        if ds is None: print(f"Warning: DistanceSensor '{name}' not found!")
        else:
            devices[name] = ds
            ds.enable(timestep)
            # *** Enable Recognition for survivor detection ***
            try:
                ds.recognitionEnable(timestep)
                print(f"Enabled recognition for {name}")
            except AttributeError:
                print(f"Warning: Recognition not supported or enabled for DistanceSensor '{name}'.")
            except Exception as e:
                print(f"Warning: Error enabling recognition for {name}: {e}")


    # IMU
    imu = robot.getDevice(imu_name)
    if imu is None: print(f"Warning: IMU '{imu_name}' not found!")
    else:
        devices[imu_name] = imu
        imu.enable(timestep)

    # --- Initialize Motors ---
    devices[LEFT_MOTOR_NAME].setPosition(float('inf'))
    devices[RIGHT_MOTOR_NAME].setPosition(float('inf'))
    devices[LEFT_MOTOR_NAME].setVelocity(0.0)
    devices[RIGHT_MOTOR_NAME].setVelocity(0.0)

    # --- Start IPC Thread ---
    ipc_thread = threading.Thread(target=ipc_server_thread, daemon=True)
    ipc_thread.start()

    print("Controller: Entering main simulation loop...")

    # --- Main Loop ---
    while robot.step(timestep) != -1:
        # --- Process Incoming Commands ---
        try:
            command = command_queue.get_nowait()
            cmd_type = command.get("command")
            if cmd_type == "move": handle_move_command(command.get("direction", "stop"))
            elif cmd_type == "stop": handle_stop_command()
            elif cmd_type == "deploy_aid": print("Main Loop: Received deploy_aid (Action TBD)")
            elif cmd_type != "get_state": print(f"Main Loop: Unknown command '{cmd_type}'")
        except queue.Empty: pass
        except Exception as e: print(f"Main Loop: Error processing command - {e}")

        # --- Read Sensors & Detect Survivors ---
        sensor_readings = {}
        survivor_nearby = False
        survivor_details = {} # Optional: distance, etc.

        for name, ds in devices.items():
            if isinstance(ds, DistanceSensor):
                 value = ds.getValue()
                 sensor_readings[name] = round(value, 3) # Store raw sensor value

                 # --- Survivor Detection Logic ---
                 try:
                      recognized_objects = ds.getRecognitionRecognizedObjects()
                      for obj in recognized_objects:
                           # Check model name or color - **ADAPT THIS CHECK**
                           obj_color = obj.getColors() # Returns list [R, G, B]
                           # obj_name = obj.getModel() # Alternative check
                           # print(f"DEBUG: Recognized {obj.getModel()} Color: {obj_color}")
                           if obj_color == SURVIVOR_RECOGNITION_COLOR:
                                survivor_nearby = True
                                # Can get relative position if needed: obj.getPosition()
                                print(f"*** Survivor Detected by {name}! ***")
                                # Simple: just flag detection. Complex: get details.
                                survivor_details = {"detected_by": name} # Basic info
                                break # Stop checking once one is found this step
                 except AttributeError: pass # Recognition not enabled/supported
                 except Exception as e: print(f"Error checking recognition on {name}: {e}")
            if survivor_nearby: break # Stop checking other sensors if found

        # IMU Data
        imu_values = devices[imu_name].getRollPitchYaw() if imu_name in devices else [0.0, 0.0, 0.0]

        # --- Simulate Battery ---
        time_elapsed_sec = timestep / 1000.0
        # More realistic drain based on speed
        speed_factor = (abs(current_left_speed) + abs(current_right_speed)) / (2 * MAX_SPEED)
        simulated_battery -= battery_drain_rate * time_elapsed_sec * (0.5 + speed_factor) # Drain more when moving
        simulated_battery = max(0.0, simulated_battery)

        # --- Prepare State Dictionary (NO GPS) ---
        current_state = {
            "timestamp": robot.getTime(),
            # "position": REMOVED,
            "orientation": {"roll": imu_values[0], "pitch": imu_values[1], "yaw": imu_values[2]},
            "battery": round(simulated_battery, 2),
            "is_charging": False,
            "sensors": { # Pass specific sensor readings needed by backend
                "ultrasonic_front": sensor_readings.get(FRONT_DS_NAME, 999.0),
                "ultrasonic_left": sensor_readings.get(LEFT_DS_NAME, 999.0),
                "ultrasonic_right": sensor_readings.get(RIGHT_DS_NAME, 999.0),
                # Add other specific sensor values if needed (e.g., raw IR/RFID value)
            },
            "survivor_nearby": survivor_nearby, # Simple boolean flag
            "survivor_details": survivor_details # Optional extra info
        }

        # --- Update State Queue for IPC ---
        if state_queue.full():
            try: state_queue.get_nowait()
            except queue.Empty: pass
        state_queue.put(current_state)

        # --- Apply Motor Velocities ---
        devices[LEFT_MOTOR_NAME].setVelocity(current_left_speed)
        devices[RIGHT_MOTOR_NAME].setVelocity(current_right_speed)

        # --- Internal Safety/Wall Following (Optional) ---
        # if sensor_readings.get(FRONT_DS_NAME, 999.0) < OBSTACLE_THRESHOLD_FRONT:
        #     print("Controller Override: Front Obstacle! Stopping/Turning.")
        #     # Implement turning logic here based on side sensors if available
        #     handle_move_command("turn_left") # Example basic reaction


    # --- Cleanup ---
    print("Controller: Simulation ended.")
    ipc_thread_running = False
    if client_socket:
        try: client_socket.close()
        except: pass
    ipc_thread.join(timeout=2.0)
    print("Controller: Exiting.")z