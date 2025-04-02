import flask
from flask import Flask, jsonify # Use flask.jsonify for Flask >= 2.2
import threading
import time
import copy # To safely copy the state for the API response
from navigator import Navigator

# Import the API wrapper developed by Person 1
import api_wrapper

# --- Placeholder for Navigator Logic (Person 3) ---
# You would import the actual navigator module here
class MockNavigator:
    def decide_next_action(self, state):
        # Basic Placeholder: Avoid obstacles, otherwise move forward
        # Person 3 implements the real logic here!
        ultrasonic_dist = state.get("sensors", {}).get("ultrasonic_distance")
        print(f"Navigator received ultrasonic: {ultrasonic_dist}")
        if ultrasonic_dist is not None and ultrasonic_dist < 1.0: # Example threshold
            print("Navigator decision: Obstacle detected! Turn Left.")
            return "turn_left" # Action command
        else:
            print("Navigator decision: Path clear. Move Forward.")
            return "move_forward" # Action command

navigator = Navigator()
# -----------------------------------------------------

# --- Global Shared State & Control ---
# This dictionary will hold the latest known state of the rover.
# It will be updated by the background thread and read by the API endpoint.
current_rover_state = {
    "initialized": False,
    "session_id": None,
    "connection_status": "Disconnected", # Disconnected, Connecting, Connected, Comms Lost
    "last_updated": None,
    "rover_status": "Unknown", # e.g., Initializing, Exploring, Charging, Avoiding, Stopped
    "position": None,       # {x: float, y: float}
    "battery_level": None,  # float %
    "is_charging": False,   # boolean derived from battery logic
    "comms_ok": False,      # boolean derived from battery logic
    "sensors": {},          # Dict to hold sensor readings: ultrasonic_distance, ir_signal_strength, etc.
    "survivors_found": [],  # List of dicts e.g., {"position": {x: y:}, "timestamp": ..., "sensor_type": "RFID"}
    "path_history": [],     # List of positions to draw the path
    "last_error": None,
    "last_action_sent": None
}
# Lock to ensure thread-safe access to the shared state
state_lock = threading.Lock()

# --- Background Rover Control Logic Thread ---

def run_rover_control():
    """The main function running in the background thread."""
    global current_rover_state # Allow modification of the global state dict
    loop_interval = 2.0 # Seconds between loop cycles - ADJUST AS NEEDED

    print("Rover Control Thread: Starting...")

    # 1. Initialization Phase
    with state_lock:
        current_rover_state["connection_status"] = "Connecting"
        current_rover_state["rover_status"] = "Initializing"
    print("Rover Control Thread: Attempting to start API session...")
    session_id = api_wrapper.start_session()

    with state_lock:
        current_rover_state["last_updated"] = time.time()
        if session_id:
            current_rover_state["initialized"] = True
            current_rover_state["session_id"] = session_id
            current_rover_state["connection_status"] = "Connected"
            current_rover_state["comms_ok"] = True # Assume okay initially if session starts
            print("Rover Control Thread: Session started.")
        else:
            current_rover_state["connection_status"] = "Connection Failed"
            current_rover_state["last_error"] = "Failed to start API session."
            print("Rover Control Thread: CRITICAL - Failed to start session. Thread terminating.")
            return # Cannot proceed without a session

    # 2. Main Sense -> Think -> Act Loop
    while True:
        try:
            start_time = time.time()
            api_data = None # Reset api_data each loop

            # --- Acquire Lock to Safely Read and Update State ---
            with state_lock:
                # Make a local copy of critical state needed for decisions outside lock if necessary
                local_comms_ok = current_rover_state["comms_ok"]
                local_is_charging = current_rover_state["is_charging"]
                last_known_battery = current_rover_state["battery_level"]

            # --- Sense Phase (Conditional API Call) ---
            if local_comms_ok:
                print("Rover Control Thread: Attempting to get data...")
                # Choose which API call gives the best data or call both if needed
                api_data = api_wrapper.get_rover_status() # Or get_sensor_data()
                current_time = time.time()

                with state_lock:
                    current_rover_state["last_updated"] = current_time
                    if api_data:
                         # ** Person 2's logic to update state from API data **
                        # This should be a separate function for clarity
                        update_rover_state_based_on_data(api_data)
                        # Add current position to path history (limit size if needed)
                        if current_rover_state["position"]:
                             current_rover_state["path_history"].append(current_rover_state["position"])
                             if len(current_rover_state["path_history"]) > 200: # Limit history length
                                 current_rover_state["path_history"].pop(0)
                    else:
                        print("Rover Control Thread: Failed to get data from API.")
                        current_rover_state["connection_status"] = "API Error"
                        # Decide if this implies comms lost based on battery rule, handled below
            else:
                # Comms are flagged as down, possibly due to low battery
                print(f"Rover Control Thread: Comms Lost / Waiting for reconnect (Last Battery: {last_known_battery}%)...")
                with state_lock:
                    current_rover_state["rover_status"] = "Comms Lost"
                # Periodically try to fetch data to see if comms are back
                time.sleep(15) # Wait longer before retrying
                api_data = api_wrapper.get_rover_status() # Try reconnecting
                current_time = time.time()
                with state_lock:
                    current_rover_state["last_updated"] = current_time
                    if api_data:
                         print("Rover Control Thread: RECONNECTED!")
                         current_rover_state["connection_status"] = "Connected"
                         current_rover_state["comms_ok"] = True # We got data!
                         # Update state fully now that we are back online
                         update_rover_state_based_on_data(api_data)
                    else:
                         # Still offline
                         print("Rover Control Thread: Reconnect attempt failed.")
                         continue # Skip rest of loop, try again after sleep


            # --- Think Phase (State & Logic Updates within Lock) ---
            next_action = "none" # Default action is do nothing specific
            perform_action = False # Flag to check if rover should execute a command

            with state_lock:
                 # ** Person 2's Power Management Logic **
                 # This should be a function call
                handle_power_logic(current_rover_state)
                # Now update local copies based on the power logic results
                local_comms_ok = current_rover_state["comms_ok"]
                local_is_charging = current_rover_state["is_charging"]

                if local_is_charging:
                    current_rover_state["rover_status"] = "Charging"
                    print("Rover Control Thread: Rover is charging, no movement allowed.")
                    # Ensure rover is stopped if charging state just started
                    # Consider calling api_wrapper.stop_rover() here if needed, requires careful state handling
                elif not local_comms_ok:
                    # Already handled above, just update status message
                    current_rover_state["rover_status"] = "Comms Lost"
                    print("Rover Control Thread: Comms still lost based on battery state.")
                else:
                     # Rover is OK to move (not charging, comms OK)
                     current_rover_state["rover_status"] = "Thinking" # Temporarily

                     # ** Person 3's Navigation & Decision Logic **
                     # Requires the current state
                     navigator_input_state = copy.deepcopy(current_rover_state) # Give navigator a safe copy
                     # --- Release lock briefly if navigator is slow? Careful ---
                     # state_lock.release()
                     action_command = navigator.decide_next_action(navigator_input_state)
                     # state_lock.acquire() # Re-acquire if released
                     # ---

                     # ** Person 2's Survivor Detection Logging **
                     # Based on sensor data check (could be part of navigator decision too)
                     if check_for_survivor_trigger(current_rover_state["sensors"]):
                          log_survivor_detection(current_rover_state)
                          # Maybe modify action? e.g., pause briefly
                          # action_command = "stop" # Example
                     else:
                     # Rover is OK to move
                          current_rover_state["rover_status"] = "Thinking"

                     # Check and Log Survivors FIRST, based on latest sensor data
                          log_survivor_detection(current_rover_state) # <-- CALL IT HERE

                     # Decide navigation action
                          navigator_input_state = copy.deepcopy(current_rover_state)
                          action_command = navigator.decide_next_action(navigator_input_state)

                     # [...] rest of the logic

                     # Prepare action for execution
                     if action_command in ["forward", "backward", "left", "right", "stop", "deploy_aid"]: # Check valid actions
                        next_action = action_command
                        perform_action = True
                        current_rover_state["rover_status"] = f"Executing: {next_action}"
                     else:
                        current_rover_state["rover_status"] = "Idle / Exploring" # If no specific command

            # --- Act Phase (API Calls - Outside Lock) ---
            if perform_action and next_action != "none":
                success = False
                print(f"Rover Control Thread: Sending Action - {next_action}")
                if next_action == "stop":
                    success = api_wrapper.stop_rover()
                elif next_action == "deploy_aid":
                     # Check if survivor is actually detected here? Maybe UI triggers this?
                     # Be very careful with the assumed endpoint.
                     success = api_wrapper.deploy_aid()
                elif next_action in ["forward", "backward", "left", "right"]:
                    success = api_wrapper.move_rover(next_action)

                # Update state with action outcome
                with state_lock:
                    current_rover_state["last_action_sent"] = {"action": next_action, "success": success, "timestamp": time.time()}
                if not success:
                    print(f"Rover Control Thread: Failed to send action {next_action}")
                    # Implement retry logic? Or just let next loop decide?

            # --- Loop Delay ---
            elapsed_time = time.time() - start_time
            sleep_time = max(0, loop_interval - elapsed_time)
            print(f"Rover Control Thread: Loop End. Elapsed: {elapsed_time:.2f}s, Sleeping: {sleep_time:.2f}s")
            time.sleep(sleep_time)

        except Exception as e:
            # Catch unexpected errors in the loop
            print(f"!!! CRITICAL ERROR in rover control loop: {e} !!!")
            # Log the error state
            with state_lock:
                current_rover_state["last_error"] = f"Loop Crash: {e}"
                current_rover_state["rover_status"] = "CRITICAL ERROR"
            # Consider stopping the thread or trying to recover? For robustness, maybe just log and retry.
            time.sleep(5) # Wait longer after a major error


def update_rover_state_based_on_data(api_data):
    """Updates the current_rover_state dict using data from the API.
       IMPORTANT: This function assumes the state_lock is ALREADY HELD
                  by the calling code (the main loop).
    """
    global current_rover_state # We need this to modify the global dictionary

    if not api_data:
        print("Update State Error: No api_data received.")
        return # Do nothing if no data came back

    print(f"Updating state with data: {api_data}") # Useful for debugging

    # --- Update Battery ---
    # Use .get() to safely access keys that might be missing, providing a default.
    # Keep the previous value if the key is missing in the new data.
    new_battery = api_data.get("battery_level", current_rover_state["battery_level"])
    if new_battery is not None:
        current_rover_state["battery_level"] = float(new_battery) # Ensure it's a number

    # --- Update Position ---
    # Position is usually a nested dictionary {'x': value, 'y': value}
    new_position = api_data.get("position") # Get the nested dict
    if isinstance(new_position, dict) and 'x' in new_position and 'y' in new_position:
        # Basic check if it looks like a valid position dict
        current_rover_state["position"] = {
            "x": float(new_position['x']),
            "y": float(new_position['y'])
        }
        print(f"  Updated position to: {current_rover_state['position']}")
    else:
         # Keep old position if new one is invalid or missing
        print(f"  Position data missing or invalid in API response: {new_position}")

    # --- Update Sensor Readings (Store them together) ---
    # We put sensors in a sub-dictionary for organization
    sensors = current_rover_state["sensors"] # Get the existing sensors dict

    new_ultrasonic = api_data.get("ultrasonic_distance", sensors.get("ultrasonic_distance"))
    if new_ultrasonic is not None:
        sensors["ultrasonic_distance"] = float(new_ultrasonic)

    new_ir_signal = api_data.get("ir_signal_strength", sensors.get("ir_signal_strength"))
    if new_ir_signal is not None:
        sensors["ir_signal_strength"] = float(new_ir_signal)

    # RFID is usually boolean
    new_rfid = api_data.get("rfid_detected", sensors.get("rfid_detected"))
    if new_rfid is not None: # Check if key exists
        sensors["rfid_detected"] = bool(new_rfid) # Ensure it's True or False

    # Accelerometer is often a nested dictionary
    new_accelerometer = api_data.get("accelerometer")
    if isinstance(new_accelerometer, dict) and all(k in new_accelerometer for k in ('x', 'y', 'z')):
        sensors["accelerometer"] = {
            "x": float(new_accelerometer['x']),
            "y": float(new_accelerometer['y']),
            "z": float(new_accelerometer['z'])
        }
    else:
        print(f"  Accelerometer data missing or invalid: {new_accelerometer}")

    # Update the main state dictionary with the modified sensors sub-dictionary
    current_rover_state["sensors"] = sensors

    print("State update complete.")
    # Note: We DO NOT update is_charging or comms_ok here.
    # That's handled separately by handle_power_logic.
def handle_power_logic(state):
    """
    Applies the power rules based on battery level.
    Modifies 'is_charging' and 'comms_ok' flags in the provided 'state' dict.
    IMPORTANT: This function assumes the state_lock is ALREADY HELD
               by the calling code (the main loop).
    """
    battery = state.get("battery_level")

    # --- Handle case where battery level is unknown ---
    if battery is None:
        print("Power Logic Warning: Battery level unknown. Cannot reliably update charging/comms status.")
        # If comms were previously lost, keep them lost until battery level confirms >= 10
        if state.get("comms_ok") is False:
            print("  Keeping comms_ok = False due to previous state.")
            pass # No change needed
        else:
             # What to do if battery unknown and comms were previously ok?
             # Safer to assume okay initially, but requires valid first reading.
             # For now, make no change if battery is None. Needs valid first reading.
            print("  Making no change to comms_ok as battery level is None.")

        # Can't determine charging state without battery level
        print("  Making no change to is_charging as battery level is None.")
        return # Exit the function

    # --- Update Communication Status based on Battery ---
    # Store previous comms status to detect changes
    previous_comms_ok = state.get("comms_ok", True) # Assume True if key never existed before

    if battery < 10.0:
        state["comms_ok"] = False
        if previous_comms_ok: # Only print if changed
            print(f"Power Logic: Battery {battery:.1f}% < 10%. Setting Comms LOST.")
    else: # battery >= 10.0
        state["comms_ok"] = True
        if not previous_comms_ok: # Only print if changed from False to True
            print(f"Power Logic: Battery {battery:.1f}% >= 10%. Setting Comms OK.")

    # --- Update Charging Status based on Battery ---
    current_charging = state.get("is_charging", False) # Get current charging state

    new_charging_state = current_charging # Assume no change initially

    # Rule: Start charging if not already charging and battery <= 5%
    if not current_charging and battery <= 5.0:
        new_charging_state = True
        print(f"Power Logic: Battery {battery:.1f}% <= 5%. Entering Charging state.")

    # Rule: Stop charging if currently charging and battery >= 80%
    elif current_charging and battery >= 80.0:
        new_charging_state = False
        print(f"Power Logic: Battery {battery:.1f}% >= 80%. Exiting Charging state.")

    # Apply the change (if any) to the state dictionary
    state["is_charging"] = new_charging_state

    # Optional: Print current charging status if unchanged but relevant
    # if current_charging and new_charging_state:
    #     print(f"Power Logic: Battery {battery:.1f}%. Remaining in Charging state.")
def check_for_survivor_trigger(sensors):
    """
    Checks sensor readings for conditions indicating a survivor/marker.

    Args:
        sensors (dict): The 'sensors' sub-dictionary from current_rover_state.

    Returns:
        tuple: (bool, str, float/None) indicating (triggered, sensor_type, signal_value)
               Returns (False, None, None) if no trigger.
    """
    rfid_detected = sensors.get("rfid_detected", False)
    ir_signal = sensors.get("ir_signal_strength")

    # --- Define Detection Criteria ---
    rfid_trigger = rfid_detected is True # Check boolean True explicitly
    ir_threshold = 75.0 # TUNE THIS VALUE based on testing
    ir_trigger = ir_signal is not None and ir_signal > ir_threshold

    if rfid_trigger:
        return (True, "RFID", None) # RFID doesn't usually have signal strength here
    elif ir_trigger:
        return (True, "IR", ir_signal)
    else:
        return (False, None, None)

def log_survivor_detection(state):
    """
    Logs a survivor detection event if triggered by sensors.
    Adds an entry to state['survivors_found'].
    IMPORTANT: This function assumes the state_lock is ALREADY HELD.
    """
    sensors = state.get("sensors", {})
    position = state.get("position")

    triggered, sensor_type, signal_value = check_for_survivor_trigger(sensors)

    if triggered and position:
        now = time.time() # Use timestamp from acquisition time? Or log time?
        timestamp_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))

        log_entry = {
            "id": len(state["survivors_found"]) + 1, # Simple incrementing ID
            "position": copy.deepcopy(position),
            "timestamp": timestamp_str,
            "sensor_type": sensor_type,
            "signal_strength": signal_value if signal_value is not None else "N/A"
        }

        # --- Optional: Prevent rapid duplicate logging ---
        log_cooldown_seconds = 5 # Don't log same type within X seconds
        if state["survivors_found"]:
            last_log = state["survivors_found"][-1]
            time_since_last = now - time.mktime(time.strptime(last_log["timestamp"], '%Y-%m-%d %H:%M:%S')) # Need to convert back
            # Rough position check (optional, needs distance calculation)
            # distance_check_passed = calculate_distance(position, last_log["position"]) > 0.5
            if last_log["sensor_type"] == sensor_type and time_since_last < log_cooldown_seconds:
                 print(f"Skipping duplicate {sensor_type} log within {log_cooldown_seconds}s.")
                 return # Don't log

        print(f"Logging Survivor/Marker Detection: {log_entry}")
        state["survivors_found"].append(log_entry)

# --- Flask API Endpoint ---

app = Flask(__name__)

@app.route('/api/state', methods=['GET'])
def get_state():
    """API endpoint for the frontend to fetch the current rover state."""
    with state_lock:
        # Create a deep copy to safely return the state
        # without holding the lock during jsonify serialization
        state_copy = copy.deepcopy(current_rover_state)
    return flask.jsonify(state_copy)

@app.route('/')
def index():
    """Serves a simple message or could serve the main HTML file for Person 4."""
    return "Nova Explorer Backend is running. Access /api/state for rover status."

# --- Main Execution ---

if __name__ == '__main__':
    print("Starting Nova Explorer Backend...")

    # Start the background thread for rover control
    print("Initializing rover control thread...")
    control_thread = threading.Thread(target=run_rover_control, daemon=True)
    control_thread.start()

    # Start the Flask web server
    print("Starting Flask web server on http://0.0.0.0:5000 ...")
    # Use debug=False when running with background threads typically
    # Use host='0.0.0.0' to make accessible on your network (use localhost or 127.0.0.1 for local only)
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    # use_reloader=False is important when running threads manually like this