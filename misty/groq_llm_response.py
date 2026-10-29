import sounddevice as sd
import scipy.io.wavfile as wav
import requests
import os
import json
from groq import Groq
from Misty_Shamim_Bhaiyaa.misty.mistyPy.Robot import Robot

# ---------------- CONFIG ----------------
# 16kHz is the gold standard for Whisper cloud models
SAMPLE_RATE = 16000  
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2"  # Local Ollama model
MISTY_IP = "10.10.1.9"
TEMP_AUDIO_FILE = "temp_recording.wav"
RECORDING_DURATION = 5  # Adjusted for natural speech
# ---------------------------------------

# Initialize Misty
misty = Robot(MISTY_IP)

# Initialize Groq client securely from environment variable
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def ask_ollama(user_prompt):
    """Sends the corrected text to local Ollama for Misty's personality response."""
    system_prompt = """
    You are Misty, a friendly personal robot.
    Your responses are sharp, helpful, and lightly witty.
    Keep answers short (1 sentence) and avoid emojis.
    """
    payload = {
        "model": LLM_MODEL,
        "prompt": f"{system_prompt}\nUser: {user_prompt}\nAssistant:",
        "stream": False
    }
    response = requests.post(OLLAMA_URL, json=payload)
    response.raise_for_status()
    return response.json()["response"].strip()

def get_corrected_speech(audio_file):
    """
    Step 1: Transcribes audio with Whisper Large V3 Turbo.
    Step 2: Auto-corrects the transcript with Llama 3.3 70B.
    """
    # 1. High-accuracy transcription
    with open(audio_file, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(audio_file, file.read()),
            model="whisper-large-v3-turbo",  # Latest high-speed model
            response_format="text"
        )
    
    raw_text = transcription.strip()
    if not raw_text:
        return ""

    # 2. Auto-Correction Layer using Llama 3.3 (Replacement for 3.1)
    correction_prompt = f"Correct any typos or grammar in this speech. Output ONLY the text: {raw_text}"
    corrected = client.chat.completions.create(
        model="llama-3.3-70b-versatile",  # Updated supported model
        messages=[{"role": "user", "content": correction_prompt}]
    )
    return corrected.choices[0].message.content.strip()

def listen_once(filename=TEMP_AUDIO_FILE, duration=RECORDING_DURATION):
    """Captures microphone input and saves it to a WAV file via SciPy."""
    print(f"\n🎤 Recording for {duration} seconds... Speak now.")
    
    # Capture mono audio data
    recording = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='int16')
    sd.wait()  # Block until the recording is finished
    
    # Save the file for Groq API processing
    wav.write(filename, SAMPLE_RATE, recording)
    return filename

if __name__ == "__main__":
    print("🤖 Misty is ready for conversation (Cloud-Enhanced).\n")

    while True:
        # Step 1: Record audio to file
        audio_path = listen_once()

        # Step 2: Use Groq for Transcription + Correction
        print("🧠 Processing and correcting speech...")
        user_text = get_corrected_speech(audio_path)
        
        if not user_text:
            print("⚠ No speech detected. Try again.")
            continue

        print(f"👤 User: {user_text}")

        # Step 3: Get the robot's specific personality response from Ollama
        print("📨 Generating response...")
        response = ask_ollama(user_text)

        print(f"🤖 Misty: {response}")
        
        # Step 4: Output response via Misty's speakers
        misty.speak(response)