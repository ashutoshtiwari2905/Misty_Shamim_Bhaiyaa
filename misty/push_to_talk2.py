import sounddevice as sd
import scipy.io.wavfile as wav
import keyboard
import time

# ---------------- CONFIG ----------------
SAMPLE_RATE = 16000  
OUTPUT_FILENAME = "input.wav"
RECORDING_DURATION = 5  
# ---------------------------------------

def get_audio_input():
    """Waits for Ctrl+T, records, and returns the filename."""
    print("⌨️  Waiting for [Ctrl+T] to record | [Esc] to quit")
    
    while True:
        # Check for recording trigger
        if keyboard.is_pressed('ctrl+t'):
            print(f"\n🔴 Recording started for {RECORDING_DURATION}s...")
            recording = sd.rec(
                int(RECORDING_DURATION * SAMPLE_RATE), 
                samplerate=SAMPLE_RATE, 
                channels=1, 
                dtype='int16'
            )
            sd.wait() # Wait for recording to finish
            wav.write(OUTPUT_FILENAME, SAMPLE_RATE, recording)
            print(f"✅ Saved to {OUTPUT_FILENAME}")
            return OUTPUT_FILENAME # Return the file path to the other script
        
        # Check for exit trigger
        if keyboard.is_pressed('esc'):
            return None
            
        time.sleep(0.1)


print(get_audio_input())        

