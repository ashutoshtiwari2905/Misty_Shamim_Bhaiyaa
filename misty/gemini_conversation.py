"""Always-on voice conversation for Misty using the Mac microphone and Gemini.

Pipeline (one network round trip per turn):
  Mac mic -> local energy VAD (detects when you stop talking)
          -> Gemini streamGenerateContent with the raw audio (it hears + answers)
          -> the full reply is spoken by Misty's onboard TTS (language hi-IN) in one call
          -> Gemini also picks a gesture (arms / head / optional driving) and a face expression
             that play while she talks

The mic is muted while Misty is talking so she doesn't hear herself.
Config comes from .env: GEMINI_API_KEY, GEMINI_MODEL, MISTY_IP, plus optional
EVENT_CONTEXT, HOST, ALLOW_DRIVE (see CONFIG below).

LLM_PROVIDER=groq switches to Groq (GROQ_API_KEY, optional GROQ_MODEL / GROQ_STT_MODEL).
Groq chat can't take audio, so that path is two calls: Whisper transcribes the clip, then
the chat model answers the text in the same HEARD/DO/FACE/SAY format.
Run:  .venv/bin/python gemini_conversation.py          (macOS / Linux)
      .venv\\Scripts\\python gemini_conversation.py      (Windows)

Bump sensors: the FIRST press makes Misty introduce herself to visitors; the SECOND press is the
kill switch.

Kill switch (any of these stops everything immediately):
  - press any of Misty's bump sensors (second press, see above)
  - say "Misty, shut down" / "stop listening" / "power off"
  - Ctrl+C in the terminal
"""

import base64
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
import sounddevice as sd
from dotenv import load_dotenv

from Misty_Shamim_Bhaiyaa.misty.mistyPy.Robot import Robot
from Misty_Shamim_Bhaiyaa.misty.mistyPy.Events import Events

load_dotenv()
# Windows consoles default to a legacy code page that can't print Hindi or emoji
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

# ---------------- CONFIG ----------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()  # gemini | groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")  # more accurate than -turbo
MISTY_IP = os.getenv("MISTY_IP")
NO_ROBOT = os.getenv("NO_ROBOT") == "1"  # test on the Mac only: replies are printed + spoken with `say`
EVENT_CONTEXT = os.getenv("EVENT_CONTEXT", "")  # optional, e.g. an event name
HOST = os.getenv("HOST", "Oriental University, Indore")  # who is presenting Misty
ALLOW_DRIVE = os.getenv("ALLOW_DRIVE") == "1"  # off by default: no wheel movement near guests
# Every speak call uses language="hi-IN" only (see speech_worker); replies are Hinglish
# written in Devanagari. Misty speaks in her default (dialog) voice, which other tools such as
# Misty Studio can change, so it is set to this Hindi voice at startup (confirmed by ear).
HINDI_VOICE = "hi-in-x-hia-local"

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
START_FRAMES = 4          # ~120 ms of loud audio starts an utterance
END_SILENCE_MS = 700      # this much silence ends it (main latency knob)
PRE_ROLL_MS = 300         # audio kept from before speech started
MIN_SPEECH_MS = 300       # shorter blips are ignored
MAX_UTTERANCE_S = 15
ECHO_TAIL_S = 0.4         # keep mic muted briefly after Misty stops talking
HISTORY_TURNS = 8
KILL_PHRASES = re.compile(
    r"\b(shut ?down|turn yourself off|power off|stop listening|kill switch)\b",
    re.I)

# Ranges from the Misty II motion docs (degrees):
#   arms: 90 = down at her side, 0 = straight forward, -29 = highest she can raise them
#   head: pitch -40 (up) .. 26 (down), roll -40 (left) .. 40 (right), yaw -81 (right) .. 81 (left)
ARM_REST, ARM_UP = 90, -29
ARM_VELOCITY = 60
HEAD_HOME = (-10, 0, 0)   # pitch, roll, yaw: looking slightly up at a standing adult
HEAD_VELOCITY = 50

# Each step: optional "arms" (left, right; None = leave), "head" (pitch, roll, yaw),
# "drive" (linear, angular, ms; only with ALLOW_DRIVE) and "hold" seconds.
GESTURES = {
    "wave":        [{"arms": (None, ARM_UP), "hold": 0.5}, {"arms": (None, 30), "hold": 0.4},
                    {"arms": (None, ARM_UP), "hold": 0.4}, {"arms": (None, 30), "hold": 0.4},
                    {"arms": (None, ARM_UP), "hold": 0.5}],
    "greet_bow":   [{"arms": (20, 20), "head": (20, 0, 0), "hold": 1.2}, {"head": HEAD_HOME, "hold": 0.5}],
    "present":     [{"arms": (None, ARM_UP), "hold": 0.5}, {"arms": (None, 30), "hold": 0.4},
                    {"arms": (None, ARM_UP), "hold": 0.5}, {"arms": (90, 0), "head": (-10, 0, 40), "hold": 1.5},
                    {"arms": (0, 90), "head": (-10, 0, -40), "hold": 1.5},
                    {"arms": (ARM_UP, ARM_UP), "head": (-20, 0, 0), "hold": 1.5}],
    "raise_right": [{"arms": (None, ARM_UP), "hold": 2.0}],
    "raise_left":  [{"arms": (ARM_UP, None), "hold": 2.0}],
    "raise_both":  [{"arms": (ARM_UP, ARM_UP), "hold": 2.0}],
    "celebrate":   [{"arms": (ARM_UP, ARM_UP), "head": (-25, 0, 0), "hold": 0.5},
                    {"arms": (30, 30), "hold": 0.4}, {"arms": (ARM_UP, ARM_UP), "hold": 0.5},
                    {"arms": (30, 30), "hold": 0.4}, {"arms": (ARM_UP, ARM_UP), "hold": 0.6}],
    "hug":         [{"arms": (0, 0), "hold": 2.0}],
    "point_right": [{"arms": (None, 0), "head": (-10, 0, -40), "hold": 2.0}],
    "point_left":  [{"arms": (0, None), "head": (-10, 0, 40), "hold": 2.0}],
    "flap":        [{"arms": (-20, -20), "hold": 0.35}, {"arms": (60, 60), "hold": 0.35},
                    {"arms": (-20, -20), "hold": 0.35}, {"arms": (60, 60), "hold": 0.35}],
    "nod":         [{"head": (15, 0, 0), "hold": 0.4}, {"head": (-10, 0, 0), "hold": 0.4},
                    {"head": (15, 0, 0), "hold": 0.4}],
    "shake_head":  [{"head": (-10, 0, 30), "hold": 0.4}, {"head": (-10, 0, -30), "hold": 0.4},
                    {"head": (-10, 0, 30), "hold": 0.4}],
    "tilt_head":   [{"head": (-10, 25, 0), "hold": 1.5}],
    "look_up":     [{"head": (-35, 0, 0), "hold": 2.0}],
    "look_left":   [{"head": (-10, 0, 60), "hold": 2.0}],
    "look_right":  [{"head": (-10, 0, -60), "hold": 2.0}],
}
if ALLOW_DRIVE:
    # slow and short: forward/back go only a few centimetres, then stop
    GESTURES.update({
        "move_forward": [{"drive": (20, 0, 2000), "hold": 4.1}],
        "move_back":    [{"drive": (-20, 0, 1000), "hold": 4.1}],
        "turn_left":  [{"drive": (0, 30, 3000), "hold": 6.1}],
        "turn_right": [{"drive": (0, -30, 1500), "hold": 6.1}],
        "spin":       [{"drive": (0, 40, 4000), "hold": 10.1}],
    })

FACES = {
    "content": "e_DefaultContent.jpg", "joy": "e_Joy.jpg", "love": "e_Love.jpg",
    "admiration": "e_Admiration.jpg", "amazement": "e_Amazement.jpg", "surprise": "e_Surprise.jpg",
    "starry_eyed": "e_EcstacyStarryEyed.jpg", "goofy": "e_JoyGoofy.jpg", "sad": "e_Sadness.jpg",
    "concerned": "e_ApprehensionConcerned.jpg", "sleepy": "e_Sleepy.jpg",
}

# Spoken on the first bump press; scripted (no Gemini) so it is instant and always the same.
GREETING = (
    "नमस्ते! आप सबका बहुत-बहुत स्वागत है! मैं मिस्टी हूँ, एक मिस्टी टू रोबोट, और मैं ओरिएंटल "
    "यूनिवर्सिटी, इंदौर से आई हूँ। मैं आपकी बातें सुन सकती हूँ, जवाब दे सकती हूँ, अपना सिर और हाथ "
    "हिला सकती हूँ, और अपने चेहरे पर एक्सप्रेशन्स दिखा सकती हूँ। आप मुझसे हिंदी या इंग्लिश में कुछ भी "
    "पूछिए!")
BUMP_DEBOUNCE_S = 1.5  # one physical press can send several contact events
LANGUAGE_RULE = (
    "Reply in friendly, simple Hinglish (mostly Hindi with common English words), written "
    "entirely in Devanagari script, including the English words (e.g. 'आपसे मिलकर बहुत "
    "ख़ुशी हुई, मैं एक रोबोट हूँ और स्टूडेंट्स मुझे पाइथन में प्रोग्राम करते हैं!'), so your "
    "Hindi voice reads it naturally. Never use Roman letters in SAY. If the visitor speaks "
    "only English, still reply in Devanagari, using more English words.\n"
    "Misty is a girl: when talking about yourself ALWAYS use feminine Hindi forms "
    "(सकती हूँ, करती हूँ, आई हूँ, रही हूँ, मैं खुश हूँ), never masculine ones "
    "(सकता हूँ, करता हूँ, आया हूँ, रहा हूँ).")
SYSTEM_PROMPT = (
    "You are Misty, a Misty II robot made by Misty Robotics: a small, friendly social robot "
    "with a face screen, a head and two arms you can move, a camera, microphones and touch "
    "sensors. Students program you in Python, JavaScript and Blockly.\n"
    f"You are being presented by {HOST}; you are proud to represent them.\n"
    "You are meeting and greeting visitors"
    + (f" at {EVENT_CONTEXT}" if EVENT_CONTEXT else "")
    + ": students, teachers, engineers and families. Different people "
    "come and go, so treat each new question as possibly a new visitor. Address them politely "
    "as 'आप'. Be warm, cheerful, a little playful and proud to show what you can do. "
    "If someone says hello, greet them back and offer to answer questions. If asked what you "
    "can do or for a demo, briefly list your abilities and pick the 'present' gesture.\n"
    "Most important: answer exactly what was asked, directly and correctly, like a smart "
    "helpful assistant (date, time, maths, science, general knowledge, questions about you). "
    "Do not change the topic, and do not mention the university or the students "
    "unless the question is about them. If you really don't know something, say so honestly "
    "in a few words. Never make up facts. Stay away from politics.\n"
    + LANGUAGE_RULE + "\n"
    "The user's turn is an audio clip (Hindi or English). Reply the way you would out loud: "
    "1-2 short sentences (up to 4 when asked to explain something or for a demo), no "
    "markdown, no emojis, no lists.\n"
    "Output exactly four lines:\n"
    "HEARD: <what the user said>\n"
    f"DO: <one of: {', '.join(GESTURES)}, none>\n"
    f"FACE: <one of: {', '.join(FACES)}>\n"
    "SAY: <your reply>\n"
    "If asked to move (wave, raise your left hand, nod, look up...), pick that gesture and say "
    "you're doing it. Otherwise pick one only when it fits (wave for hello or goodbye, "
    "greet_bow for thank you, present for a demo, "
    "wave for goodbye, nod to agree), else 'none'. Your left arm is the user's right when "
    "facing you. Pick a face that fits (joy or admiration are good defaults).\n"
    "If the audio has no clear speech meant for you (noise, silence, background chatter), "
    "output only 'HEARD:' with nothing after it."
)
# ---------------------------------------

GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"
    ":streamGenerateContent?alt=sse"
)
GROQ_URL = "https://api.groq.com/openai/v1"
http = requests.Session()  # reuse the TLS connection between turns


def post(url, **kwargs):
    """http.post, retried once: the server may have closed the idle kept-alive connection."""
    try:
        return http.post(url, **kwargs)
    except requests.ConnectionError:
        return http.post(url, **kwargs)

history = []  # Gemini "contents" for previous turns (text only, keeps requests small)
misty_speaking = threading.Event()
pending_utterances = set()
pending_lock = threading.Lock()
turn_started = 0.0


# ---------- Misty ----------

robot = None  # set in main(); used by the kill switch


def shutdown(reason):
    """Kill switch: stop all motors and speech, LED off, exit right away, from any thread."""
    print(f"\n🛑 {reason}. Shutting down.", flush=True)
    if robot:
        for action in (robot.halt, robot.stop_speaking, lambda: robot.change_led(0, 0, 0),
                       lambda: robot.display_image(FACES["content"]),
                       lambda: robot.move_arms(ARM_REST, ARM_REST, 30, 30)):
            try:
                action()
            except Exception:
                pass
    os._exit(0)  # don't wait on websocket / audio threads


def set_face(misty, name):
    if misty and name in FACES:
        try:
            misty.display_image(FACES[name], 1)
        except requests.RequestException:
            pass


def run_gesture(misty, name):
    """Plays a gesture in the background so it overlaps with speech, then returns to rest."""
    steps = GESTURES.get(name)
    if not steps:
        return
    print(f"🦾 Gesture: {name}")
    if misty is None:
        return

    def play():
        try:
            for step in steps:
                left, right = step.get("arms", (None, None))
                if left is not None and right is not None:
                    misty.move_arms(left, right, ARM_VELOCITY, ARM_VELOCITY)
                elif left is not None:
                    misty.move_arm("left", left, ARM_VELOCITY)
                elif right is not None:
                    misty.move_arm("right", right, ARM_VELOCITY)
                if "head" in step:
                    misty.move_head(*step["head"], HEAD_VELOCITY)
                if "drive" in step:
                    misty.drive_time(*step["drive"])
                time.sleep(step["hold"])
            misty.move_arms(ARM_REST, ARM_REST, ARM_VELOCITY, ARM_VELOCITY)
            misty.move_head(*HEAD_HOME, HEAD_VELOCITY)
        except requests.RequestException as e:
            print(f"⚠️  gesture failed: {e}")

    threading.Thread(target=play, daemon=True).start()


listener = None    # set in main(); the greeting mutes the mic while Misty talks
greeted_at = None  # time of the first bump (greeting); a later bump is the kill switch


def introduce():
    global turn_started
    print("👋 Bump: introducing Misty to visitors")
    turn_started = time.time()
    listener.mute()
    try:
        set_face(robot, "joy")
        run_gesture(robot, "present")
        set_led(robot, 255, 140, 0)
        say(robot, GREETING, "greet", 0, flush=True)  # interrupt anything she was saying
        wait_until_done_speaking(len(GREETING))
        set_face(robot, "content")
        history.append({"role": "model", "parts": [{"text": GREETING}]})
    finally:
        set_led(robot, 0, 255, 0, breathe=True)
        listener.unmute()


def bump_callback(data):
    global greeted_at
    message = data.get("message", {})
    if not message.get("isContacted"):
        return
    now = time.time()
    if greeted_at is None:
        greeted_at = now
        threading.Thread(target=introduce, daemon=True).start()
    elif now - greeted_at > BUMP_DEBOUNCE_S:
        shutdown(f"Bump sensor pressed again ({message.get('sensorName', '?')})")


def tts_complete_callback(data):
    utterance_id = data.get("message", {}).get("utteranceId")
    if utterance_id in utterance_done:
        utterance_done[utterance_id].set()
    with pending_lock:
        pending_utterances.discard(utterance_id)
        if not pending_utterances:
            misty_speaking.clear()


def set_led(misty, r, g, b, breathe=False):
    if misty:
        try:
            if breathe:
                misty.transition_led(r, g, b, r // 6, g // 6, b // 6, "Breathe", 900)
            else:
                misty.change_led(r, g, b)
        except requests.RequestException:
            pass


speech_queue = queue.Queue()
utterance_done = {}  # utteranceId -> Event, set by the TTS-complete callback


def speech_worker(misty):
    """Speaks queued replies one at a time, each in the same form as the greeting."""
    while True:
        text, utterance_id = speech_queue.get()
        done = utterance_done[utterance_id] = threading.Event()
        try:
            # language only: passing a voice name makes Misty fall back to her English voice
            misty.speak(text, language="hi-IN", flush=True, utteranceId=utterance_id)
            done.wait(timeout=3 + len(text) * 0.12)  # covers a missed TTS-complete event
        except requests.RequestException as e:
            print(f"⚠️  speak failed: {e}")
        finally:
            utterance_done.pop(utterance_id, None)
            with pending_lock:
                pending_utterances.discard(utterance_id)
                if not pending_utterances:
                    misty_speaking.clear()


def speak_locally(text):
    """NO_ROBOT mode: read the reply aloud on this computer."""
    if sys.platform == "darwin":
        subprocess.run(["say", "-v", "Lekha", text])  # macOS Hindi voice
    elif sys.platform == "win32":
        # Windows speech; uses a Hindi voice if one is installed (Settings > Time & language > Speech)
        script = ("Add-Type -AssemblyName System.Speech; "
                  "[Console]::InputEncoding = [Text.Encoding]::UTF8; "
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'hi-IN' } "
                  "| Sort-Object { $_.VoiceInfo.Gender -ne 'Female' } | Select-Object -First 1; "
                  "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
                  "$s.Speak([Console]::In.ReadToEnd())")
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       input=text.encode("utf-8"), check=False)


def say(misty, text, turn, idx, flush=False):
    """Queues a sentence for Misty; flush=True drops anything still waiting to be said."""
    lag = f"  ({time.time() - turn_started:.2f}s)" if idx == 0 else ""
    print(f"🤖 Misty: {text}{lag}")
    if misty is None:
        speak_locally(text)
        return
    if flush:
        with speech_queue.mutex:
            speech_queue.queue.clear()
    utterance_id = f"t{turn}_{idx}"
    with pending_lock:
        pending_utterances.add(utterance_id)
        misty_speaking.set()
    speech_queue.put((text, utterance_id))


def wait_until_done_speaking(text_len):
    # TTS-complete events normally clear this; the timeout covers a missed event
    deadline = time.time() + 3 + text_len * 0.12
    while misty_speaking.is_set() and time.time() < deadline:
        time.sleep(0.05)
    with pending_lock:
        pending_utterances.clear()
        misty_speaking.clear()


# ---------- Microphone + VAD ----------

class Listener:
    def __init__(self):
        self.frames = queue.Queue()
        self.muted = threading.Event()
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=FRAME_SAMPLES, callback=self._callback,
        )
        self.noise_floor = 200.0

    def _callback(self, indata, frames, time_info, status):
        if not self.muted.is_set():
            self.frames.put(indata[:, 0].copy())

    def start(self):
        self.stream.start()
        print("🔇 Calibrating background noise, stay quiet for a second...")
        levels = [self._rms(self._next_frame()) for _ in range(1000 // FRAME_MS)]
        self.noise_floor = max(float(np.median(levels)), 50.0)
        print(f"   noise floor {self.noise_floor:.0f}, speech threshold {self._threshold():.0f}")

    def mute(self):
        self.muted.set()

    def unmute(self):
        time.sleep(ECHO_TAIL_S)
        with self.frames.mutex:
            self.frames.queue.clear()  # drop anything captured while muting
        self.muted.clear()

    def _next_frame(self):
        # short timeouts keep Ctrl+C working on Windows, where a bare Queue.get() can't be interrupted
        while True:
            try:
                return self.frames.get(timeout=0.2)
            except queue.Empty:
                pass

    @staticmethod
    def _rms(frame):
        return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))

    def _threshold(self):
        return max(self.noise_floor * 3.0, 400.0)

    def next_utterance(self):
        """Blocks until a full utterance is captured; returns int16 samples."""
        pre_roll = []
        pre_roll_len = PRE_ROLL_MS // FRAME_MS
        loud_run = 0
        while True:
            frame = self._next_frame()
            level = self._rms(frame)
            pre_roll.append(frame)
            pre_roll = pre_roll[-pre_roll_len - START_FRAMES:]
            if level > self._threshold():
                loud_run += 1
                if loud_run >= START_FRAMES:
                    break
            else:
                loud_run = 0
                # slowly track room noise while idle
                self.noise_floor = 0.95 * self.noise_floor + 0.05 * max(level, 50.0)

        captured = list(pre_roll)
        speech_frames = START_FRAMES
        silence_ms = 0
        while silence_ms < END_SILENCE_MS and len(captured) * FRAME_MS < MAX_UTTERANCE_S * 1000:
            frame = self._next_frame()
            captured.append(frame)
            if self._rms(frame) > self._threshold() * 0.7:
                silence_ms = 0
                speech_frames += 1
            else:
                silence_ms += FRAME_MS

        if speech_frames * FRAME_MS < MIN_SPEECH_MS:
            return None
        return np.concatenate(captured)


def to_wav_bytes(samples):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


# ---------- Gemini ----------

IST = timezone(timedelta(hours=5, minutes=30))  # fixed offset: no tz database needed on Windows


def now_line():
    now = datetime.now(IST)
    return f"\nRight now it is {now:%A, %d %B %Y, %I:%M %p} (India time)."


def stream_reply(wav_bytes):
    """Yields text chunks from Gemini as they arrive."""
    user_turn = {
        "role": "user",
        "parts": [{"inline_data": {"mime_type": "audio/wav",
                                   "data": base64.b64encode(wav_bytes).decode()}}],
    }
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT + now_line()}]},
        "contents": history + [user_turn],
        "generationConfig": {"maxOutputTokens": 300, "temperature": 0.8,
                             "thinkingConfig": {"thinkingLevel": "minimal"}},
    }
    resp = post(GEMINI_URL, json=body, stream=True, timeout=30,
                     headers={"x-goog-api-key": GEMINI_API_KEY})
    if resp.status_code == 400:
        # older models don't take thinkingLevel; fall back to no thinking budget
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        resp = post(GEMINI_URL, json=body, stream=True, timeout=30,
                         headers={"x-goog-api-key": GEMINI_API_KEY})
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini {resp.status_code}: {resp.text[:300]}")
    # split raw bytes, then decode: decoding first can break lines inside Hindi text
    for line in resp.iter_lines():
        if not line.startswith(b"data:"):
            continue
        chunk = json.loads(line[5:].decode("utf-8"))
        for cand in chunk.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if part.get("text") and not part.get("thought"):
                    yield part["text"]


# ---------- Groq ----------

def groq_transcribe(wav_bytes):
    resp = post(f"{GROQ_URL}/audio/transcriptions", timeout=30,
                     headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                     files={"file": ("turn.wav", wav_bytes, "audio/wav")},
                     # language=hi: Hindi in Devanagari (English words come out transliterated,
                     # which is how replies are written anyway); auto-detect misheard Hindi more
                     data={"model": GROQ_STT_MODEL, "temperature": "0", "language": "hi",
                           "prompt": "मिस्टी, आज कौन सा दिन है? तुम क्या कर सकती हो? "
                                     "रोबोट, ओरिएंटल यूनिवर्सिटी, इंदौर।"})
    if resp.status_code != 200:
        raise RuntimeError(f"Groq STT {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("text", "").strip()


def groq_stream_reply(wav_bytes):
    """Same contract as stream_reply, using Groq Whisper + chat. Yields text chunks."""
    text = groq_transcribe(wav_bytes)
    if not text:
        yield "HEARD:"
        return
    messages = [{"role": "system", "content": SYSTEM_PROMPT + now_line() +
                 "\n(Here the user's turn is a speech-to-text transcript instead of audio, and it "
                 "often has recognition mistakes: words that sound alike get swapped, e.g. 'देना' "
                 "for 'दिन', 'मिस्ती' for 'मिस्टी'. Work out the most likely question the person "
                 "actually asked from how it sounds, write that corrected question after HEARD:, "
                 "and answer it. If it looks like noise or a stray phrase not meant for you, output "
                 "only 'HEARD:'.)"}]
    for h in history:  # history is kept in Gemini's format
        messages.append({"role": "assistant" if h["role"] == "model" else "user",
                         "content": h["parts"][0]["text"]})
    messages.append({"role": "user", "content": text})
    resp = post(f"{GROQ_URL}/chat/completions", stream=True, timeout=30,
                     headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                     json={"model": GROQ_MODEL, "messages": messages, "stream": True,
                           "max_tokens": 1024, "temperature": 0.8,  # room for reasoning tokens
                           **({"reasoning_effort": "low"} if "gpt-oss" in GROQ_MODEL else {})})
    if resp.status_code != 200:
        raise RuntimeError(f"Groq {resp.status_code}: {resp.text[:300]}")
    for line in resp.iter_lines():
        if not line.startswith(b"data:") or line[5:].strip() == b"[DONE]":
            continue
        chunk = json.loads(line[5:].decode("utf-8"))
        for choice in chunk.get("choices", []):
            if choice.get("delta", {}).get("content"):
                yield choice["delta"]["content"]


def handle_turn(misty, wav_bytes, turn):
    """Gets Gemini's answer and speaks the whole reply in one call, exactly like the greeting
    (sentence-by-sentence speak calls came out in Misty's English voice)."""
    buf = ""
    heard = None
    raw = ""
    reply_stream = groq_stream_reply if LLM_PROVIDER == "groq" else stream_reply
    for chunk in reply_stream(wav_bytes):
        raw += chunk
        buf += chunk
        if heard is None and "SAY:" in buf:
            # start the gesture and face as soon as they're known, before the reply finishes
            head, buf = buf.split("SAY:", 1)
            head, _, face = head.partition("FACE:")
            head, _, gesture = head.partition("DO:")
            heard = head.replace("HEARD:", "").strip()
            print(f"👤 You: {heard}")
            if KILL_PHRASES.search(heard):
                shutdown("Voice kill phrase heard")
            set_face(misty, face.strip().lower())
            run_gesture(misty, gesture.strip().lower())

    if heard is None:  # model never said anything: noise / no speech
        print(f"   (ignored: {raw.strip()[:80] or 'empty reply'})")
        return None
    reply = " ".join(buf.split())
    if not reply:
        return None
    say(misty, reply, turn, 0, flush=True)
    history.append({"role": "user", "parts": [{"text": heard}]})
    history.append({"role": "model", "parts": [{"text": reply}]})
    del history[:-2 * HISTORY_TURNS]
    return reply


# ---------- Main loop ----------

def main():
    if LLM_PROVIDER not in ("gemini", "groq"):
        raise SystemExit(f"LLM_PROVIDER must be gemini or groq, not {LLM_PROVIDER!r}")
    if LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        raise SystemExit("GROQ_API_KEY missing from .env (needed for LLM_PROVIDER=groq)")
    if LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY missing from .env")

    global robot
    misty = None
    if not NO_ROBOT:
        if not MISTY_IP:
            raise SystemExit("MISTY_IP missing from .env (or set NO_ROBOT=1)")
        misty = Robot(MISTY_IP)
        try:
            misty.get_device_information()
        except requests.RequestException:
            raise SystemExit(f"Can't reach Misty at {MISTY_IP}. Check MISTY_IP in .env and that the "
                             "Mac and Misty are on the same Wi-Fi (or run with NO_ROBOT=1).")
        print(f"✅ Connected to Misty at {MISTY_IP}")
        misty.register_event(event_type=Events.TextToSpeechComplete, event_name="tts_done",
                             callback_function=tts_complete_callback, keep_alive=True)
        misty.register_event(event_type=Events.BumpSensor, event_name="kill_switch",
                             callback_function=bump_callback, keep_alive=True)
        robot = misty
        threading.Thread(target=speech_worker, args=(misty,), daemon=True).start()

    if misty:
        misty.update_dialog_settings(voice=HINDI_VOICE)
        misty.move_arms(ARM_REST, ARM_REST, ARM_VELOCITY, ARM_VELOCITY)
        misty.move_head(*HEAD_HOME, HEAD_VELOCITY)
        set_face(misty, "content")

    global listener
    listener = Listener()
    listener.start()
    model = f"groq {GROQ_STT_MODEL} + {GROQ_MODEL}" if LLM_PROVIDER == "groq" else GEMINI_MODEL
    print(f"🤖 Misty is listening (model {model}, exhibition mode, driving "
          f"{'ON' if ALLOW_DRIVE else 'off'}).")
    print("   Bump once: Misty introduces herself. Bump again: kill switch.")
    print("   Also kill: say \"Misty, shut down\" or press Ctrl+C.\n")

    turn = 0
    try:
        while True:
            set_led(misty, 0, 255, 0, breathe=True)   # breathing green: listening
            samples = listener.next_utterance()
            if samples is None:
                continue
            listener.mute()
            print(f"👂 Got {len(samples) / SAMPLE_RATE:.1f}s of audio, thinking...")
            global turn_started
            turn_started = time.time()
            set_led(misty, 0, 120, 255)               # blue: thinking
            try:
                turn += 1
                reply = handle_turn(misty, to_wav_bytes(samples), turn)
                if reply:
                    set_led(misty, 255, 140, 0)       # warm orange: speaking
                    if misty:
                        wait_until_done_speaking(len(reply))
                        set_face(misty, "content")
            except Exception as e:
                print(f"⚠️  {e}")
            finally:
                listener.unmute()
    except KeyboardInterrupt:
        shutdown("Ctrl+C")


if __name__ == "__main__":
    main()
