#!/usr/bin/env python3
import serial
import time
import re
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import TextBox, Button
import voice_to_text as v2t  # Ensure your voice input module is available
import subprocess  # Needed to call phi3.5
import piper_tts  # Module for text-to-speech confirmation


SERIAL_PORT = "/dev/cu.usbmodem744DBD9FCC982"  # Update this to your Arduino port
BAUD_RATE = 115200  # Using the higher baud rate


ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
time.sleep(2)  # Allow time for the connection to initialize

# ----- Global Variables for Countdown -----
countdown_end_time = None  # Stores the end time for the running timer (if any)

# ----- Data Storage -----
t_data = []
rpm_data = []
ma_data = []
set_data = []
pwm_data = []
perr_data = []
start_time = time.time()

# Regular expression to match lines like:
# "RPM: 123.45   MA: 123.45   Set: 1500.00   PWM: 200   %Err: 20.50"
pattern = re.compile(
    r"RPM:\s*([-\d.]+)\s+MA:\s*([-\d.]+)\s+Set:\s*([-\d.]+)\s+PWM:\s*([-\d]+)\s+%Err:\s*([-\d.]+)"
)

# ----- Helper Function: Parse Command (used for voice input) -----
def parse_command(command):
    """
    Parses a command string to extract the RPM and time.
    First, it checks if the command consists of two numbers (expected from phi3.5).
    Otherwise, it searches for a pattern with "rpm" and time units.
    """
    # Check for a simple two-number format: "<RPM> <TIME>"
    two_numbers = re.match(r"^\s*(\d+)\s+(\d+)\s*$", command)
    if two_numbers:
        rpm_val = int(two_numbers.group(1))
        timer = int(two_numbers.group(2))
        return rpm_val, timer

    # Otherwise, parse natural language commands
    rpm_match = re.search(r"(\d+)\s*rpm", command, re.IGNORECASE)
    time_match = re.search(r"(\d+)\s*(minutes?|seconds?)", command, re.IGNORECASE)
    
    if rpm_match:
        rpm_val = int(rpm_match.group(1))
    else:
        # Fallback: try interpreting the entire command as a number
        try:
            rpm_val = int(float(command.strip()))
        except ValueError:
            rpm_val = None

    timer = None
    if time_match:
        timer = int(time_match.group(1))
        unit = time_match.group(2).lower()
        if 'minute' in unit:
            timer = timer * 60  # Convert minutes to seconds
    return rpm_val, timer

def execute_command(rpm, timer):
    """
    Directly sends the command to the Arduino.
    """
    global countdown_end_time
    if timer is not None:
        data = f"{rpm},{timer}\n"
        countdown_end_time = time.time() + timer  # Set countdown end time
    else:
        data = f"{rpm}\n"
        countdown_end_time = None  # Clear countdown if no time provided
    ser.write(data.encode())
    print(f"Sent command: {data.strip()}")

def confirm_and_execute_command(rpm, timer):
    """
    Uses Piper TTS to ask the user for confirmation of the command.
    Waits for a voice response and then either executes the command (if "yes" is detected)
    or cancels it and returns to listening for the next command.
    """
    confirmation_prompt = f"Do you really want to run for {timer} seconds at {rpm} RPM? Please say yes or no."
    piper_tts.speak(confirmation_prompt)
    print("Waiting for confirmation...")
    confirmation_response = v2t.recognize_speech()  # Listen for the confirmation response
    print(f"Confirmation response: {confirmation_response}")
    if "yes" in confirmation_response.lower():
        execute_command(rpm, timer)
    else:
        print("Command cancelled. Returning to command listening stage.")

def send_command(command):
    """
    Processes the command string (from voice input),
    extracts RPM and time, and sends them to the Arduino.
    If only RPM is provided, only that value is sent.
    Also sets the countdown timer if a time value is provided.
    (This function is used for manual input.)
    """
    global countdown_end_time
    rpm, timer = parse_command(command)
    if rpm is not None:
        if timer is not None:
            data = f"{rpm},{timer}\n"
            countdown_end_time = time.time() + timer
        else:
            data = f"{rpm}\n"
            countdown_end_time = None
        ser.write(data.encode())
        print(f"Sent command: {data.strip()}")
    else:
        print("Invalid command input. Please try again.")

# ----- Manual Input via Two TextBoxes and a Submit Button -----
def manual_submit(event):
    global countdown_end_time
    rpm_text = rpm_box.text.strip()
    time_text = time_box.text.strip()
    try:
        rpm_val = int(rpm_text)
        timer_val = int(time_text) if time_text else None
        if timer_val is not None:
            command = f"{rpm_val},{timer_val}\n"
            countdown_end_time = time.time() + timer_val
        else:
            command = f"{rpm_val}\n"
            countdown_end_time = None
        ser.write(command.encode())
        print(f"Sent manual command: {command.strip()}")
    except ValueError:
        print("Invalid manual input. Please enter valid numbers for RPM and Time (in seconds).")

# ----- Voice Input via Button using phi3.5 -----
def voice_input(event):
    # Update the voice button label to indicate activity
    voice_button.label.set_text("Listening...")
    plt.draw()
    
    print("Listening for voice command...")
    command_text = v2t.listen_for_trigger()  # Blocks until a valid voice command is captured
    if command_text:
        print("Voice command recognized:", command_text)
        # Build the prompt for phi3.5
        base_prompt = (
            "Extract the centrifuge settings from the following request exactly as stated. "
            "Ignore any extraneous words (such as names or filler words) that do not affect the numerical values. "
            "Do the following:\n\n"
            "1. Find the integer immediately preceding the term \"rpm\" (case insensitive) and use that as the RPM value without altering it.\n"
            "2. Identify the time duration mentioned. If the duration is specified in minutes, convert it to seconds; if in seconds, use it as is.\n"
            "3. Return your answer as plain text in the exact format: <RPM> <TIME>, with no extra formatting or characters.\n\n"
            "For example, if the input is \"set centrifuge to 2000 rpm for 15 seconds\", the output should be: 2000 15\n\n"
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
        
        # Parse the output from phi3.5
        rpm, timer = parse_command(output)
        if rpm is not None and timer is not None:
            # Ask for user confirmation before executing the command
            confirm_and_execute_command(rpm, timer)
        elif rpm is not None:
            # If only RPM is provided, execute the command without confirmation
            execute_command(rpm, timer)
        else:
            print("Invalid command received from phi3.5.")
    else:
        print("No voice command detected.")
    
    # Revert the voice button label
    voice_button.label.set_text("Voice Input")
    plt.draw()

# ----- Set Up Plotting -----
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8))
plt.subplots_adjust(bottom=0.35, top=0.92)  # Reserve extra space at top and bottom for widgets

# Countdown Text at the top center
countdown_text = fig.text(0.5, 0.97, "", ha="center", va="top", fontsize=12)

# Subplot 1: RPM, Moving Average, and Set RPM
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
    # Read all available serial lines
    while ser.in_waiting:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
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

    # Keep only the last 60 seconds of data
    current_time = time.time() - start_time
    while t_data and t_data[0] < current_time - 60:
        t_data.pop(0)
        rpm_data.pop(0)
        ma_data.pop(0)
        set_data.pop(0)
        pwm_data.pop(0)
        perr_data.pop(0)

    # Update the plot lines
    line_rpm.set_data(t_data, rpm_data)
    line_ma.set_data(t_data, ma_data)
    line_set.set_data(t_data, set_data)
    line_pwm.set_data(t_data, pwm_data)
    line_perr.set_data(t_data, perr_data)

    # Adjust x-axis to display only the last 60 seconds
    for ax in (ax1, ax2, ax3):
        ax.set_xlim(max(0, current_time - 60), current_time + 1)
        ax.relim()
        ax.autoscale_view(scalex=False)

    # Update countdown text if a timer is active
    if countdown_end_time is not None:
        remaining = countdown_end_time - time.time()
        if remaining <= 0:
            countdown_text.set_text("")  # Timer expired
            countdown_end_time = None
        else:
            countdown_text.set_text(f"Remaining Time: {int(remaining)} s")
    else:
        countdown_text.set_text("")

    return line_rpm, line_ma, line_set, line_pwm, line_perr

ani = FuncAnimation(fig, update, interval=100)

# ----- Set Up Widgets -----
# Manual input: Two TextBoxes and a Submit Button
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
