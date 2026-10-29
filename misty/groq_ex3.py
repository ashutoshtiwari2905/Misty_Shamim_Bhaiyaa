import os
import requests
import time
from groq import Groq
from Misty_Shamim_Bhaiyaa.misty.mistyPy.Robot import Robot
from Misty_Shamim_Bhaiyaa.misty.mistyPy.Events import Events

# IMPORT THE FIRST FILE AS A MODULE
import Misty_Shamim_Bhaiyaa.misty.push_to_talk2 as push_to_talk2

# ---------------- CONFIG ----------------
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2" 
MISTY_IP = "10.213.148.107"
# ---------------------------------------

is_misty_speaking = False

def tts_callback(data):
    global is_misty_speaking
    is_misty_speaking = False
    print("✅ Misty has finished her response.")

misty = Robot(MISTY_IP)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def ask_ollama(user_prompt):
    system_prompt = "You are Misty, a friendly robot. Keep answers to 1 short sentence."
    payload = {"model": LLM_MODEL, "prompt": f"{system_prompt}\nUser: {user_prompt}\nAssistant:", "stream": False}
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=15)
        return response.json()["response"].strip()
    except Exception:
        return "I am having trouble connecting to my local brain."

def get_corrected_speech(audio_file):
    with open(audio_file, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(audio_file, file.read()),
            model="whisper-large-v3-turbo",
            response_format="text"
        )
    raw_text = transcription.strip()
    if not raw_text: return ""

    corrected = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": f"Correct typos: {raw_text}. Output ONLY text."}]
    )
    return corrected.choices[0].message.content.strip()

if __name__ == "__main__":
    print("🤖 Misty Conversation Started.")
    
    while True:
        # STEP 1: CALL THE FIRST FILE TO GET AUDIO
        audio_path = push_to_talk2.get_audio_input()
        
        if audio_path is None: # If Esc was pressed
            print("Exiting...")
            break

        # STEP 2: THINK
        misty.change_led(0, 0, 255) 
        user_text = get_corrected_speech(audio_path)
        
        if not user_text or len(user_text) < 2:
            continue

        print(f"👤 User: {user_text}")

        # STEP 3: RESPOND
        response = ask_ollama(user_text)
        print(f"🤖 Misty: {response}")
        
        #global is_misty_speaking
        is_misty_speaking = True
        misty.change_led(255, 0, 0) 
        
        misty.register_event(
            event_name="SpeechFinished", 
            event_type=Events.TextToSpeechComplete, 
            callback_function=tts_callback, 
            keep_alive=False
        )
        
        # Use a timestamped ID to avoid "Invalid Subscription" errors
        misty.speak(response, utteranceId=f"id_{int(time.time())}")
        
        print("🔈 Waiting for speech to finish...")
        start_wait = time.time()
        while is_misty_speaking:
            time.sleep(0.1)
            if time.time() - start_wait > 15:
                is_misty_speaking = False
                break
        
        print("✅ Ready for next input.")