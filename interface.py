"""
Centrifuge Control and Monitoring System
----------------------------------------
This script communicates with an Arduino-controlled centrifuge via serial communication.
It enables manual and voice-controlled RPM commands with real-time data visualization.

Features:
- Serial communication with Arduino
- Voice input for command execution (via speech-to-text)
- RPM control with a countdown timer
- Live data plotting (RPM, PWM, % Error)
- Text-based manual command input
- Confirmation system using TTS (Coqui)

Author: Jeff Liu, with the help of Lucas Sosnick and Zach Lin
Hardware: Raspberry Pi 5 with 8GB RAM

/ Main Program
  ├── Serial Communication Setup
  ├── Data Storage (using deque)
  ├── Helper Functions
  │   ├── parse_command()              # Extracts RPM and time from input
  │   ├── send_to_arduino()            # Sends RPM command to Arduino
  │   ├── confirm_and_execute_command()# Confirms voice command execution
  │   ├── manual_submit()              # Handles manual text input
  │   ├── voice_input()                # Processes voice command input
  │   ├── trim_old_data()              # Removes data older than 60s
  ├── Data Visualization
  │   ├── update()                     # Updates the live graph
  ├── UI Elements
  │   ├── TextBox (RPM & Time)
  │   ├── Button (Submit & Voice Input)
  ├── Main Execution
  │   ├── FuncAnimation (Real-time update)
  │   ├── Matplotlib UI rendering
  │   ├── Serial connection closure
"""

#!/usr/bin/env python3
import serial
import time
import re
from collections import deque
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import TextBox, Button
import voice_to_text as v2t  
import subprocess  # Used for playing audio
from TTS.api import TTS  # Coqui TTS

# ----- Configuration -----
SERIAL_PORT = "/dev/cu.usbmodem744DBD9FCC982"  
BAUD_RATE = 115200

# ----- Initialize Serial Connection -----
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
time.sleep(2)  # Allow time for the connection to initialize

# ----- Global Variables for Countdown -----
countdown_end_time = None  # Stores the end time for the running timer (if any)

# ----- Data Storage using deque for efficient pops from left -----
t_data = deque()
rpm_data = deque()
ma_data = deque()
set_data = deque()
pwm_data = deque()
perr_data = deque()
start_time = time.time()

# Regular expression to match lines like:
# "RPM: 123.45   MA: 123.45   Set: 1500.00   PWM: 200   %Err: 20.50"
pattern = re.compile(
    r"RPM:\s*([-\d.]+)\s+MA:\s*([-\d.]+)\s+Set:\s*([-\d.]+)\s+PWM:\s*([-\d]+)\s+%Err:\s*([-\d.]+)"
)

# ----- Preinitialize the TTS instance once for reuse -----
tts_instance = TTS("tts_models/en/ljspeech/tacotron2-DDC", gpu=False)

# ----- Helper Functions -----
def parse_command(command):
    """
    Parses a command string to extract the RPM and time.
    """
    # Check for a simple two-number format: "<RPM> <TIME>"
    two_numbers = re.match(r"^\s*(\d+)\s+(\d+)\s*$", command)
    if two_numbers:
        rpm_val = int(two_numbers.group(1))
        timer = int(two_numbers.group(2))
        return rpm_val, timer

    # Parse natural language commands
    rpm_match = re.search(r"(\d+)\s*rpm", command, re.IGNORECASE)
    time_match = re.search(r"(\d+)\s*(minutes?|seconds?)", command, re.IGNORECASE)
    
    rpm_val = int(rpm_match.group(1)) if rpm_match else None
    timer = None
    if time_match:
        timer = int(time_match.group(1))
        if 'minute' in time_match.group(2).lower():
            timer *= 60  # Convert minutes to seconds
    else:
        # Fallback: try to interpret the entire command as a number
        try:
            rpm_val = int(float(command.strip()))
        except ValueError:
            rpm_val = None

    return rpm_val, timer

def send_to_arduino(rpm, timer):
    """
    Sends the RPM (and optionally timer) command to the Arduino.
    """
    global countdown_end_time
    if timer is not None:
        data = f"{rpm},{timer}\n"
        countdown_end_time = time.time() + timer  # Set countdown end time
    else:
        data = f"{rpm}\n"
        countdown_end_time = None
    ser.write(data.encode())
    print(f"Sent command: {data.strip()}")

def confirm_and_execute_command(rpm, timer):
    """
    Asks for user confirmation before executing the command using TTS.
    """
    confirmation_prompt = f"Do you really want to run for {timer} seconds at {rpm} RPM? Please say yes or no."
    # Use the preinitialized TTS instance
    tts_instance.tts_to_file(text=confirmation_prompt, file_path="confirmation.wav")
    subprocess.run(["aplay", "confirmation.wav"])
    
    print("Waiting for confirmation...")
    confirmation_response = v2t.recognize_speech()  # Listen for the confirmation response
    print(f"Confirmation response: {confirmation_response}")
    
    if "yes" in confirmation_response.lower():
        send_to_arduino(rpm, timer)
    else:
        print("Command cancelled. Returning to command listening stage.")

def send_command(command):
    """
    Processes the command string (from voice input or manual) and sends it to the Arduino.
    """
    rpm, timer = parse_command(command)
    if rpm is not None:
        send_to_arduino(rpm, timer)
    else:
        print("Invalid command input. Please try again.")

def manual_submit(event):
    """
    Callback for the manual submission via text boxes.
    """
    rpm_text = rpm_box.text.strip()
    time_text = time_box.text.strip()
    try:
        rpm_val = int(rpm_text)
        timer_val = int(time_text) if time_text else None
        send_to_arduino(rpm_val, timer_val)
        print(f"Sent manual command: {rpm_val}" + (f", {timer_val}" if timer_val is not None else ""))
    except ValueError:
        print("Invalid manual input. Please enter valid numbers for RPM and Time (in seconds).")

def voice_input(event):
    """
    Callback for voice input.
    """
    voice_button.label.set_text("Listening...")
    plt.draw()
    
    print("Listening for voice command...")
    command_text = v2t.listen_for_trigger()  # Blocks until a valid voice command is captured
    if command_text:
        print("Voice command recognized:", command_text)
        base_prompt = (
            "Extract the centrifuge settings from the following request exactly as stated. "
            "Ignore extraneous words that do not affect the numerical values. "
            "Return your answer as plain text in the exact format: <RPM> <TIME>.\n\n"
            "For example, if the input is 'set centrifuge to 2000 rpm for 5 minutes', the output should be: 2000 300\n\n"
            "Request: "
        )
        combined_prompt = base_prompt + command_text
        print("Generated Prompt:", combined_prompt)
        
        # Call phi3.5 via subprocess to get the formatted command
        result = subprocess.run(
            ['ollama', 'run', 'phi3.5', combined_prompt],
            capture_output=True,
            text=True
        )
        output = result.stdout.strip()
        print("Raw output from phi3.5:", output)
        
        rpm, timer = parse_command(output)
        if rpm is not None:
            if timer is not None:
                confirm_and_execute_command(rpm, timer)
            else:
                send_to_arduino(rpm, timer)
        else:
            print("Invalid command received from phi3.5.")
    else:
        print("No voice command detected.")
    
    voice_button.label.set_text("Voice Input")
    plt.draw()

def trim_old_data(current_time):
    """
    Remove data points older than 60 seconds from each deque.
    """
    while t_data and t_data[0] < current_time - 60:
        t_data.popleft()
        rpm_data.popleft()
        ma_data.popleft()
        set_data.popleft()
        pwm_data.popleft()
        perr_data.popleft()

# ----- Set Up Plotting -----
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8))
plt.subplots_adjust(bottom=0.35, top=0.92)

# Countdown Text at the top center
countdown_text = fig.text(0.5, 0.97, "", ha="center", va="top", fontsize=12)

# Subplot 1: RPM, MA, and Set RPM
line_rpm, = ax1.plot([], [], "o-", label="RPM")
line_ma, = ax1.plot([], [], "x--", label="MA")
line_set, = ax1.plot([], [], "s:", label="Set")
ax1.set_ylabel("RPM")
ax1.set_title("RPM, MA, and Set RPM vs. Time")
ax1.legend()
ax1.grid(True)

# Subplot 2: PWM output
line_pwm, = ax2.plot([], [], "o-", color="magenta", label="PWM")
ax2.set_ylabel("PWM")
ax2.set_title("PWM vs. Time")
ax2.legend()
ax2.grid(True)

# Subplot 3: Percentage Error
line_perr, = ax3.plot([], [], "o-", color="red", label="% Err")
ax3.set_xlabel("Time (s)")
ax3.set_ylabel("% Err")
ax3.set_title("Percentage Error vs. Time")
ax3.legend()
ax3.grid(True)

def update(frame):
    global countdown_end_time
    # Read all available serial lines at once
    try:
        lines = ser.readlines()
    except Exception as e:
        print(f"Error reading serial data: {e}")
        lines = []
        
    for raw_line in lines:
        try:
            line = raw_line.decode("utf-8", errors="ignore").strip()
        except Exception as e:
            continue
        if line:
            m = pattern.search(line)
            if m:
                try:
                    rpm_val = float(m.group(1))
                    ma_val = float(m.group(2))
                    set_val = float(m.group(3))
                    pwm_val = int(m.group(4))
                    perr_val = float(m.group(5))
                except ValueError:
                    continue
                current_time = time.time() - start_time
                t_data.append(current_time)
                rpm_data.append(rpm_val)
                ma_data.append(ma_val)
                set_data.append(set_val)
                pwm_data.append(pwm_val)
                perr_data.append(perr_val)
    
    current_time = time.time() - start_time
    trim_old_data(current_time)

    # Update the plot lines
    line_rpm.set_data(list(t_data), list(rpm_data))
    line_ma.set_data(list(t_data), list(ma_data))
    line_set.set_data(list(t_data), list(set_data))
    line_pwm.set_data(list(t_data), list(pwm_data))
    line_perr.set_data(list(t_data), list(perr_data))

    # Adjust x-axis for each subplot
    for ax in (ax1, ax2, ax3):
        ax.set_xlim(max(0, current_time - 60), current_time + 1)
        ax.relim()
        ax.autoscale_view(scalex=False)

    # Update countdown text if active
    if countdown_end_time is not None:
        remaining = countdown_end_time - time.time()
        if remaining <= 0:
            countdown_text.set_text("")
            countdown_end_time = None
        else:
            countdown_text.set_text(f"Remaining Time: {int(remaining)} s")
    else:
        countdown_text.set_text("")

    return line_rpm, line_ma, line_set, line_pwm, line_perr

ani = FuncAnimation(fig, update, interval=100)

# ----- Set Up Widgets -----
ax_rpm = plt.axes([0.1, 0.22, 0.3, 0.075])
rpm_box = TextBox(ax_rpm, "RPM")

ax_time = plt.axes([0.45, 0.22, 0.3, 0.075])
time_box = TextBox(ax_time, "Time (s)")

ax_submit = plt.axes([0.8, 0.22, 0.15, 0.075])
manual_submit_button = Button(ax_submit, "Submit")
manual_submit_button.on_clicked(manual_submit)

ax_voice = plt.axes([0.8, 0.1, 0.15, 0.075])
voice_button = Button(ax_voice, "Voice Input")
voice_button.on_clicked(voice_input)

plt.show()
ser.close()
