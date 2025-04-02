# webots_interface.py
import socket
import json
import time
import select # Used for non-blocking checks and timeouts on receive

# --- Configuration ---
# Default values, can be overridden when calling connect_to_webots if needed
DEFAULT_WEBOTS_HOST = 'localhost' # Assumes Webots controller is on the same machine
DEFAULT_WEBOTS_PORT = 10001       # Make sure this matches the port in boe_bot_controller.py
SOCKET_TIMEOUT = 5.0              # Seconds for send/receive operations (can be tuned)
CONNECT_TIMEOUT = 10.0            # Seconds to wait for the initial connection
BUFFER_SIZE = 4096                # Max bytes to receive in one go (adjust if needed)

# --- Module State ---
_socket = None          # Holds the active socket object
_is_connected = False   # Tracks if we believe the connection is active
_last_error = None      # Stores the last error message for debugging

# --- Helper Function for Error Handling ---
def _log_error(context, message):
    """Simple error logger that updates the module state."""
    global _last_error
    err_msg = f"Webots Interface Error ({context}): {message}"
    print(err_msg) # Log to console
    _last_error = err_msg # Store the last error

def get_last_error():
    """Returns the last recorded error message."""
    return _last_error

# --- Core Communication Functions ---

def connect_to_webots(host=DEFAULT_WEBOTS_HOST, port=DEFAULT_WEBOTS_PORT):
    """
    Establishes a TCP socket connection to the Webots controller's server.

    Args:
        host (str): The hostname or IP address of the machine running Webots.
        port (int): The port number the Webots controller is listening on.

    Returns:
        bool: True if connection was successful, False otherwise.
    """
    global _socket, _is_connected, _last_error
    if _is_connected:
        print("Webots Interface: Already connected.")
        return True

    _last_error = None # Clear previous error on new attempt
    print(f"Webots Interface: Attempting to connect to {host}:{port}...")
    try:
        # Create a TCP/IP socket
        _socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Set a timeout for the connection attempt itself
        _socket.settimeout(CONNECT_TIMEOUT)
        # Connect to the server
        _socket.connect((host, port))
        # Set a default timeout for subsequent send/receive operations
        _socket.settimeout(SOCKET_TIMEOUT)
        _is_connected = True
        print("Webots Interface: Connection successful.")
        return True
    except socket.timeout:
        _log_error("connect", f"Connection attempt timed out after {CONNECT_TIMEOUT}s")
        _socket = None
        _is_connected = False
        return False
    except socket.error as e:
        # Covers various connection issues like "Connection refused"
        _log_error("connect", f"Socket error - {e}")
        _socket = None
        _is_connected = False
        return False
    except Exception as e:
         # Catch any other unexpected errors during connection
         _log_error("connect", f"Unexpected error - {e}")
         _socket = None
         _is_connected = False
         return False

def disconnect():
    """Closes the socket connection gracefully."""
    global _socket, _is_connected, _last_error
    if _socket:
        print("Webots Interface: Disconnecting...")
        _last_error = None # Clear error on disconnect
        try:
            # Shut down reading/writing first (optional but good practice)
            _socket.shutdown(socket.SHUT_RDWR)
            _socket.close()
        except socket.error as e:
            # Handle potential errors during shutdown (e.g., already closed)
            _log_error("disconnect", f"Error closing socket - {e}")
        except Exception as e:
            _log_error("disconnect", f"Unexpected error during disconnect - {e}")
        finally:
             # Ensure state is updated even if close fails
             _socket = None
             _is_connected = False
             print("Webots Interface: Disconnected.")
    else:
         print("Webots Interface: Already disconnected.")


def is_connected():
    """
    Returns the current believed connection status.
    Note: This doesn't actively probe the connection unless send/receive fails.
    """
    return _is_connected

def _send_message(message_dict):
    """
    Internal helper to send a dictionary as a JSON string terminated by newline.

    Args:
        message_dict (dict): The dictionary to send.

    Returns:
        bool: True if sending was successful, False otherwise.
    """
    global _is_connected, _last_error
    if not _is_connected or not _socket:
        _log_error("send", "Not connected.")
        # If we try to send when not connected, ensure status is False
        _is_connected = False
        return False

    _last_error = None # Clear previous error on new attempt
    try:
        # Convert dictionary to JSON string
        message_json = json.dumps(message_dict)
        # Add the newline delimiter and encode to bytes
        message_bytes = (message_json + '\n').encode('utf-8')
        # Send all the bytes
        _socket.sendall(message_bytes)
        # print(f"DEBUG: Sent -> {message_json}") # Uncomment for debugging
        return True
    except socket.timeout:
        _log_error("send", f"Send operation timed out ({SOCKET_TIMEOUT}s)")
        # Assume connection is broken if send times out
        disconnect() # Close the faulty socket
        return False
    except socket.error as e:
        _log_error("send", f"Socket error - {e}")
        # Assume connection is broken on socket error
        disconnect()
        return False
    except Exception as e:
         _log_error("send", f"Unexpected error - {e}")
         disconnect()
         return False


def _receive_message():
    """
    Internal helper to receive data until a newline, decode JSON.
    Handles potential partial messages and timeouts.

    Returns:
        dict or None: The received dictionary if successful, None otherwise.
    """
    global _is_connected, _last_error
    if not _is_connected or not _socket:
        _log_error("receive", "Not connected.")
        return None

    _last_error = None # Clear previous error
    data_buffer = b""
    start_time = time.time()

    try:
        while True:
            # Check if data is available using select (avoids hard blocking indefinitely)
            # The last '0.1' is a short timeout for select itself
            ready_to_read, _, _ = select.select([_socket], [], [], 0.1)

            if ready_to_read:
                 # Data is available, receive it
                 chunk = _socket.recv(BUFFER_SIZE)
                 if not chunk:
                      # An empty chunk usually means the other side closed the connection
                      _log_error("receive", "Connection closed by Webots controller.")
                      disconnect()
                      return None

                 data_buffer += chunk

                 # Check if we have received the newline delimiter
                 if b'\n' in data_buffer:
                      # Split message at the first newline
                      message_bytes, rest = data_buffer.split(b'\n', 1)
                      # Keep the 'rest' for the next receive cycle if needed (though unlikely with sendall)
                      data_buffer = rest # Store any remaining data after the newline

                      message_str = message_bytes.decode('utf-8').strip()
                      # print(f"DEBUG: Received Raw -> {message_str}") # Debugging

                      if not message_str: # Handle empty lines if they occur
                          continue

                      try:
                         # Attempt to parse the JSON
                         message_dict = json.loads(message_str)
                         return message_dict # Success!
                      except json.JSONDecodeError as e:
                         _log_error("receive", f"JSON decode error - {e}. Received: '{message_str}'")
                         # Don't disconnect here, maybe it was just a bad message?
                         # Or maybe disconnect if errors persist? For now, just return None.
                         return None
                      except Exception as e:
                          _log_error("receive", f"Error decoding message - {e}")
                          return None

            # Check for overall timeout for the receive operation
            if time.time() - start_time > SOCKET_TIMEOUT:
                _log_error("receive", f"Receive operation timed out ({SOCKET_TIMEOUT}s waiting for newline). Buffer: '{data_buffer.decode('utf-8', errors='ignore')}'")
                # Consider the connection lost on timeout
                disconnect()
                return None

            # Optional: Tiny sleep if select returns empty frequently to prevent busy-waiting
            # time.sleep(0.001)

    except socket.timeout:
         # This might occur if the socket timeout is hit during recv, though select should prevent hard blocks
        _log_error("receive", f"Socket recv timed out ({SOCKET_TIMEOUT}s)")
        disconnect()
        return None
    except socket.error as e:
        _log_error("receive", f"Socket error - {e}")
        disconnect()
        return None
    except Exception as e:
         _log_error("receive", f"Unexpected error - {e}")
         disconnect()
         return None


# --- High-Level Interface Functions (Used by app.py) ---

def get_simulation_state():
    """
    Requests and retrieves the current state dictionary from the Webots simulation.

    Returns:
        dict or None: The state dictionary if successful, None otherwise.
    """
    # print("Webots Interface: Requesting simulation state...") # Can be verbose
    # Send the command to request state
    if not _send_message({"command": "get_state"}):
        # Error logged by _send_message
        _log_error("get_state", "Failed to send request.")
        return None

    # Wait for and receive the response
    state_data = _receive_message()
    if state_data:
        # print("Webots Interface: Received state data.") # Can be verbose
        # print(f"DEBUG: State Data -> {state_data}") # Debugging
        return state_data
    else:
        # Error logged by _receive_message or send failure
        _log_error("get_state", "Failed to receive valid state data.")
        return None

def send_move_command(direction):
    """
    Sends a move command (e.g., "forward", "turn_left") to the simulation.

    Args:
        direction (str): The direction command string.

    Returns:
        bool: True if the command was likely sent successfully, False otherwise.
              (Success only means sent, not necessarily executed by Webots yet).
    """
    # print(f"Webots Interface: Sending move command - {direction}") # Can be verbose
    command = {"command": "move", "direction": direction.lower()} # Ensure lowercase
    return _send_message(command) # Return True if send succeeds

def send_stop_command():
    """Sends a stop command to the simulation."""
    # print("Webots Interface: Sending stop command.") # Can be verbose
    command = {"command": "stop"}
    return _send_message(command)

def send_deploy_aid_command():
    """Sends a command to deploy aid (if implemented in Webots)."""
    # print("Webots Interface: Sending deploy_aid command.") # Can be verbose
    command = {"command": "deploy_aid"}
    return _send_message(command)

# --- Example Usage Block (Optional - for testing this module directly) ---
# if __name__ == "__main__":
#     print("--- Testing Webots Interface ---")
#     if connect_to_webots():
#         print("\n--- Getting initial state ---")
#         state = get_simulation_state()
#         if state:
#             print(f"  Initial State Received: {state}")
#         else:
#             print(f"  Failed to get initial state. Last Error: {get_last_error()}")

#         print("\n--- Testing movement ---")
#         if send_move_command("forward"):
#             print("  Move forward command sent. Sleeping...")
#             time.sleep(2) # Give Webots time to move
#         else:
#             print(f"  Failed to send move command. Last Error: {get_last_error()}")


#         print("\n--- Testing stop ---")
#         if send_stop_command():
#              print("  Stop command sent. Sleeping...")
#              time.sleep(1)
#         else:
#              print(f"  Failed to send stop command. Last Error: {get_last_error()}")


#         print("\n--- Getting final state ---")
#         final_state = get_simulation_state()
#         if final_state:
#             print(f"  Final State Received: {final_state}")
#         else:
#             print(f"  Failed to get final state. Last Error: {get_last_error()}")

#         disconnect()
#     else:
#         print(f"Failed to connect to Webots controller. Last Error: {get_last_error()}")

#     print("\n--- Test Complete ---")