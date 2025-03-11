import time
import serial
import subprocess
import v3_centrifuge.voice_to_text as v2t

# Initialize serial connection with Arduino (adjust port as needed)
ser = serial.Serial('/dev/cu.usbmodem744DBD9FCC982', 115200, timeout=1)  
time.sleep(2)  # Allow time for the connection to establish

def listen_and_generate_prompt():
    """
    Listens for a command using v2t.listen_for_trigger() and generates a prompt for phi3.5.
    """
    base_prompt = (
        """
        Reasoned about clear prompt structure for a couple of seconds
        Extract the centrifuge settings from the following request exactly as stated. Ignore any extraneous words (such as names or filler words) that do not affect the numerical values. Do the following:

        Find the integer immediately preceding the term "rpm" (case insensitive) and use that as the RPM value without altering it.
        Identify the time duration mentioned. If the duration is specified in minutes, convert it to seconds; if in seconds, use it as is.
        Return your answer as plain text in the exact format: <RPM> <TIME>, with no extra formatting or characters.
        For example, if the input is "set centrifuge to 2000 rpm for 15 seconds", the output should be: 2000 15

        Request: 
        """
    )
    
    while True:
        command_text = v2t.listen_for_trigger()  # Blocks until a valid command is detected
        if command_text:
            combined_prompt = f"{base_prompt}{command_text}"
            print("Generated Prompt:", combined_prompt)
            return combined_prompt

def get_phi3_response(prompt):
    """
    Calls the phi3.5 model via Ollama to extract RPM and Timer values.
    """
    result = subprocess.run(
        ['ollama', 'run', 'phi3.5', prompt],  # Calls phi3.5 model
        capture_output=True,
        text=True
    )
    
    output = result.stdout.strip()
    print("Raw output:", output)  # Debugging step
    
    rpm, timer = None, None
    try:
        parts = output.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            rpm = int(parts[0])
            timer = int(parts[1])
        else:
            print("Error: Unexpected response format:", output)
    except Exception as e:
        print("Error extracting RPM and Timer:", e)
    
    return {"rpm": rpm, "timer": timer}

def process_command():
    """
    Listens for a voice command, generates a prompt, queries phi3.5, and parses RPM and Timer values.
    """
    combined_prompt = listen_and_generate_prompt()
    phi3_response = get_phi3_response(combined_prompt)
    return phi3_response

def send_data_to_arduino(rpm, timer):
    """
    Sends RPM and Timer values to Arduino over UART.
    """
    if rpm is not None and timer is not None:
        data = f"{rpm},{timer}\n"
        ser.write(data.encode())  # Encode and send over UART
        print(f"Sent to Arduino: {data.strip()}")
    else:
        print("Invalid RPM or Timer values, not sending.")

def receive_feedback():
    """
    Reads and prints feedback from Arduino.
    """
    while True:
        if ser.in_waiting > 0:
            response = ser.readline().decode().strip()
            print(f"Arduino: {response}")
            if response == "ACK":
                print("Arduino acknowledged receipt.")
            elif response == "Complete":
                print("Centrifuge cycle completed.")
                break

# Main Execution
if __name__ == '__main__':
    result = process_command()  # Get parsed RPM and Timer
    print("Received response:", result)

    if result["rpm"] is not None and result["timer"] is not None:
        send_data_to_arduino(result["rpm"], result["timer"])  # Send to Arduino
        receive_feedback()  # Wait for Arduino's response
    else:
        print("Invalid RPM/Timer values received, retrying.")
