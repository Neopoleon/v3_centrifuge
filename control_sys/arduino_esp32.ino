/***************************************************************
 *  PID-Controlled DC Motor RPM w/ Hall Effect Sensor (UART)
 *  Updated for ESP32 using LEDC for PWM control.
 *
 *  Reads pulses from a Hall-effect sensor to measure
 *  centrifuge RPM with a tuned PID algorithm to adjust the PWM
 *  output to reach the desired RPM precisely.
 *
 *  Receives RPM and timer values via UART from Raspberry Pi.
 *  When timer expires, motor stops automatically.
 * 
 * Author: Jeff Liu
 ***************************************************************/

 const int hallPin = 2;    // Make sure this pin is appropriate for your ESP32 board
 const int pwmPin = 5;     // Make sure this pin is appropriate for your ESP32 board
 
 // LEDC configuration for ESP32 PWM
 const int pwmChannel = 0;
 const int pwmFreq = 5000;       // Frequency in Hz
 const int pwmResolution = 8;    // 8-bit resolution (0-255)
 
 volatile unsigned int pulseCount = 0;
 unsigned long lastTime = 0;
 float currentRPM = 0, desiredRPM = 0;
 float error = 0, integral = 0, previousError = 0;
 const float Kp = 0.065, Ki = 0.028, Kd = 0.023; // Tuned PID parameters
 const int magnets = 2;    // 2 RISING edges per revolution
 
 // Moving Average (MA) Buffer
 const int bufferSize = 5;
 float rpmBuffer[bufferSize] = {0};
 int bufferIndex = 0;
 int sampleCount = 0;
 
 // Timer Variables
 unsigned long startTime = 0;
 int timerDuration = 0;
 bool motorRunning = false;
 
 // Interrupt Service Routine (ISR)
 // Use IRAM_ATTR for faster ISR execution on ESP32
 void IRAM_ATTR countPulse() {
     pulseCount++;
 }
 
 void setup() {
     pinMode(hallPin, INPUT_PULLUP);
     // Initialize LEDC for PWM on ESP32
     ledcSetup(pwmChannel, pwmFreq, pwmResolution);
     ledcAttachPin(pwmPin, pwmChannel);
 
     Serial.begin(115200);
     Serial.println("Waiting for RPM and Timer values via UART...");
 
     // Attach interrupt on the hall sensor pin
     attachInterrupt(digitalPinToInterrupt(hallPin), countPulse, RISING);
 }
 
 void loop() {
     unsigned long now = millis();
 
     // Read new data from Raspberry Pi via UART
     if (Serial.available() > 0) {
         String receivedData = Serial.readStringUntil('\n');
         receivedData.trim();
         int commaIndex = receivedData.indexOf(',');
 
         if (commaIndex != -1) {
             desiredRPM = receivedData.substring(0, commaIndex).toFloat();
             timerDuration = receivedData.substring(commaIndex + 1).toInt();
 
             Serial.println("ACK");  // Acknowledge receipt to Raspberry Pi
 
             if (desiredRPM > 0 && timerDuration > 0) {
                 motorRunning = true;
                 startTime = millis();
                 Serial.print("New desired RPM: ");
                 Serial.print(desiredRPM);
                 Serial.print(" | Timer: ");
                 Serial.print(timerDuration);
                 Serial.println(" seconds.");
             }
         }
     }
 
     // If motor is running, perform PID control
     if (motorRunning) {
         if (now - lastTime >= 100) {  // Update every 100ms
             unsigned long elapsed = now - lastTime;
 
             noInterrupts();
             unsigned int pulses = pulseCount;
             pulseCount = 0;
             interrupts();
 
             currentRPM = (pulses / (float)magnets) * (60000.0 / elapsed);
             lastTime = now;
 
             // Moving Average Calculation
             rpmBuffer[bufferIndex] = currentRPM;
             bufferIndex = (bufferIndex + 1) % bufferSize;
             if (sampleCount < bufferSize) sampleCount++;
 
             float sum = 0;
             for (int i = 0; i < sampleCount; i++) {
                 sum += rpmBuffer[i];
             }
             float movingAverageRPM = sum / sampleCount;
 
             // PID Control Calculation
             float dt = elapsed / 1000.0;
             error = desiredRPM - movingAverageRPM;
             integral += error * dt;
             float derivative = (error - previousError) / dt;
             previousError = error;
 
             int pwmOutput = constrain((int)(Kp * error + Ki * integral + Kd * derivative), 0, 255);
             // Write PWM output using LEDC
             ledcWrite(pwmChannel, pwmOutput);
 
             // Print status
             Serial.print("RPM: ");
             Serial.print(currentRPM, 2);
             Serial.print("   MA: ");
             Serial.print(movingAverageRPM, 2);
             Serial.print("   Set: ");
             Serial.print(desiredRPM, 2);
             Serial.print("   PWM: ");
             Serial.println(pwmOutput);
         }
 
         // Check if timer has elapsed
         if ((millis() - startTime) >= (timerDuration * 1000)) {
             motorRunning = false;
             // Stop the motor
             ledcWrite(pwmChannel, 0);
             Serial.println("Complete");  // Notify Raspberry Pi
         }
     }
 }
 