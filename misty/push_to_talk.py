import sounddevice as sd
import scipy.io.wavfile as wav
import keyboard
import time

# ---------------- CONFIG ----------------
SAMPLE_RATE = 16000  
OUTPUT_FILENAME = "input.wav"
RECORDING_DURATION = 5  # Seconds to record after pressing keys
# ---------------------------------------

def record_audio():
    print(f"\n🔴 Recording started for {RECORDING_DURATION} seconds...")
    
    # Capture audio data
    # dtype='int16' ensures compatibility with most speech engines
    recording = sd.rec(
        int(RECORDING_DURATION * SAMPLE_RATE), 
        samplerate=SAMPLE_RATE, 
        channels=1, 
        dtype='int16'
    )
    
    sd.wait()  # Wait until recording is finished
    wav.write(OUTPUT_FILENAME, SAMPLE_RATE, recording)
    
    print(f"✅ Recording saved to {OUTPUT_FILENAME}")
    print("Press Ctrl+T to record again, or Esc to exit.")

if __name__ == "__main__":
    print("⌨️  Program Running...")
    print("Hotkeys: [Ctrl+T] to record | [Esc] to quit")

    # This creates a loop that waits for the hotkey
    while True:
        try:
            # Check if the user pressed the combination
            if keyboard.is_pressed('ctrl+t'):
                record_audio()
                # Short sleep to prevent multiple triggers from one press
                time.sleep(0.5) 
            
            # Allow the user to exit the program gracefully
            if keyboard.is_pressed('esc'):
                print("Exiting...")
                break
                
            time.sleep(0.01) # Small sleep to reduce CPU usage
            
        except KeyboardInterrupt:
            break