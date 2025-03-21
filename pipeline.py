#!/usr/bin/env python3
import serial
import time
import re
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import TextBox, Button
import voice_to_text as v2t  # Using your existing voice_to_text module (unchanged)
import subprocess  # Needed to call phi4 and to play audio
import asyncio
import edge_tts  # Edge TTS package for neural voices
import os
import threading

# ----- TTS Helper Function using Edgpipe TTS -----
async def speak_text(text):
    # Using "en-US-GuyNeural" for a deeper voice.
    communicate = edge_tts.Communicate(text, voice="en-GB-RyanNeural")
    output_file = "tts_output.mp3"
    await communicate.save(output_file)
    # On macOS, use afplay to play the audio file. Change if on another OS.
    subprocess.run(["afplay", output_file])
    os.remove(output_file)

# ----- Configuration -----
SERIAL_PORT = "/dev/cu.usbmodem1101"  # Update this to your Arduino port
BAUD_RATE = 9600  # Using the higher baud rate

# ----- Global Variables -----
countdown_end_time = None  # Global countdown timer for sending stop command
# Variables for data storage; these will be reinitialized each session.
t_data = []
rpm_data = []
ma_data = []
set_data = []
pwm_data = []
perr_data = []
start_time = None

# ----- Helper Functions -----
def parse_command(command):
    """
    Parses a command string to extract the RPM and time.
    Strips extra whitespace and expects a format like "<RPM> <TIME>" or "<RPM>,<TIME>".
    It also supports natural language inputs containing "rpm" and a time unit.
    """
    command = command.strip()
    # Try simple two-number format.
    two_numbers = re.match(r"^(\d+)[,\s]+(\d+)$", command)
    if two_numbers:
        rpm_val = int(two_numbers.group(1))
        timer = int(two_numbers.group(2))
        return rpm_val, timer

    # Otherwise, use regex search for natural language patterns.
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
        unit = time_match.group(2).lower()
        if 'minute' in unit:
            timer *= 60  # Convert minutes to seconds
    return rpm_val, timer

def send_command(command, ser):
    """
    Processes the command string (from voice or manual input),
    extracts RPM and time, and sends them to the Arduino.
    Flushes the serial buffer to ensure the command is sent immediately.
    """
    global countdown_end_time
    command = command.strip()
    rpm, timer = parse_command(command)
    if rpm is not None:
        if timer is not None:
            data = f"{rpm},{timer}\n"
            countdown_end_time = time.time() + timer  # Set countdown end time
        else:
            data = f"{rpm}\n"
            countdown_end_time = None  # Clear countdown if no time provided
        try:
            ser.write(data.encode())
            ser.flush()  # Ensure the data is sent immediately
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
            command = f"{rpm_val},{timer_val}\n"
            countdown_end_time = time.time() + timer_val
        else:
            command = f"{rpm_val}\n"
            countdown_end_time = None
        ser.write(command.encode())
        ser.flush()
        print(f"Sent manual command: {command.strip()}")
    except ValueError:
        print("Invalid manual input. Please enter valid numbers for RPM and Time (in seconds).")
    except Exception as e:
        print(f"Error in manual submission: {e}")

def voice_input_async():
    """
    Runs the voice input process in a separate thread so that the UI remains responsive.
    """
    # Update the voice button label to indicate listening.
    voice_button.label.set_text("Listening...")
    plt.draw()
    
    print("Listening for voice command...")
    command_text = v2t.listen_for_trigger()  # Blocks until a valid voice command is captured
    if command_text:
        print("Voice command recognized:", command_text)
        base_prompt = (
            "Extract the centrifuge settings from the following request exactly as stated. "
            "Ignore any extraneous words that do not affect the numerical values. "
            "Return your answer as plain text in the format: <RPM> <TIME>.\n\n"
            "For example, if the input is \"set centrifuge to 2000 rpm for 15 seconds\", "
            "the output should be: 2000 15\n\n"
            "Request: "
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
            confirmation_text = f"The parsed command is: {output}. Is this correct? Please say yes or no."
            asyncio.run(speak_text(confirmation_text))
            print(confirmation_text)
            
            # Temporarily change listening duration for confirmation.
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
    
    # Revert the voice button label.
    voice_button.label.set_text("Voice Input")
    plt.draw()

def voice_input(event):
    # Run the voice input process in a separate thread to keep the UI responsive.
    threading.Thread(target=voice_input_async, daemon=True).start()



def call_chatbot_api(conversation_history):
    """
    Converts the conversation history into a prompt and calls your chatbot model.
    Adjust the command if you use a different API or model.
    """
    prompt = ""
    for msg in conversation_history:
        # Format each message as "role: content"
        prompt += f"{msg['role']}: {msg['content']}\n"
    prompt += "assistant: "  # Prompt the assistant to respond
    
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
    """
    Runs a conversation loop in which the AI (with a fun personality) chats with the user.
    The user can say "exit chat" or "quit chat" to leave the mode.
    """
    # Initialize conversation with a system prompt defining the AI personality.
    conversation_history = [
        {"role": "system", "content": "You are a fun, witty, and engaging scientific chat partner. Respond in a humorous and friendly tone. The user will ask questions related to science and centrifugation. Please be Very Brief with your response and allow for the user to continue the conversation."}
    ]
    
    # Announce that chat mode has been activated.
    asyncio.run(speak_text("Chat mode activated. What would you like to talk about?"))
    
    while True:
        # Use voice-to-text to capture user input.
        user_input = v2t.recognize_speech()
        if not user_input:
            continue
        
        # Allow exit from chat mode.
        if "exit chat" in user_input.lower() or "quit chat" in user_input.lower():
            asyncio.run(speak_text("Exiting chat mode."))
            break
        
        # Append the user input to the conversation history.
        conversation_history.append({"role": "user", "content": user_input})
        
        # Get the chatbot's response.
        response = call_chatbot_api(conversation_history)
        conversation_history.append({"role": "assistant", "content": response})
        
        # Speak the AI's response using TTS.
        asyncio.run(speak_text(response))




def run_session():
    """Run one full RPM session with plotting and input handling."""
    global ser, countdown_end_time, t_data, rpm_data, ma_data, set_data, pwm_data, perr_data, start_time
    countdown_end_time = None
    t_data = []
    rpm_data = []
    ma_data = []
    set_data = []
    pwm_data = []
    perr_data = []
    start_time = time.time()

    # Open the serial port
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    except Exception as e:
        print(f"Error opening serial port: {e}")
        return

    time.sleep(2)  # Allow time for the connection to initialize

    # Regular expression to match data lines from the serial port.
    pattern = re.compile(
        r"RPM:\s*([-\d.]+)\s+MA:\s*([-\d.]+)\s+Set:\s*([-\d.]+)\s+PWM:\s*([-\d]+)\s+%Err:\s*([-\d.]+)"
    )

    # Set up the figure and subplots.
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8))
    plt.subplots_adjust(bottom=0.35, top=0.92)
    countdown_text = fig.text(0.5, 0.97, "", ha="center", va="top", fontsize=12)

    line_rpm, = ax1.plot([], [], "o-", label="RPM")
    line_ma, = ax1.plot([], [], "x--", label="MA")
    line_set, = ax1.plot([], [], "s:", label="Set")
    ax1.set_ylabel("RPM")
    ax1.set_title("RPM, MA, and Set RPM vs. Time")
    ax1.legend()
    ax1.grid(True)

    line_pwm, = ax2.plot([], [], "o-", color="magenta", label="PWM")
    ax2.set_ylabel("PWM")
    ax2.set_title("PWM vs. Time")
    ax2.legend()
    ax2.grid(True)

    line_perr, = ax3.plot([], [], "o-", color="red", label="% Err")
    ax3.set_xlabel("Time (s)")
    ax3.set_ylabel("% Err")
    ax3.set_title("Percentage Error vs. Time")
    ax3.legend()
    ax3.grid(True)

    def update(frame):
        global countdown_end_time
        # Read available serial lines.
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

        # Keep only the last 60 seconds of data.
        current_time = time.time() - start_time
        while t_data and t_data[0] < current_time - 60:
            t_data.pop(0)
            rpm_data.pop(0)
            ma_data.pop(0)
            set_data.pop(0)
            pwm_data.pop(0)
            perr_data.pop(0)

        # Update plot lines.
        line_rpm.set_data(t_data, rpm_data)
        line_ma.set_data(t_data, ma_data)
        line_set.set_data(t_data, set_data)
        line_pwm.set_data(t_data, pwm_data)
        line_perr.set_data(t_data, perr_data)

        for ax in (ax1, ax2, ax3):
            ax.set_xlim(max(0, current_time - 60), current_time + 1)
            ax.relim()
            ax.autoscale_view(scalex=False)

        # Update countdown text if a timer is active.
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
        return line_rpm, line_ma, line_set, line_pwm, line_perr

    ani = FuncAnimation(fig, update, interval=100)

    # Set up widgets.
    ax_rpm = plt.axes([0.1, 0.22, 0.3, 0.075])
    global rpm_box
    rpm_box = TextBox(ax_rpm, "RPM")

    ax_time = plt.axes([0.45, 0.22, 0.3, 0.075])
    global time_box
    time_box = TextBox(ax_time, "Time (s)")

    ax_submit = plt.axes([0.8, 0.22, 0.15, 0.075])
    manual_submit_button = Button(ax_submit, "Submit")
    manual_submit_button.on_clicked(manual_submit)

    ax_voice = plt.axes([0.8, 0.1, 0.15, 0.075])
    global voice_button
    voice_button = Button(ax_voice, "Voice Input")
    voice_button.on_clicked(voice_input)

    # Create the Chat Mode button axes
    ax_chat = plt.axes([0.1, 0.1, 0.15, 0.075])

    # Create a rainbow gradient background in the button's axes.
    n = 256  # resolution
    # Create a horizontal gradient array.
    gradient = np.linspace(0, 1, n).reshape(1, n)
    # Display the gradient with the 'rainbow' colormap.
    ax_chat.imshow(gradient, aspect='auto', cmap='rainbow', origin='lower', extent=[0, 1, 0, 1])
    # Make the axes background transparent so the gradient shows.
    ax_chat.patch.set_alpha(0)

    # Create a Button with transparent background to reveal the gradient.
    chat_button = Button(ax_chat, "Chat Mode", color='none', hovercolor='none')
    chat_button.label.set_fontsize(12)  # Optional: adjust text size

    # Set up the button to start chat_mode in a new thread.
    chat_button.on_clicked(lambda event: threading.Thread(target=chat_mode, daemon=True).start())


    plt.show()
    ser.close()

if __name__ == '__main__':
    while True:
        run_session()  # Run one full RPM session.

        # After the session ends (when the plot window is closed), ask if the user wants a new session.
        asyncio.run(speak_text("Do you want to start a new session? Please say yes or no."))
        print("Awaiting response for new session...")
        response = v2t.recognize_speech()
        print("Response received:", response)
        if "yes" in response.lower():
            continue
        else:
            asyncio.run(speak_text("Exiting the program. Goodbye."))
            break