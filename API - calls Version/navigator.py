# navigator.py

import random

class Navigator:
    """Class to handle navigation decisions."""

    def __init__(self):
        # Initialize any state the navigator needs to keep track of
        # e.g., preferred direction, wall following state, visited map
        self.last_obstacle_state = False
        print("Navigator initialized.")

    def decide_next_action(self, current_state):
        """
        Determines the next action based on the rover's state.

        Args:
            current_state (dict): A copy of the rover's current state dictionary.

        Returns:
            str: The action command ("forward", "backward", "left", "right", "stop").
        """

        sensors = current_state.get("sensors", {})
        position = current_state.get("position")
        ultrasonic_dist = sensors.get("ultrasonic_distance")

        # --- 1. Obstacle Avoidance (Highest Priority) ---
        obstacle_threshold = 0.8 # meters - TUNE THIS VALUE!
        is_obstacle = ultrasonic_dist is not None and ultrasonic_dist < obstacle_threshold

        if is_obstacle:
            # Obstacle detected! Don't move forward.
            print(f"Navigator: Obstacle detected ({ultrasonic_dist:.2f}m < {obstacle_threshold}m)")
            self.last_obstacle_state = True
            # Simple strategy: Turn Left (could be random, or alternate)
            return "turn_left"
        # else:
            # Optional: If we JUST cleared an obstacle, maybe go forward briefly first
            # if self.last_obstacle_state:
            #     self.last_obstacle_state = False
            #     print("Navigator: Obstacle cleared, moving forward briefly.")
            #     return "forward"
            # self.last_obstacle_state = False


        # --- 2. Exploration Strategy (If no obstacle) ---
        # Basic Random Walk Strategy:
        # If path is clear, mostly go forward, sometimes turn randomly.
        print("Navigator: No immediate obstacle detected. Deciding exploration move.")

        # You can make this much smarter!
        # - Use position history (current_state['path_history'])
        # - Implement wall following using ultrasonic
        # - Implement grid mapping

        # Simple random choice:
        rand_choice = random.random() # Random float between 0.0 and 1.0
        if rand_choice < 0.75: # 75% chance to go forward
            print("  -> Explore: forward")
            return "forward"
        elif rand_choice < 0.90: # 15% chance to turn left
            print("  -> Explore: turn_left")
            return "turn_left"
        else: # 10% chance to turn right
            print("  -> Explore: turn_right")
            return "turn_right"

        # Default action if none chosen (shouldn't happen with above logic)
        # return "stop"