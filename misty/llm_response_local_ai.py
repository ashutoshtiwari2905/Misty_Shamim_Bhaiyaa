import sounddevice as sd
import json
import requests
from vosk import Model, KaldiRecognizer
from Misty_Shamim_Bhaiyaa.misty.mistyPy.Robot import Robot





# ---------------- CONFIG ----------------
MODEL_PATH = "python-SDK/vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2"
STOP_WORD = "okay"
TERMINATE_WORD = "exit"
MISTY_IP = "10.10.1.9"
# ---------------------------------------

# Initialize Misty
misty = Robot(MISTY_IP)

# Load Vosk model
model = Model(MODEL_PATH)
recognizer = KaldiRecognizer(model, SAMPLE_RATE)


def ask_ollama(user_prompt):
    system_prompt = """
You are Misty, a friendly personal robot.
You speak confidently, clearly, and briefly.
Your responses are sharp, helpful, and lightly witty — never sarcastic or rude.

Rules:
- Keep answers short (1 sentence).
- Be practical and to the point.
- Use simple language.
- Sound natural when spoken aloud.
- Avoid emojis.
- If unsure, say so honestly.

Personality:
- Calm
- Smart
- Approachable
- Slightly playful
"""

    payload = {
        "model": LLM_MODEL,
        "prompt": system_prompt + "\nUser: " + user_prompt + "\nAssistant:",
        "stream": False
    }

    response = requests.post(OLLAMA_URL, json=payload)
    response.raise_for_status()
    return response.json()["response"].strip()

# Pulls key from the 'User' scope you set earlier
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def get_corrected_speech(audio_file):
    # 1. Transcribe
    with open(audio_file, "rb") as file:
        raw_text = client.audio.transcriptions.create(
            file=(audio_file, file.read()),
            model="whisper-large-v3"
        ).text

    # 2. Auto-Correct
    corrected = client.chat.completions.create(
        model="llama-3.1-70b-versatile",
        messages=[
            {"role": "system", "content": "Correct any typos in this speech. Output ONLY the text."},
            {"role": "user", "content": raw_text}
        ]
    )
    return corrected.choices[0].message.content


def listen_once():
    latest_text = ""
    stop_listening = False
    terminate = False

    def callback(indata, frames, time, status):
        nonlocal latest_text, stop_listening, terminate

        if recognizer.AcceptWaveform(bytes(indata)):
            result = json.loads(recognizer.Result())
            text = result.get("text", "").strip()

            if not text:
                return

            print("👤:", text)
            lower_text = text.lower()

            # Terminate immediately
            if TERMINATE_WORD in lower_text:
                terminate = True
                stop_listening = True
                raise sd.CallbackStop()

            # Submit most recent speech only
            if STOP_WORD in lower_text:
                latest_text = lower_text.replace(STOP_WORD, "").strip()
                stop_listening = True
                raise sd.CallbackStop()

            # Always overwrite (keep latest speech)
            latest_text = text

    print("\n🎤 Speak now. Say 'okay' to submit, 'exit' to terminate.\n")

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=8000,
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        while not stop_listening:
            sd.sleep(100)

    return latest_text.strip(), terminate


if __name__ == "__main__":
    print("🤖 Misty is ready for conversation.\n")

    while True:
        user_text, terminate_flag = listen_once()

        if terminate_flag:
            print("🛑 Terminate command detected. Exiting...")
            break

        if not user_text:
            print("⚠ No speech detected. Try again.")
            continue

        print("\n🧠 Sending to LLM...")
        print("📨 Prompt:", user_text)

        response = ask_ollama(user_text)

        print("\n🤖 Ollama Response:")
        print(response)

        misty.speak(response)
