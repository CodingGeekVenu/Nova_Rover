# supervisor_monitor.py (Receives survivor signal from BoeBot emitter)

from controller import Supervisor, Receiver # Added Receiver
import socket
import json
import threading
import time
import math
import queue

# --- Configuration ---
IPC_HOST = 'localhost'
IPC_PORT = 10001
BUFFER_SIZE = 4096
ROBOT_DEF_NAME = "MY_BOEBOT" # *** MUST MATCH THE DEF NAME OF YOUR BOE-BOT NODE ***
POSITION_HISTORY_LENGTH = 5
RECEIVER_NAME = "status_receiver" # *** 'name' of Receiver device on Supervisor ***
EMITTER_CHANNEL = 1               # *** Must match Emitter channel in C code ***
SURVIVOR_MESSAGE = "SURVIVOR_FOUND" # Message the C code sends

# --- Global Variables ---
state_queue = queue.Queue(maxsize=1)
client_socket = None
ipc_thread_running = True
robot_node = None
last_known_position = None
position_history = []
last_observation_time = 0.0
survivor_signal_received = False # Flag set by receiver check

# --- IPC Server Thread (Unchanged from previous Supervisor version) ---
def handle_client_connection(conn, addr):
    # ... (Identical IPC handling code) ...
    global client_socket, ipc_thread_running
    client_socket = conn
    print(f"Supervisor IPC: Connection established with {addr}")
    conn.settimeout(10.0)
    received_buffer = b""

    while ipc_thread_running:
        try:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                print("Supervisor IPC: Client disconnected.")
                break
            received_buffer += data
            while b'\n' in received_buffer:
                message_bytes, received_buffer = received_buffer.split(b'\n', 1)
                message_str = message_bytes.decode('utf-8').strip()
                if not message_str: continue
                try:
                    command = json.loads(message_str)
                    if command.get("command") == "get_state":
                        try:
                            current_state = state_queue.get(timeout=0.5)
                            state_json = json.dumps(current_state)
                            response = (state_json + '\n').encode('utf-8')
                            conn.sendall(response)
                        except queue.Empty:
                            print("Supervisor IPC: Warning - State data not ready.")
                            conn.sendall(json.dumps({"error": "State not available"}).encode('utf-8') + b'\n')
                        except Exception as e: print(f"Supervisor IPC: Error sending state - {e}")
                    # else: Ignore other commands
                except json.JSONDecodeError: print(f"Supervisor IPC: Error - Invalid JSON: {message_str}")
                except Exception as e: print(f"Supervisor IPC: Error processing command - {e}")
        except socket.timeout: continue
        except socket.error as e:
            print(f"Supervisor IPC: Socket error - {e}. Closing connection.")
            break
        except Exception as e:
            print(f"Supervisor IPC: Unexpected error - {e}. Closing connection.")
            break

    print(f"Supervisor IPC: Closing connection with {addr}")
    try: conn.close()
    except: pass
    client_socket = None

def ipc_server_thread():
    # ... (Identical IPC server setup code) ...
    global ipc_thread_running
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((IPC_HOST, IPC_PORT))
        server_socket.listen(1)
        print(f"Supervisor IPC: Listening on {IPC_HOST}:{IPC_PORT}...")
        while ipc_thread_running:
            try:
                server_socket.settimeout(1.0)
                conn, addr = server_socket.accept()
                handle_client_connection(conn, addr)
                print("Supervisor IPC: Client disconnected, waiting for new connection...")
            except socket.timeout: continue
            except Exception as e:
                if ipc_thread_running:
                    print(f"Supervisor IPC: Error accepting connection - {e}")
                time.sleep(1)
    except Exception as e: print(f"Supervisor IPC: Failed to bind or listen - {e}")
    finally:
        print("Supervisor IPC: Shutting down...")
        server_socket.close()

# --- Helper Functions (Unchanged) ---
def estimate_velocity(current_time, current_pos):
    global position_history, last_observation_time
    if not current_pos or not position_history: return 0.0
    dt = current_time - last_observation_time
    if dt <= 0: return 0.0
    prev_pos = position_history[-1]
    distance = math.sqrt(sum([(c - p)**2 for c, p in zip(current_pos, prev_pos)]))
    return distance / dt

def infer_robot_status(velocity, survivor_signal):
    VELOCITY_STOPPED_THRESHOLD = 0.01
    if survivor_signal: # If signal received, assume deploying aid overrides velocity check
        return "Deploying Aid (Signaled)"
    elif velocity < VELOCITY_STOPPED_THRESHOLD:
        return "Stopped / Idle"
    elif velocity > 0.1:
        return "Searching / Moving"
    else:
        return "Unknown / Slow / Turning"

# --- Main Supervisor Logic ---
if __name__ == "__main__":
    supervisor = Supervisor()
    timestep = int(supervisor.getBasicTimeStep())
    print(f"Supervisor using timestep: {timestep} ms")

    # --- Get Robot Node (Unchanged) ---
    robot_node = supervisor.getFromDef(ROBOT_DEF_NAME)
    if robot_node is None:
        print(f"FATAL ERROR: Supervisor could not find robot node DEF '{ROBOT_DEF_NAME}'.")
        exit()
    else: print(f"Supervisor monitoring robot: '{ROBOT_DEF_NAME}'")
    robot_translation_field = robot_node.getField("translation")
    robot_rotation_field = robot_node.getField("rotation")

    # --- Get Supervisor's Receiver ---
    receiver = supervisor.getDevice(RECEIVER_NAME)
    if receiver:
        receiver.enable(timestep)
        receiver.setChannel(EMITTER_CHANNEL) # Listen on the correct channel
        print(f"Supervisor Receiver '{RECEIVER_NAME}' enabled on channel {EMITTER_CHANNEL}.")
    else:
        print(f"ERROR: Supervisor Receiver device '{RECEIVER_NAME}' not found! Cannot receive survivor signals.")
        # Continue without receiver? Or exit? For now, continue.

    # --- Start IPC Thread (Unchanged) ---
    ipc_thread = threading.Thread(target=ipc_server_thread, daemon=True)
    ipc_thread.start()

    print("Supervisor: Entering main simulation loop...")
    last_observation_time = supervisor.getTime()

    # --- Main Loop ---
    while supervisor.step(timestep) != -1:
        current_time = supervisor.getTime()
        survivor_signal_received_this_step = False # Reset each step

        # --- Check Receiver for Messages from BoeBot ---
        if receiver:
            while receiver.getQueueLength() > 0:
                message_bytes = receiver.getData()
                try:
                    message_str = message_bytes.decode('utf-8')
                    print(f"Supervisor Receiver: Received '{message_str}'")
                    if message_str == SURVIVOR_MESSAGE:
                        survivor_signal_received_this_step = True
                        # Could add a timestamp here if needed
                except Exception as e:
                    print(f"Supervisor Receiver: Error decoding message - {e}")
                receiver.nextPacket() # IMPORTANT: Clear the packet queue

        # --- Observe Robot State (Unchanged) ---
        try:
            position = robot_translation_field.getSFVec3f()
            orientation_data = {"roll": 0, "pitch": 0, "yaw": 0} # Placeholder
            if position:
                linear_velocity = estimate_velocity(current_time, position)
                position_history.append(position)
                if len(position_history) > POSITION_HISTORY_LENGTH: position_history.pop(0)
                last_known_position = position
            else: linear_velocity = 0.0

            inferred_status = infer_robot_status(linear_velocity, survivor_signal_received_this_step)
            estimated_battery = max(0.0, 100.0 - (current_time * 0.1)) # Rough guess
            observed_sensors = { "info": "Direct sensor reading unavailable via Supervisor" }

        except Exception as e:
            # ... (Error handling for observation unchanged) ...
            print(f"Supervisor Error observing robot: {e}")
            position = last_known_position
            orientation_data = {"roll": 0, "pitch": 0, "yaw": 0}
            linear_velocity = 0.0
            inferred_status = "Error Observing"
            estimated_battery = 0.0
            observed_sensors = {"error": str(e)}


        # --- Prepare State Dictionary for Backend ---
        current_observed_state = {
            "timestamp": current_time,
            "position": {"x": position[0], "y": position[1], "z": position[2]} if position else None,
            "orientation": orientation_data,
            "battery": round(estimated_battery, 2),
            "is_charging": False,
            "sensors": observed_sensors,
            "survivor_nearby": survivor_signal_received_this_step, # Use the received signal flag
            "survivor_details": {"signaled": True} if survivor_signal_received_this_step else {},
            "inferred_status": inferred_status,
            "observed_velocity": round(linear_velocity, 3)
        }

        # --- Update State Queue (Unchanged) ---
        if state_queue.full():
            try: state_queue.get_nowait()
            except queue.Empty: pass
        state_queue.put(current_observed_state)
        last_observation_time = current_time

    # --- Cleanup (Unchanged) ---
    print("Supervisor: Simulation ended.")
    ipc_thread_running = False
    if client_socket:
        try: client_socket.close()
        except: pass
    ipc_thread.join(timeout=2.0)
    print("Supervisor: Exiting.")