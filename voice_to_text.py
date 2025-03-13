import os
import string
import sounddevice as sd
import numpy as np
import whisper
import scipy.io.wavfile as wav
import time

# Settings
SAMPLE_RATE = 48000  # Updated to 48kHz
DURATION = 8       # Seconds to record per chunk
FILENAME = "input.wav"
TRIGGER_WORD = "Jeff"  # Trigger word (case-insensitive)

# Load the Whisper model on CPU with FP32 explicitly
model = whisper.load_model("small").to("cpu").float()

def recognize_speech():
    print("Recording...")
    # Record audio for a fixed duration
    recording = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype=np.int16)
    sd.wait()

    # Convert int16 audio to float32 normalized to [-1, 1]
    recording_float = recording.astype(np.float32).squeeze() / 32768.0

    # Convert the audio back to int16
    recording_int16 = (recording_float * 32768).astype(np.int16)

    # Save the recording to a WAV file
    wav.write(FILENAME, SAMPLE_RATE, recording_int16)
    print("Transcribing...")

    # Transcribe the audio using Whisper
    result = model.transcribe(FILENAME)
    recognized_text = result.get('text', '')
    print(f"Recognized Speech: {recognized_text}")

    # Delete the temporary WAV file
    os.remove(FILENAME)
    return recognized_text.lower()

def listen_for_trigger(trigger_word=TRIGGER_WORD):
    """
    Continuously listens and returns the transcribed sentence as soon as the first 20 words contain the trigger word.
    Punctuation is stripped from each word for accurate matching.
    """
    print(f"Listening for the trigger word '{trigger_word}' (case-insensitive) in the first 20 words...")
    trigger_word = trigger_word.lower()  # Ensure trigger word is lowercase for comparison
    while True:
        text = recognize_speech().strip()
        # Remove punctuation from each word
        words = [word.strip(string.punctuation) for word in text.split()]
        # Check if the trigger word is found in the first 20 words
        if any(word == trigger_word for word in words[:20]):
            print("Trigger phrase detected!")
            # Return the full detected sentence for further processing in your pipeline
            return text
        else:
            print("No trigger phrase detected.")
        # Short pause before the next recording cycle
        time.sleep(1)

if __name__ == '__main__':
    detected_sentence = listen_for_trigger()
    # This variable can now be used as input to the rest of your pipeline.
    print("Detected sentence for further processing:", detected_sentence)