# navigator.py (Challenge 1 Adaptation - No GPS)

import random

class Navigator:
    """Makes navigation decisions based on sensor data, without GPS."""

    def __init__(self):
        self.current_state = "exploring" # exploring, avoiding, wall_following
        self.avoidance_turn_direction = "left" # or "right"
        self.last_front_distance = 999.0
        print("Navigator (No GPS) initialized.")

    def decide_next_action(self, current_state):
        """
        Determines the next action based ONLY on sensor data and orientation.

        Args:
            current_state (dict): The rover's state dictionary.
                                  Expects state['sensors']['ultrasonic_front'], etc.

        Returns:
            str: Action command ("forward", "backward", "turn_left", "turn_right", "stop").
        """
        sensors = current_state.get("sensors", {})
        front_dist = sensors.get("ultrasonic_front", 999.0)
        left_dist = sensors.get("ultrasonic_left", 999.0)
        right_dist = sensors.get("ultrasonic_right", 999.0)

        # --- Constants (TUNE THESE CAREFULLY!) ---
        # Use the same threshold as the controller's override or slightly larger
        OBSTACLE_STOP_THRESHOLD = 0.35 # Stop/Turn sharply if closer than this
        OBSTACLE_SLOW_THRESHOLD = 0.6 # Maybe slow down if closer than this? (Optional)
        # Wall following requires side sensors
        WALL_FOLLOW_TARGET = 0.4
        WALL_FOLLOW_THRESHOLD_NEAR = 0.3
        WALL_FOLLOW_THRESHOLD_FAR = 0.5

        # --- State Machine Logic ---

        # 1. Obstacle Avoidance (Highest Priority)
        if front_dist < OBSTACLE_STOP_THRESHOLD:
            print(f"Navigator: Front Obstacle! ({front_dist:.2f}m < {OBSTACLE_STOP_THRESHOLD:.2f}m). Avoid.")
            self.current_state = "avoiding"
            # Decision: Turn away from obstacle. Check side sensors to help.
            if left_dist < right_dist: # More space on the right
                print("  -> Turning Right (more space)")
                self.avoidance_turn_direction = "right"
                return "turn_right"
            else: # More space on the left (or equal)
                print("  -> Turning Left (more space)")
                self.avoidance_turn_direction = "left"
                return "turn_left"
            # Alternative: Just always turn left/right or back up slightly first
            # return "backward" # Simple backup

        # If we were avoiding, maybe turn a bit more?
        # if self.current_state == "avoiding":
             # print("Navigator: Continuing avoidance turn.")
             # Check if front is clear again before exploring
             # if front_dist > OBSTACLE_SLOW_THRESHOLD:
             #      self.current_state = "exploring"
             #      print("  -> Front clear, resuming exploration.")
             #      return "forward"
             # else:
             #      print(f"  -> Front still not clear ({front_dist:.2f}m), continue turn {self.avoidance_turn_direction}")
             #      return f"turn_{self.avoidance_turn_direction}"


        # 2. Exploration / Wall Following (If Front is Clear)
        self.current_state = "exploring" # Default state if no obstacle
        print(f"Navigator: Path clear (Front: {front_dist:.2f}m). Exploring.")

        # --- Basic Random Exploration ---
        # (Disable or modify if using wall following)
        rand_choice = random.random()
        if rand_choice < 0.85: # High chance to go forward
            print("  -> Explore: forward")
            return "forward"
        elif rand_choice < 0.95:
             print("  -> Explore: turn_left")
             return "turn_left"
        else:
             print("  -> Explore: turn_right")
             return "turn_right"


        # --- Example: Basic Wall Following (Requires reliable side sensors) ---
        # Uncomment and adapt if needed. Choose Left or Right wall to follow.
        # Follow Left Wall Example:
        # print(f"Navigator: Trying Left Wall Following (L: {left_dist:.2f}m)")
        # if left_dist < WALL_FOLLOW_THRESHOLD_NEAR: # Too close
        #     print("  -> Wall Follow: Turn Right (too close)")
        #     return "turn_right"
        # elif left_dist > WALL_FOLLOW_THRESHOLD_FAR: # Too far
        #      print("  -> Wall Follow: Turn Left (too far)")
        #      return "turn_left"
        # else: # Good distance, go forward
        #      print("  -> Wall Follow: Forward")
        #      return "forward"


        # Fallback if no other decision made
        # print("Navigator: No specific action decided, stopping.")
        # return "stop"