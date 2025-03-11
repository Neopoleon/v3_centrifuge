import os
import string
import sounddevice as sd
import numpy as np
import whisper
import scipy.io.wavfile as wav
import time
from df import enhance, init_df

# Settings
SAMPLE_RATE = 48000  # DeepFilterNet requirement
DURATION = 12        # Seconds to record per chunk
FILENAME = "input.wav"
TRIGGER_WORD = "Jeff"  # Trigger word 

# Load the Whisper model on CPU with FP32 explicitly
model = whisper.load_model("base").to("cpu").float()

# Initialize the DeepFilterNet model for denoising (loads the default model)
df_model, df_state, _ = init_df()

def recognize_speech():
    """
    Records audio for a fixed duration, denoises it using DeepFilterNet,
    transcribes it with Whisper, and returns the recognized text in lowercase.
    """
    print("Recording...")
    recording = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype=np.int16)
    sd.wait()
    recording_float = recording.astype(np.float32).squeeze() / 32768.0
    enhanced_audio = enhance(df_model, df_state, recording_float)
    enhanced_int16 = (enhanced_audio * 32768).astype(np.int16)
    wav.write(FILENAME, SAMPLE_RATE, enhanced_int16)
    print("Transcribing...")
    result = model.transcribe(FILENAME)
    recognized_text = result.get('text', '')
    print(f"Recognized Speech: {recognized_text}")
    os.remove(FILENAME)
    return recognized_text.lower()

def listen_for_trigger(trigger_word=TRIGGER_WORD):
    """
    Continuously listens and returns the transcribed sentence as soon as
    the trigger word is detected within the first 20 words.
    """
    print(f"Listening for the trigger word '{trigger_word}' (case-insensitive) in the first 20 words...")
    trigger_word = trigger_word.lower()
    while True:
        text = recognize_speech().strip()
        words = [word.strip(string.punctuation) for word in text.split()]
        if any(word == trigger_word for word in words[:20]):
            print("Trigger phrase detected!")
            return text
        else:
            print("No trigger phrase detected.")
        time.sleep(1)

if __name__ == '__main__':
    detected_sentence = listen_for_trigger()
    print("Detected sentence for further processing:", detected_sentence)
