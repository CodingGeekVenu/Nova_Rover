/*
 * Description: BoeBot controller - autonomous navigation, obstacle avoidance,
 *              detects specific obstacles as "survivors" via recognition,
 *              emits a signal on survivor detection, stops on tilt.
 *              Implements slightly smarter turning.
 */

 #include <webots/robot.h>
 #include <webots/motor.h>
 #include <webots/distance_sensor.h>
 #include <webots/accelerometer.h>
 #include <webots/emitter.h> // <-- Added Emitter
 #include <webots/supervisor.h> // <-- Added Supervisor (to get node info)
 #include <webots/led.h>
 // #include <webots/touch_sensor.h> // Optional whiskers
 
 #include <math.h>
 #include <stdio.h>
 #include <stdlib.h>
 #include <string.h>
 
 // --- Time Step ---
 #define TIME_STEP 64
 
 // --- Movement Speeds ---
 #define FORWARD_SPEED 5.0
 #define TURN_SPEED 4.0
 #define BACKUP_SPEED 3.0 // Optional
 
 // --- Behavior Durations ---
 #define AID_DEPLOY_DURATION 50 // Pause duration after finding survivor
 // #define BACKUP_DURATION 8 // Optional
 
 // --- TUNABLE SENSOR THRESHOLDS ---
 #define OBSTACLE_DISTANCE_THRESHOLD 0.3 // Avoid if DistanceSensor value is LESS than this (meters)
 #define TILT_THRESHOLD 3.5
 #define SURVIVOR_DETECTION_RANGE 0.4 // Must recognize survivor AND be closer than this (meters)
 
 // --- Names & Communication ---
 #define SURVIVOR_OBJECT_NAME "SurvivorObstacle" // *** The 'name' field of survivor objects in Webots ***
 #define EMITTER_NAME "status_emitter"        // *** 'name' of the Emitter device on the BoeBot ***
 #define EMITTER_CHANNEL 1                    // Channel for communication (must match Supervisor Receiver)
 #define SURVIVOR_MESSAGE "SURVIVOR_FOUND"    // Message sent when survivor found
 
 // --- Robot States ---
 typedef enum {
   SEARCHING,
   AVOIDING_OBSTACLE,
   DEPLOYING_AID,
   ROBOT_TILTED
   // BACKING_UP // Optional
 } RobotState;
 
 // --- Global state variables ---
 static int aid_deploy_counter = 0;
 // static int backup_counter = 0; // Optional
 
 // Function to check if a node is a survivor based on its name
 bool is_survivor(WbNodeRef node) {
   if (!node) return false;
   const char *node_name = wb_supervisor_node_get_name(node); // Use supervisor function to get name field value
   if (node_name && strcmp(node_name, SURVIVOR_OBJECT_NAME) == 0) {
     return true;
   }
   // Optional: Also check model name if needed
   // const char *model_name = wb_supervisor_node_get_model_name(node);
   // if (model_name && strcmp(model_name, "SurvivorProtoName") == 0) return true;
   return false;
 }
 
 
 int main() {
   wb_robot_init();
 
   // --- Get Device Handles ---
   WbDeviceTag left_motor = wb_robot_get_device("left wheel motor");
   WbDeviceTag right_motor = wb_robot_get_device("right wheel motor");
   // Use multiple sensors for better avoidance
   WbDeviceTag ds_front = wb_robot_get_device("ds_front");
   WbDeviceTag ds_left = wb_robot_get_device("ds_left");   // NEEDED for smarter turning
   WbDeviceTag ds_right = wb_robot_get_device("ds_right"); // NEEDED for smarter turning
   WbDeviceTag accelerometer = wb_robot_get_device("accelerometer");
   WbDeviceTag emitter = wb_robot_get_device(EMITTER_NAME); // Get the emitter
   WbDeviceTag left_led = wb_robot_get_device("left_led");
   WbDeviceTag right_led = wb_robot_get_device("right_led");
   // WbDeviceTag left_whisker = wb_robot_get_device("left_whisker"); // Optional
   // WbDeviceTag right_whisker = wb_robot_get_device("right_whisker"); // Optional
 
   // --- Enable Devices & Setup ---
   if (!left_motor || !right_motor) { /* ... Error handling ... */ return 1; }
   wb_motor_set_position(left_motor, INFINITY);
   wb_motor_set_position(right_motor, INFINITY);
   wb_motor_set_velocity(left_motor, 0.0);
   wb_motor_set_velocity(right_motor, 0.0);
 
   WbDeviceTag distance_sensors[] = {ds_front, ds_left, ds_right};
   for (int i = 0; i < 3; ++i) {
       if (distance_sensors[i]) {
           wb_distance_sensor_enable(distance_sensors[i], TIME_STEP);
           // Enable recognition on distance sensors
           wb_distance_sensor_recognition_enable(distance_sensors[i], TIME_STEP);
       } else {
           printf("Warning: Distance sensor %d not found!\n", i);
       }
   }
 
   if (accelerometer) wb_accelerometer_enable(accelerometer, TIME_STEP); else printf("Warning: Accelerometer not found.\n");
   if (!emitter) printf("ERROR: Emitter '%s' not found! Cannot send survivor signal.\n", EMITTER_NAME);
   else wb_emitter_set_channel(emitter, EMITTER_CHANNEL); // Set communication channel
 
 
   printf("BoeBot Survivor Emitter Controller Initialized.\n");
   RobotState current_state = SEARCHING;
 
   // --- Main Control Loop ---
   while (wb_robot_step(TIME_STEP) != -1) {
     double left_speed = 0.0;
     double right_speed = 0.0;
 
     // --- 1. Read Sensor Values & Check for Survivors ---
     double ds_values[3] = {999.0, 999.0, 999.0}; // Front, Left, Right
     bool survivor_detected_this_step = false;
 
     for (int i = 0; i < 3; ++i) {
         if (distance_sensors[i]) {
             ds_values[i] = wb_distance_sensor_get_value(distance_sensors[i]);
             // Check recognized objects from this sensor
             int num_obj = wb_distance_sensor_recognition_get_number_of_objects(distance_sensors[i]);
             const WbRecognizedObject *objects = wb_distance_sensor_recognition_get_objects(distance_sensors[i]);
             for (int j = 0; j < num_obj; ++j) {
                 WbNodeRef recognized_node = objects[j].node;
                 // Use supervisor function to get name (requires supervisor=TRUE in Robot node)
                 // OR check model name if supervisor access isn't desired/possible from robot controller
                 if (is_survivor(recognized_node)) {
                      // Check if it's close enough based on the sensor reading
                     if (ds_values[i] < SURVIVOR_DETECTION_RANGE) {
                          survivor_detected_this_step = true;
                          printf("--- SURVIVOR DETECTED by sensor %d ---\n", i);
                          break; // Found one, no need to check others
                     }
                 }
             }
         }
         if (survivor_detected_this_step) break;
     }
 
     bool tilted = false;
     if (accelerometer) {
       const double *a = wb_accelerometer_get_values(accelerometer);
       if (fabs(a[0]) > TILT_THRESHOLD || fabs(a[1]) > TILT_THRESHOLD) tilted = true;
     }
 
     // --- 2. Determine Robot State ---
     RobotState next_state = current_state;
     bool actively_deploying_aid = false;
 
     if (aid_deploy_counter > 0) { // Timer logic
       aid_deploy_counter--;
       if (aid_deploy_counter == 0) printf(" Aid Deployment Finished.\n");
       else { next_state = DEPLOYING_AID; actively_deploying_aid = true; }
     }
 
     if (!actively_deploying_aid) { // Event triggers (only if not deploying aid)
       if (tilted) { // Priority 1: Tilt
         if (current_state != ROBOT_TILTED) printf("STATE CHANGE: Robot Tilted! Halting.\n");
         next_state = ROBOT_TILTED;
       }
       else if (survivor_detected_this_step) { // Priority 2: Survivor found
         if (current_state != DEPLOYING_AID) {
           printf("STATE CHANGE: Survivor Detected! Deploying Aid & Emitting Signal.\n");
           aid_deploy_counter = AID_DEPLOY_DURATION; // Start timer
           next_state = DEPLOYING_AID;
           // Send signal via emitter
           if (emitter) {
             wb_emitter_send(emitter, SURVIVOR_MESSAGE, strlen(SURVIVOR_MESSAGE) + 1);
             printf(" Emitter: Sent '%s'\n", SURVIVOR_MESSAGE);
           } else { printf(" Emitter: Error - cannot send signal.\n"); }
         }
       }
       // Priority 3: Obstacle detection (using front sensor primarily)
       else if (ds_values[0] < OBSTACLE_DISTANCE_THRESHOLD) {
         if (current_state != AVOIDING_OBSTACLE) printf("STATE CHANGE: Obstacle Detected (Front DS). Avoiding.\n");
         next_state = AVOIDING_OBSTACLE;
       }
       // Priority 4: Default - Clear path
       else {
         if (current_state != SEARCHING) printf("STATE CHANGE: Clear. Resuming Search.\n");
         next_state = SEARCHING;
       }
     }
     current_state = next_state;
 
     // --- 3. Execute Actions Based on State ---
     if(left_led) wb_led_set(left_led, 0); // Reset LEDs
     if(right_led) wb_led_set(right_led, 0);
 
     switch (current_state) {
       case ROBOT_TILTED:
         left_speed = 0.0; right_speed = 0.0;
         if(left_led) wb_led_set(left_led, 1); if(right_led) wb_led_set(right_led, 1); // Solid error LEDs
         break;
       case DEPLOYING_AID:
         left_speed = 0.0; right_speed = 0.0;
         if (aid_deploy_counter % 4 < 2) { // Blink both LEDs
              if(left_led) wb_led_set(left_led, 1); if(right_led) wb_led_set(right_led, 1);
         }
         break;
       case AVOIDING_OBSTACLE:
         // Smarter Turn: Turn away from the side with less space
         if (ds_values[1] < ds_values[2]) { // Left sensor closer or equal -> Turn Right
              left_speed = TURN_SPEED;
              right_speed = -TURN_SPEED;
              printf(" Avoiding: Turning Right (Left closer: %.2f < Right: %.2f)\n", ds_values[1], ds_values[2]);
         } else { // Right sensor closer -> Turn Left
              left_speed = -TURN_SPEED;
              right_speed = TURN_SPEED;
               printf(" Avoiding: Turning Left (Right closer: %.2f < Left: %.2f)\n", ds_values[2], ds_values[1]);
         }
         break;
       case SEARCHING:
       default:
         left_speed = FORWARD_SPEED; right_speed = FORWARD_SPEED;
         break;
     }
 
     // --- 4. Set Motor Velocities ---
     wb_motor_set_velocity(left_motor, left_speed);
     wb_motor_set_velocity(right_motor, right_speed);
 
     // --- 5. Periodic Debug Output ---
     static int debug_print_counter = 0;
     if (debug_print_counter++ % 8 == 0) {
          printf("S:%d Aid:%d | F:%.2f L:%.2f R:%.2f | Tilt:%d Surv:%d | Spd L:%.1f R:%.1f\n",
                current_state, aid_deploy_counter, ds_values[0], ds_values[1], ds_values[2],
                tilted, survivor_detected_this_step, left_speed, right_speed);
     }
   }
   wb_robot_cleanup();
   return 0;
 }