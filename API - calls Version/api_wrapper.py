import requests
import time
import json

# --- Configuration ---
API_BASE_URL = "https://roverdata2-production.up.railway.app"
DEFAULT_TIMEOUT_GET = 10  # seconds for GET requests (fetching data)
DEFAULT_TIMEOUT_POST = 15 # seconds for POST requests (sending commands)

# --- Module State ---
_session_id = None # Stores the active session ID

# --- Helper Function for Error Handling ---
def _handle_api_error(error_prefix, exception, response=None):
    """Consistently formats and prints API errors."""
    error_message = f"API Error ({error_prefix}): {exception}"
    if isinstance(exception, requests.exceptions.Timeout):
        error_message = f"API Error ({error_prefix}): Request timed out after {getattr(exception.request, 'timeout', 'N/A')} seconds."
    elif isinstance(exception, requests.exceptions.HTTPError):
        error_message = f"API Error ({error_prefix}): HTTP error - {exception.response.status_code} {exception.response.reason}"
        try:
            # Try to get detailed validation error from FastAPI 422 response
            error_detail = response.json()
            error_message += f"\n   Details: {json.dumps(error_detail)}"
        except json.JSONDecodeError:
            # Fallback if response is not JSON or other HTTP error
             error_message += f"\n   Response: {response.text[:200]}..." # Show beginning of text
        except Exception:
             error_message += f"\n   Response: {response.text[:200]}..." # Show beginning of text

    elif isinstance(exception, json.JSONDecodeError):
        error_message = f"API Error ({error_prefix}): Failed to decode JSON response - {exception}"
        if response:
            error_message += f"\n   Received text: {response.text[:200]}..."

    elif isinstance(exception, requests.exceptions.ConnectionError):
         error_message = f"API Error ({error_prefix}): Connection error - {exception}"

    elif isinstance(exception, requests.exceptions.RequestException):
         error_message = f"API Error ({error_prefix}): An unexpected requests error occurred - {exception}"

    print(error_message)


# --- Core API Functions ---

def start_session():
    """
    Starts a new API session and stores the session ID.
    Corresponds to: POST /api/session/start
    """
    global _session_id
    _session_id = None
    url = f"{API_BASE_URL}/api/session/start"
    print(f"Attempting: POST {url}")

    try:
        response = requests.post(url, timeout=DEFAULT_TIMEOUT_POST)
        response.raise_for_status() # Check for 4xx/5xx errors

        data = response.json()
        session_id_from_response = data.get("session_id") # Expecting {"session_id": "...", "message": "..."}

        if session_id_from_response:
            _session_id = session_id_from_response
            print(f"Session started successfully. Session ID: {_session_id}")
            return _session_id
        else:
            print("Error: 'session_id' not found in start_session response.")
            print(f"Received data: {data}")
            return None

    except Exception as e:
        _handle_api_error("start_session", e, getattr(e, 'response', None))
        return None

def get_rover_status():
    """
    Fetches the current status of the rover.
    Corresponds to: GET /api/rover/status
    """
    if not _session_id:
        print("Error (get_rover_status): Session not started.")
        return None

    url = f"{API_BASE_URL}/api/rover/status"
    params = {"session_id": _session_id} # Parameters are query params
    print(f"Attempting: GET {url} with params {params}")

    try:
        response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT_GET)
        response.raise_for_status()
        data = response.json()
        return data

    except Exception as e:
        _handle_api_error("get_rover_status", e, getattr(e, 'response', None))
        return None

def get_sensor_data():
    """
    Fetches detailed sensor data for the rover.
    Corresponds to: GET /api/rover/sensor-data
    """
    if not _session_id:
        print("Error (get_sensor_data): Session not started.")
        return None

    url = f"{API_BASE_URL}/api/rover/sensor-data"
    params = {"session_id": _session_id} # Parameters are query params
    print(f"Attempting: GET {url} with params {params}")

    try:
        response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT_GET)
        response.raise_for_status()
        data = response.json()
        return data

    except Exception as e:
        _handle_api_error("get_sensor_data", e, getattr(e, 'response', None))
        return None


def move_rover(direction):
    """
    Sends a command to move the rover.
    Corresponds to: POST /api/rover/move
    """
    if not _session_id:
        print(f"Error (move_rover {direction}): Session not started.")
        return False

    url = f"{API_BASE_URL}/api/rover/move"
    params = {"session_id": _session_id, "direction": direction} # Both are query params
    print(f"Attempting: POST {url} with params {params}")

    try:
        response = requests.post(url, params=params, timeout=DEFAULT_TIMEOUT_POST)
        response.raise_for_status()
        print(f"API Command 'Move {direction}' acknowledged by server.")
        # Optional: check response content if API provides meaningful confirmation
        # print(f"Move Response: {response.text}")
        return True

    except Exception as e:
        _handle_api_error(f"move_rover({direction})", e, getattr(e, 'response', None))
        return False

def stop_rover():
    """
    Sends a command to stop the rover.
    Corresponds to: POST /api/rover/stop
    """
    if not _session_id:
        print("Error (stop_rover): Session not started.")
        return False

    url = f"{API_BASE_URL}/api/rover/stop"
    params = {"session_id": _session_id} # Query param
    print(f"Attempting: POST {url} with params {params}")

    try:
        response = requests.post(url, params=params, timeout=DEFAULT_TIMEOUT_POST)
        response.raise_for_status()
        print("API Command 'Stop' acknowledged by server.")
        # Optional: check response content
        # print(f"Stop Response: {response.text}")
        return True

    except Exception as e:
        _handle_api_error("stop_rover", e, getattr(e, 'response', None))
        return False

def charge_rover():
    """
    Sends a command to initiate charging (based on observed endpoint).
    NOTE: The simulation rules previously suggested automatic charging.
          The role of this endpoint needs clarification / testing.
    Corresponds to: POST /api/rover/charge
    """
    if not _session_id:
        print("Error (charge_rover): Session not started.")
        return False

    url = f"{API_BASE_URL}/api/rover/charge"
    params = {"session_id": _session_id} # Query param
    print(f"Attempting: POST {url} with params {params}")

    try:
        response = requests.post(url, params=params, timeout=DEFAULT_TIMEOUT_POST)
        response.raise_for_status()
        print("API Command 'Charge' acknowledged by server.")
        # Optional: check response content
        # print(f"Charge Response: {response.text}")
        return True

    except Exception as e:
        _handle_api_error("charge_rover", e, getattr(e, 'response', None))
        return False


def deploy_aid():
    """
    *** WARNING: Endpoint NOT CONFIRMED in provided FastAPI docs. ***
    Sends a command to deploy aid. Assumes endpoint '/api/rover/deploy_aid'.

    Returns:
        bool: True if the command was likely sent successfully, False otherwise.
    """
    print("\n*** WARNING: Calling deploy_aid() with ASSUMED endpoint /api/rover/deploy_aid ***")
    print("*** Verify this endpoint exists in the official API documentation! ***\n")

    if not _session_id:
        print("Error (deploy_aid): Session not started.")
        return False

    endpoint = "/api/rover/deploy_aid" # <--- This is the assumption
    url = f"{API_BASE_URL}{endpoint}"
    params = {"session_id": _session_id} # Assume query param for consistency
    print(f"Attempting: POST {url} with params {params} (ASSUMED ENDPOINT)")

    try:
        response = requests.post(url, params=params, timeout=DEFAULT_TIMEOUT_POST)
        response.raise_for_status()

        print("API Command 'Deploy Aid' acknowledged by server (using assumed endpoint).")
        return True

    except Exception as e:
         # Handle potential 404 specifically for this assumed endpoint
        if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 404:
             print(f"\n>>> CRITICAL API Error (deploy_aid): Received 404 Not Found.")
             print(f">>> The assumed endpoint '{endpoint}' almost certainly DOES NOT EXIST.")
             print(f">>> Check the official API documentation!\n")
        else:
             _handle_api_error("deploy_aid", e, getattr(e, 'response', None))
        return False


# --- Example Usage (for testing this module directly) ---
if __name__ == "__main__":
    print("--- Testing API Wrapper ---")
    if start_session():
        print("\n--- Getting initial data (Status) ---")
        status_data = get_rover_status()
        if status_data:
            print(f"  Status Battery: {status_data.get('battery_level', 'N/A')}%")
            print(f"  Status Position: {status_data.get('position', 'N/A')}")
        else:
            print("  Failed to get status data.")

        print("\n--- Getting initial data (Sensor Data) ---")
        sensor_data = get_sensor_data()
        if sensor_data:
             # Note: Adjust keys based on actual sensor_data structure
            print(f"  Sensor Battery: {sensor_data.get('battery_level', 'N/A')}%")
            print(f"  Sensor Position: {sensor_data.get('position', 'N/A')}")
            print(f"  Sensor Ultrasonic: {sensor_data.get('ultrasonic_distance', 'N/A')}")
        else:
             print("  Failed to get sensor data.")

        print("\n--- Testing movement ---")
        if move_rover("forward"):
            print("  Sleeping for 2s...")
            time.sleep(2)

        print("\n--- Testing stop ---")
        if stop_rover():
            print("  Sleeping for 1s...")
            time.sleep(1)

        print("\n--- Testing manual charge command ---")
        if charge_rover():
            print("  Sleeping for 1s...")
            time.sleep(1)
        else:
             print(" Charge command failed.")

        print("\n--- Testing Deploy Aid (ASSUMED ENDPOINT) ---")
        if deploy_aid():
           print("  Sleeping for 1s...")
           time.sleep(1)

        print("\n--- Getting final status data ---")
        final_data = get_rover_status()
        if final_data:
            print(f"  Final Battery: {final_data.get('battery_level', 'N/A')}%")
            print(f"  Final Position: {final_data.get('position', 'N/A')}")
        else:
            print("  Failed to get final data.")

    else:
        print("Failed to start session. Cannot run further tests.")

    print("\n--- Test Complete ---")