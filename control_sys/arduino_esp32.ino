/***************************************************************
 *  Group: P4
 *  Group Members: Jeff Liu, Lucas Sosnick, Zach Lin
 *  Author: Jeff Liu
 *  Version: 1.6
 *  PID-Controlled DC Motor RPM w/ Hall Effect Sensor
 *
 *  Reads pulses from a Hall-effect sensor to measure
 *  centrifuge RPM with a tuned PID algo to adjust the PWM
 *  output to reach the desired RPM precisely
 *
 *  Note: user can input RPM via serial monitor or python terminal (range: 0 - 3000; 
 *  dependent on if using interface)
 *  When desired RPM set to 0, the motor stopped and PID vals are reset
 ***************************************************************/

 const int hallPin = 2;    
 const int pwmPin = 5; 
 
 volatile unsigned int pulseCount = 0;
 unsigned long lastTime = 0;
 float currentRPM = 0, desiredRPM = 0;
 float error = 0, integral = 0, previousError = 0;
 const float Kp = 0.058, Ki = 0.022, Kd = 0.021; // tuned params
 const int magnets = 1;    // 1 RISING edge per rev
 
 // MA buffer (per .5 sec)
 const int bufferSize = 5;
 float rpmBuffer[bufferSize] = {0};
 int bufferIndex = 0;
 int sampleCount = 0;
 
 void countPulse() {
   pulseCount++;
 }
 
 void setup() {
   pinMode(hallPin, INPUT_PULLUP);
   pinMode(pwmPin, OUTPUT);
   attachInterrupt(digitalPinToInterrupt(hallPin), countPulse, RISING); // enable interrupts
 
   Serial.begin(9600);
   Serial.println("Enter desired RPM (0 - 3000):");
 }
 
 void loop() {
   unsigned long now = millis();
   if (now - lastTime >= 100) {
     unsigned long elapsed = now - lastTime;
 
     // read and reset pulseCount
     noInterrupts(); // disable interrupts temperarily
     unsigned int pulses = pulseCount;
     pulseCount = 0;
     interrupts();
 
     // calculate real-time RPM
     currentRPM = (pulses / (float)magnets) * (60000.0 / elapsed);
     lastTime = now; // update lastTime to now for future loops
 
     // moving avg calualtion buffer
     rpmBuffer[bufferIndex] = currentRPM;
     bufferIndex = (bufferIndex + 1) % bufferSize;
     if (sampleCount < bufferSize) sampleCount++;
 
     // compute moving avg from buffer
     float sum = 0;
     for (int i = 0; i < sampleCount; i++) {
       sum += rpmBuffer[i];
     }
     float movingAverageRPM = sum / sampleCount;
 
     // PID calc approx.
     float dt = elapsed / 1000.0;
     error = desiredRPM - movingAverageRPM;
     integral += error * dt;
     float derivative = (error - previousError) / dt;
     previousError = error;
 
     // constrain claculated val to between 0 - 255
     int pwmOutput = constrain(
       (int)(Kp * error + Ki * integral + Kd * derivative),
       0, 255
     );
     analogWrite(pwmPin, pwmOutput);
 
     // calc %err
     float percentageError = 0;
     if (desiredRPM != 0) {
       percentageError = (fabs(error) / desiredRPM) * 100.0;
     }
 
     // output values
     Serial.print("RPM: ");
     Serial.print(currentRPM, 2);
     Serial.print("   MA: ");
     Serial.print(movingAverageRPM, 2);
     Serial.print("   Set: ");
     Serial.print(desiredRPM, 2);
     Serial.print("   PWM: ");
     Serial.print(pwmOutput);
     Serial.print("   %Err: ");
     Serial.println(percentageError, 2);
   }
 
   // check for new input 
   if (Serial.available() > 0) {
     String s = Serial.readStringUntil('\n');
     s.trim();
     float newRPM = s.toFloat();
 
     if (newRPM == 0) {
       // reset PID vals to avoid div-by-zero err
       integral = 0;
       previousError = 0;
       desiredRPM = 0;
       Serial.println("Desired RPM set to 0. Motor stopping.");
     } else {
       desiredRPM = newRPM;
       Serial.print("New desired RPM: ");
       Serial.println(desiredRPM);
     }
   }
 }
 