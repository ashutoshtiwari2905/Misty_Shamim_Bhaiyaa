import sounddevice as sd
import scipy.io.wavfile as wav
import requests
import os
import time
from dotenv import load_dotenv
from groq import Groq
from Misty_Shamim_Bhaiyaa.misty.mistyPy.Robot import Robot
from Misty_Shamim_Bhaiyaa.misty.mistyPy.Events import Events

# ---------------- CONFIG ----------------
SAMPLE_RATE = 16000  
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2" 
MISTY_IP = "10.79.169.107"
TEMP_AUDIO_FILE = "temp_recording.wav"
RECORDING_DURATION = 5  
# ---------------------------------------

# Global flag to track Misty's speech status
is_misty_speaking = False

def tts_callback(data):
    """Triggered automatically when Misty finishes speaking."""
    global is_misty_speaking
    is_misty_speaking = False
    print("✅ Misty has finished her response.")

# Initialize Misty
misty = Robot(MISTY_IP)

# Initialize Groq client
#client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
load_dotenv()

groq_api = os.getenv("groq_api")

if not groq_api:
    raise ValueError("groq_api not found in .env file")

client = Groq(api_key=groq_api)


def ask_ollama(user_prompt):
    """Sends text to local Ollama."""
    system_prompt = "You are Misty, a friendly robot. Keep answers to 1 short sentence."
    payload = {
        "model": LLM_MODEL,
        "prompt": f"{system_prompt}\nUser: {user_prompt}\nAssistant:",
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()["response"].strip()
    except Exception as e:
        return "I am having trouble connecting to my local brain."

def get_corrected_speech(audio_file):
    """Transcribes and corrects speech via Groq Cloud."""
    with open(audio_file, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(audio_file, file.read()),
            model="whisper-large-v3-turbo",
            response_format="text"
        )
    
    raw_text = transcription.strip()
    if not raw_text: return ""

    correction_prompt = f"Correct typos in this speech: {raw_text}. Output ONLY corrected text."
    corrected = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": correction_prompt}]
    )
    return corrected.choices[0].message.content.strip()

def listen_once(filename=TEMP_AUDIO_FILE, duration=RECORDING_DURATION):
    """Captures microphone input."""
    misty.change_led(0, 255, 0) # Green for Listening
    print(f"\n🎤 Listening... ({duration}s)")
    recording = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='int16')
    sd.wait() 
    wav.write(filename, SAMPLE_RATE, recording)
    return filename

if __name__ == "__main__":
    # Declare it here at the start of the main block

    print("🤖 Misty Conversation Started.")
    
    while True:
        # Step 1: Listen
        audio_path = listen_once()

        # Step 2: Think
        misty.change_led(0, 0, 255) 
        user_text = get_corrected_speech(audio_path)
        
        if not user_text or len(user_text) < 2:
            continue

        print(f"👤 User: {user_text}")

        # Step 3: Respond
        response = ask_ollama(user_text)
        print(f"🤖 Misty: {response}")
        
        # --- CORRECTED ORDER ---
        is_misty_speaking = True  # Now this works because 'global' was declared above
        
        misty.change_led(255, 0, 0) 
        
        misty.register_event(
            event_name="SpeechFinished", 
            event_type=Events.TextToSpeechComplete, 
            callback_function=tts_callback, 
            keep_alive=False
        )
        
        misty.speak(response, utteranceId="misty_reply_id")
        
        print("🔈 Waiting for speech to finish...")
        start_wait = time.time()
        while is_misty_speaking:
            time.sleep(0.1)
            if time.time() - start_wait > 15:
                is_misty_speaking = False
                break
        
        print("✅ Ready for next input.")