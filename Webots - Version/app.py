# app.py (Monitoring Mode via Supervisor - Updated for Emitter Signal)

import flask
from flask import Flask, jsonify
import threading
import time
import copy

# Interface connects to the SUPERVISOR's TCP Server
import webots_interface

# --- Configuration ---
WEBOTS_HOST = 'localhost' # Supervisor host
WEBOTS_PORT = 10001       # Supervisor port (must match supervisor_monitor.py)
FETCH_INTERVAL = 0.5      # How often to request state from supervisor (seconds). Make it slightly faster?

# --- Global Shared State & Control (Reflects OBSERVED state from Supervisor) ---
current_observed_state = {
    "initialized": False,
    "connection_status": "Disconnected", # Connection status to Supervisor
    "last_updated": None,
    "robot_status": "Unknown",        # Will store the *inferred* status from supervisor
    "position": None,                 # Position observed by supervisor {x, y, z}
    "orientation": None,              # Orientation observed by supervisor (basic)
    "battery_level": None,            # Battery level estimated by supervisor
    "is_charging": False,             # Assumed false, supervisor doesn't know
    "comms_ok": False,                # Health of connection to Supervisor
    "sensors": {},                    # Mostly placeholder info from supervisor
    "survivor_nearby": False,         # *** Updated by signal received by Supervisor ***
    "survivor_details": {},           # Details provided by supervisor (e.g., {"signaled": True})
    "survivors_found": [],            # Log based on the survivor_nearby signal
    "path_history": [],               # Store observed path from supervisor position data
    "last_error": None,               # Errors from interface/supervisor comms
    "observed_velocity": 0.0,         # Velocity estimated by supervisor
    # "last_action_sent": None        # REMOVED - Backend is not sending actions
}
state_lock = threading.Lock()
monitor_thread_stop_event = threading.Event()

# NO Navigator needed for control
# from navigator import Navigator
# navigator = Navigator()

# --- Background Monitor Thread ---
def run_monitor_loop():
    """Background thread to fetch observed state from the supervisor."""
    global current_observed_state

    print("Monitor Thread: Starting...")
    with state_lock:
        current_observed_state["connection_status"] = "Connecting"
        current_observed_state["robot_status"] = "Initializing"
    print(f"Monitor Thread: Connecting to Supervisor at {WEBOTS_HOST}:{WEBOTS_PORT}...")
    connected = webots_interface.connect_to_webots(WEBOTS_HOST, WEBOTS_PORT)
    with state_lock:
        current_observed_state["last_updated"] = time.time()
        if connected:
            current_observed_state["initialized"] = True
            current_observed_state["connection_status"] = "Connected"
            current_observed_state["comms_ok"] = True
            print("Monitor Thread: Connection to Supervisor successful.")
        else:
            current_observed_state["connection_status"] = "Connection Failed"
            current_observed_state["last_error"] = f"Connect fail: {webots_interface.get_last_error()}"
            print(f"Monitor Thread: CRITICAL - {current_observed_state['last_error']}. Thread terminating.")
            return

    # --- Main Loop ---
    while not monitor_thread_stop_event.is_set():
        start_time = time.time()
        observed_data = None

        # --- Sense Phase (Get observed data from Supervisor) ---
        observed_data = webots_interface.get_simulation_state() # Function name is the same
        current_time = time.time()

        survivor_signal_just_received = False # Track changes
        with state_lock:
            current_observed_state["last_updated"] = current_time
            if observed_data:
                current_observed_state["comms_ok"] = True
                if current_observed_state["connection_status"] != "Connected":
                     print("Monitor Thread: Reconnected to Supervisor.")
                     current_observed_state["connection_status"] = "Connected"

                # Check if survivor flag changed to True
                old_survivor_state = current_observed_state.get("survivor_nearby", False)
                # *** Update state using supervisor data format ***
                update_observed_state(observed_data)
                new_survivor_state = current_observed_state.get("survivor_nearby", False)
                if new_survivor_state and not old_survivor_state:
                     survivor_signal_just_received = True

                # Add current position to path history (can be done now)
                if current_observed_state["position"]:
                    current_observed_state["path_history"].append(copy.deepcopy(current_observed_state["position"]))
                    if len(current_observed_state["path_history"]) > 200: # Limit history length
                        current_observed_state["path_history"].pop(0)

            else: # Failed to get data from Supervisor
                print("Monitor Thread: Failed to get data from Supervisor.")
                current_observed_state["connection_status"] = "IPC Error"
                current_observed_state["comms_ok"] = False
                current_observed_state["last_error"] = f"Get state fail: {webots_interface.get_last_error()}"

        # --- Log Survivor if Signal Received ---
        if survivor_signal_just_received:
             with state_lock: # Acquire lock again briefly for logging consistency
                  log_survivor_detection(current_observed_state)


        # --- NO Think/Act Phases ---
        # The C controller handles all decision making autonomously.

        # --- Loop Delay ---
        elapsed_time = time.time() - start_time
        sleep_time = max(0, FETCH_INTERVAL - elapsed_time)
        time.sleep(sleep_time)

    # --- Cleanup ---
    print("Monitor Thread: Loop terminated.")
    webots_interface.disconnect()
    print("Monitor Thread: Finished.")


def update_observed_state(supervisor_data):
    """
    Updates the global state based on data received from the supervisor.
    Expected format includes position, orientation, estimated battery,
    inferred_status, observed_velocity, and crucially survivor_nearby flag.
    IMPORTANT: Assumes state_lock is HELD.
    """
    global current_observed_state
    if not isinstance(supervisor_data, dict):
        print(f"Update State Error: Invalid data type: {type(supervisor_data)}")
        current_observed_state["last_error"] = "Invalid data format from supervisor"
        return

    # print(f"DEBUG Updating state with: {supervisor_data}") # Very useful!

    # Update fields based on keys received from supervisor_monitor.py
    current_observed_state["position"] = supervisor_data.get("position", current_observed_state["position"])
    current_observed_state["orientation"] = supervisor_data.get("orientation", current_observed_state["orientation"])
    current_observed_state["battery_level"] = supervisor_data.get("battery", current_observed_state["battery_level"])
    current_observed_state["is_charging"] = supervisor_data.get("is_charging", False) # Likely always false from supervisor
    current_observed_state["sensors"] = supervisor_data.get("sensors", {"info": "unavailable"})
    current_observed_state["survivor_nearby"] = supervisor_data.get("survivor_nearby", False) # *** Get the flag ***
    current_observed_state["survivor_details"] = supervisor_data.get("survivor_details", {})
    current_observed_state["robot_status"] = supervisor_data.get("inferred_status", "Unknown")
    current_observed_state["observed_velocity"] = supervisor_data.get("observed_velocity", 0.0)
    # Note: comms_ok and last_updated are handled outside this function

def log_survivor_detection(state):
    """
    Logs survivor detection based on the signal received via Supervisor.
    Logs the position OBSERVED BY THE SUPERVISOR at the time the signal was processed.
    IMPORTANT: Assumes state_lock is HELD.
    """
    # This function is called only when the survivor_nearby flag *changes* to True
    now = time.time()
    timestamp_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))
    # Use the position observed by the supervisor in the current state update
    observed_position = state.get("position")

    log_entry = {
        "id": len(state["survivors_found"]) + 1,
        "position": copy.deepcopy(observed_position) if observed_position else "Unknown", # Log observed position
        "timestamp": timestamp_str,
        "sensor_type": "Signal via Emitter/Receiver", # Indicate how it was detected
        "signal_strength": "N/A"
    }

    # Optional: Prevent logging too rapidly if signals somehow bounce (unlikely here)
    # log_cooldown_seconds = 2 # Shorter cooldown might be okay
    # if state["survivors_found"]:
    #     last_log = state["survivors_found"][-1]
    #     time_since_last = now - time.mktime(time.strptime(last_log["timestamp"], '%Y-%m-%d %H:%M:%S'))
    #     if time_since_last < log_cooldown_seconds:
    #          # print(f"Skipping rapid survivor log within {log_cooldown_seconds}s.")
    #          return

    print(f"--- Survivor Signal Processed! Logging Detection ID {log_entry['id']} at {timestamp_str} ---")
    state["survivors_found"].append(log_entry)


# --- Flask API Endpoint (Remains the same) ---
app = Flask(__name__)
@app.route('/api/state', methods=['GET'])
def get_state():
    """API endpoint for the frontend to fetch the current OBSERVED rover state."""
    with state_lock:
        state_copy = copy.deepcopy(current_observed_state)
    # No internal flags to remove in this version
    return flask.jsonify(state_copy)

@app.route('/')
def index():
    return "Nova Explorer Backend (Monitoring Mode - Emitter Signal) is running."

# --- Main Execution (Remains the same) ---
if __name__ == '__main__':
    print("Starting Nova Explorer Backend (Monitoring Mode - Emitter Signal)...")
    print("Initializing monitor thread...")
    monitor_thread = threading.Thread(target=run_monitor_loop, daemon=True)
    monitor_thread.start()
    print(f"Starting Flask web server on http://0.0.0.0:5000 ...")
    # Make sure reloader is False when using threads/sockets
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

    # Cleanup attempt when Flask stops
    print("Flask server stopped.")
    monitor_thread_stop_event.set() # Signal the monitor thread to stop gracefully