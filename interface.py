#!/usr/bin/env python3
import sys
import serial
import time
import re
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import TextBox, Button
import voice_to_text as v2t
import subprocess
import asyncio
import edge_tts
import os
import threading

# --- TTS Helper ---
async def speak_text(text):
    communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
    output_file = "tts_output.mp3"
    await communicate.save(output_file)
    subprocess.run(["afplay", output_file])  # For macOS; adjust if needed
    os.remove(output_file)

# --- Configuration ---
SERIAL_PORT = "/dev/cu.usbmodem1101"  # adjust to your board
BAUD_RATE = 9600

# --- Globals ---
countdown_end_time = None
t_data = []
rpm_data = []
ma_data = []
set_data = []
pwm_data = []
perr_data = []
start_time = None

# --- Sliding Window Log ---
terminal_log = []
log_text_object = None
MAX_VISIBLE_LINES = 20  # Only show the last 20 lines

class EmittingStream:
    """ Redirect 'print' statements to a list, then refresh the figure text. """
    def __init__(self, text_update_callback):
        self.text_update_callback = text_update_callback

    def write(self, message):
        lines = message.split("\n")
        for line in lines:
            if line.strip():
                terminal_log.append(line.rstrip("\r"))
        self.text_update_callback()

    def flush(self):
        pass

def update_log_text():
    """
    Display only the last MAX_VISIBLE_LINES lines, so new lines appear at bottom.
    The oldest lines scroll off the top.
    """
    # Keep a slice of the last N lines
    latest_lines = terminal_log[-MAX_VISIBLE_LINES:]
    # This is normal, oldest line first ... newest line last 
    # => new lines are visually at the bottom (because of va='top')
    log_text = "\n".join(latest_lines)
    if log_text_object is not None:
        log_text_object.set_text(log_text)
    plt.draw()

# Redirect stdout to use our custom logger
sys.stdout = EmittingStream(update_log_text)

# --- Helper Functions ---
def parse_command(command):
    command = command.strip()
    two_numbers = re.match(r"^(\d+)[,\s]+(\d+)$", command)
    if two_numbers:
        rpm_val = int(two_numbers.group(1))
        timer = int(two_numbers.group(2))
        return rpm_val, timer

    rpm_match = re.search(r"(\d+)\s*rpm", command, re.IGNORECASE)
    time_match = re.search(r"(\d+)\s*(minutes?|seconds?)", command, re.IGNORECASE)
    
    if rpm_match:
        rpm_val = int(rpm_match.group(1))
    else:
        try:
            rpm_val = int(float(command))
        except ValueError:
            rpm_val = None

    timer = None
    if time_match:
        timer = int(time_match.group(1))
        if 'min' in time_match.group(2).lower():
            timer *= 60
    return rpm_val, timer

def send_command(command, ser):
    global countdown_end_time
    rpm, timer = parse_command(command)
    if rpm is not None:
        if timer is not None:
            data = f"{rpm},{timer}\n"
            countdown_end_time = time.time() + timer
        else:
            data = f"{rpm}\n"
            countdown_end_time = None

        try:
            ser.write(data.encode())
            ser.flush()
            print(f"Sent command: {data.strip()}")
        except Exception as e:
            print(f"Error sending command: {e}")
    else:
        print("Invalid command input. Please try again.")

def manual_submit(event):
    global countdown_end_time
    rpm_text = rpm_box.text.strip()
    time_text = time_box.text.strip()
    try:
        rpm_val = int(rpm_text)
        timer_val = int(time_text) if time_text else None
        if timer_val is not None:
            cmd = f"{rpm_val},{timer_val}\n"
            countdown_end_time = time.time() + timer_val
        else:
            cmd = f"{rpm_val}\n"
            countdown_end_time = None

        ser.write(cmd.encode())
        ser.flush()
        print(f"Sent manual command: {cmd.strip()}")
    except ValueError:
        print("Invalid input. Please enter numbers for RPM and Time.")
    except Exception as e:
        print(f"Error in manual submission: {e}")

def voice_input_async():
    voice_button.label.set_text("Listening...")
    plt.draw()
    
    print("Listening for voice command...")
    command_text = v2t.listen_for_trigger()
    if command_text:
        print("Voice command recognized:", command_text)
        base_prompt = (
            "Extract the centrifuge settings from the following request exactly as stated. "
            "Return the answer in '<RPM> <TIME>' format.\n\nRequest: "
        )
        combined_prompt = base_prompt + command_text
        print("Generated Prompt:", combined_prompt)

        try:
            result = subprocess.run(
                ['ollama', 'run', 'phi4', combined_prompt],
                capture_output=True,
                text=True
            )
            output = result.stdout.strip()
            print("Raw output from phi4:", output)
        except Exception as e:
            print(f"Error running phi4: {e}")
            output = ""

        if output:
            confirmation = f"The parsed command is: {output}. Is this correct? Please say yes or no."
            asyncio.run(speak_text(confirmation))
            print(confirmation)

            original_duration = v2t.DURATION
            v2t.DURATION = 5
            response = v2t.recognize_speech()
            v2t.DURATION = original_duration
            print("User response:", response)

            if "yes" in response.lower():
                print("User confirmed. Sending command.")
                asyncio.run(speak_text("Command confirmed. Sending command."))
                send_command(output, ser)
            else:
                print("User did not confirm. Command aborted.")
                asyncio.run(speak_text("Command aborted."))
        else:
            print("No valid output received from phi4.")
    else:
        print("No voice command detected.")

    voice_button.label.set_text("Voice Input")
    plt.draw()

def voice_input(event):
    threading.Thread(target=voice_input_async, daemon=True).start()

def call_chatbot_api(conversation_history):
    prompt = ""
    for msg in conversation_history:
        prompt += f"{msg['role']}: {msg['content']}\n"
    prompt += "assistant: "

    try:
        result = subprocess.run(
            ['ollama', 'run', 'phi4', prompt],
            capture_output=True,
            text=True
        )
        response = result.stdout.strip()
    except Exception as e:
        print(f"Error calling chatbot API: {e}")
        response = "Sorry, I'm having trouble responding."
    return response

def chat_mode():
    conversation_history = [
        {"role": "system", "content": "You are a fun, witty, and engaging scientific chat partner. Be brief."}
    ]
    asyncio.run(speak_text("Chat mode activated. What would you like to talk about?"))

    while True:
        user_input = v2t.recognize_speech()
        if not user_input:
            continue
        if "exit chat" in user_input.lower() or "quit chat" in user_input.lower():
            asyncio.run(speak_text("Exiting chat mode."))
            break

        conversation_history.append({"role": "user", "content": user_input})
        response = call_chatbot_api(conversation_history)
        conversation_history.append({"role": "assistant", "content": response})
        asyncio.run(speak_text(response))

def run_session():
    global ser, countdown_end_time
    global t_data, rpm_data, ma_data, set_data, pwm_data, perr_data, start_time
    global log_text_object

    countdown_end_time = None
    t_data = []
    rpm_data = []
    ma_data = []
    set_data = []
    pwm_data = []
    perr_data = []
    start_time = time.time()

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    except Exception as e:
        print(f"Error opening serial port: {e}")
        return

    time.sleep(2)

    pattern = re.compile(
        r"RPM:\s*([-\d.]+)\s+MA:\s*([-\d.]+)\s+Set:\s*([-\d.]+)\s+PWM:\s*([-\d]+)\s+%Err:\s*([-\d.]+)"
    )

    # Create a figure with 4 rows for 3 plots + 1 log axis
    fig = plt.figure(figsize=(10, 10))
    gs = fig.add_gridspec(nrows=4, ncols=1, height_ratios=[1, 1, 1, 1])
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[2, 0])
    ax_log = fig.add_subplot(gs[3, 0])

    # Extra bottom margin for text boxes & buttons
    fig.subplots_adjust(top=0.92, bottom=0.28, hspace=0.4)

    countdown_text = fig.text(0.5, 0.96, "", ha="center", va="top", fontsize=12)

    # RPM/MA/Set
    line_rpm, = ax1.plot([], [], "o-", label="RPM")
    line_ma,  = ax1.plot([], [], "x--", label="MA")
    line_set, = ax1.plot([], [], "s:", label="Set")
    ax1.set_ylabel("RPM")
    ax1.set_title("RPM, MA, and Set vs. Time")
    ax1.legend(loc="upper right")
    ax1.grid(True)

    # PWM in magenta
    line_pwm, = ax2.plot([], [], "o-", color="magenta", label="PWM")
    ax2.set_ylabel("PWM")
    ax2.set_title("PWM vs. Time")
    ax2.legend(loc="upper right")
    ax2.grid(True)

    # %Err in red
    line_perr, = ax3.plot([], [], "o-", color="red", label="% Err")
    ax3.set_xlabel("Time (s)")
    ax3.set_ylabel("% Err")
    ax3.set_title("Percentage Error vs. Time")
    ax3.legend(loc="upper right")
    ax3.grid(True)

    # -- Terminal Log Axis --
    ax_log.axis("off")
    # Pin the text to the top-left corner. New lines accumulate downward.
    # clip_on=True ensures text doesn’t overflow if it’s too big.
    log_text_object = ax_log.text(
        0, 1, "",
        va="top", ha="left",
        fontsize=9,
        family="monospace",
        clip_on=True,
        transform=ax_log.transAxes
    )

    def update(frame):
        global countdown_end_time
        while ser.in_waiting:
            try:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
            except Exception as e:
                print(f"Error reading line from serial: {e}")
                continue
            if line:
                m = pattern.search(line)
                if m:
                    try:
                        rpm_val  = float(m.group(1))
                        ma_val   = float(m.group(2))
                        set_val  = float(m.group(3))
                        pwm_val  = int(m.group(4))
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
        # Keep only 60s of rolling data
        while t_data and t_data[0] < current_time - 60:
            t_data.pop(0)
            rpm_data.pop(0)
            ma_data.pop(0)
            set_data.pop(0)
            pwm_data.pop(0)
            perr_data.pop(0)

        line_rpm.set_data(t_data, rpm_data)
        line_ma.set_data(t_data, ma_data)
        line_set.set_data(t_data, set_data)
        line_pwm.set_data(t_data, pwm_data)
        line_perr.set_data(t_data, perr_data)

        for ax in (ax1, ax2, ax3):
            ax.set_xlim(max(0, current_time - 60), current_time + 1)
            ax.relim()
            ax.autoscale_view(scalex=False)

        if countdown_end_time is not None:
            remaining = countdown_end_time - time.time()
            if remaining <= 0:
                countdown_text.set_text("")
                try:
                    ser.write("0\n".encode())
                    ser.flush()
                except Exception as e:
                    print(f"Error sending stop command: {e}")
                countdown_end_time = None
            else:
                countdown_text.set_text(f"Remaining Time: {int(remaining)} s")
        else:
            countdown_text.set_text("")

        return (line_rpm, line_ma, line_set, line_pwm, line_perr)

    ani = FuncAnimation(fig, update, interval=100)

    # ------------- Place text boxes and buttons -------------
    ax_rpm = fig.add_axes([0.1, 0.16, 0.25, 0.05])
    global rpm_box
    rpm_box = TextBox(ax_rpm, "RPM")

    ax_time = fig.add_axes([0.45, 0.16, 0.25, 0.05])
    global time_box
    time_box = TextBox(ax_time, "Time (s)")

    ax_submit = fig.add_axes([0.8, 0.16, 0.12, 0.05])
    submit_button = Button(ax_submit, "Submit")
    submit_button.on_clicked(manual_submit)

    ax_voice = fig.add_axes([0.8, 0.08, 0.12, 0.05])
    global voice_button
    voice_button = Button(ax_voice, "Voice Input")
    voice_button.on_clicked(voice_input)

    ax_chat = fig.add_axes([0.1, 0.08, 0.15, 0.05])
    n = 256
    gradient = np.linspace(0, 1, n).reshape(1, n)
    ax_chat.imshow(gradient, aspect='auto', cmap='rainbow',
                   origin='lower', extent=[0, 1, 0, 1])
    ax_chat.patch.set_alpha(0)
    chat_button = Button(ax_chat, "Chat Mode", color='none', hovercolor='none')
    chat_button.label.set_fontsize(12)
    chat_button.on_clicked(lambda event: threading.Thread(target=chat_mode, daemon=True).start())

    plt.show()
    ser.close()

if __name__ == '__main__':
    while True:
        run_session()
        asyncio.run(speak_text("Do you want to start a new session? Please say yes or no."))
        print("Awaiting response for new session...")
        response = v2t.recognize_speech()
        print("Response received:", response)
        if "yes" in response.lower():
            continue
        else:
            asyncio.run(speak_text("Exiting the program. Goodbye."))
            break
