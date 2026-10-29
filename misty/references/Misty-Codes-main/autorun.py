import os
from dotenv import load_dotenv
from mistyPy.Robot import Robot
from mistyPy.Events import Events
import time
# Load .env file
load_dotenv()

# Get Misty IP from environment
MISTY_IP = os.getenv("MISTY_IP")

# Connect to Misty
misty = Robot(MISTY_IP)

# ==== BOOT GREETING ====
misty.display_image("e_Joy2.jpg")
misty.change_led(0, 255, 0)
misty.speak("Hey, hello there! I am ready to meet you.", 1, voice="English 12 (India)")
time.sleep(2)

# ==== START FACE RECOGNITION ====
misty.start_face_recognition()

# Track last seen faces
last_seen = {}
COOLDOWN = 10   # seconds before Misty greets the same face again

def on_face(data):
    global last_seen
    label = data["message"].get("label", "unknown person")
    now = time.time()

    if label not in last_seen or now - last_seen[label] > COOLDOWN:
        last_seen[label] = now

        if label == "unknown person":
            misty.display_image("e_Surprise.jpg")
            misty.transition_led(255, 0, 0, 0, 0, 255, "Blink", 200)
            misty.speak("I see someone new.", 1, voice="English 12 (India)")
        else:
            misty.display_image("e_Joy2.jpg")
            misty.change_led(0, 255, 0)
            misty.speak(f"Hi {label}!", 1, voice="English 12 (India)")
            # Wave gesture
            misty.move_arms(80, -80, 50, 50)
            time.sleep(0.8)
            misty.move_arms(0, 0, 50, 50)
    else:
        print(f"Skipping {label}, still on cooldown.")

# Register face recognition event (ask Misty to send 'label' field)
misty.register_event(
    event_name="face_recognition_event",
    event_type=Events.FaceRecognition,
    callback_function=on_face,
    keep_alive=True,
)

# Optional stop with bump
def stop_on_bump(evt):
    if evt["message"]["sensorId"] == "bfl" and evt["message"]["isContacted"]:
        misty.unregister_all_events()
        misty.stop_face_recognition()
        misty.change_led(0, 0, 0)
        misty.speak("Goodbye! Stopping face recognition.", 1, voice="English 12 (India)")
        print("Stopped face recognition.")

misty.register_event(
    event_name="bump_stop",
    event_type=Events.BumpSensor,
    callback_function=stop_on_bump,
    keep_alive=True
)

print("✅ Misty auto-greet + face recognition running...")
misty.keep_alive()
