import os
from dotenv import load_dotenv
from mistyPy.Robot import Robot
from mistyPy.Events import Events
import time
import random

# Load .env file
load_dotenv()

# Get Misty IP from environment
MISTY_IP = os.getenv("MISTY_IP")

# Connect to Misty
misty = Robot(MISTY_IP)


greetings = [
    "Hello! Nice to see you.",
    "Hey there, friend!",
    "Hi! How’s your day going?",
    "Greetings, human!",
    "Hey hey! You look great today!"
]

def greet_and_wave():
    greeting = random.choice(greetings)
    misty.speak(greeting, flush=True)
    misty.move_arm("right", 90)
    time.sleep(1)
    misty.move_arm("right", 0)

    misty.move_head(pitch=-5, roll=0, yaw=0, velocity=50)
    time.sleep(1)
    misty.move_head(pitch=0, roll=0, yaw=0, velocity=50)

def on_head_touch(data):
    try:
        print("Touch event:", data)
        if data["message"]["isContacted"] and data["message"]["sensorPosition"] == "HeadFront":
            greet_and_wave()
    except Exception as e:
        print("Error processing touch event:", e)

misty.register_event(
    event_name="HeadFrontTouch",
    event_type=Events.TouchSensor,
    callback_function=on_head_touch,
    keep_alive=True
)

print("Touch Misty's head (front sensor) to get a greeting!")

try:
    misty.keep_alive()
except KeyboardInterrupt:
    misty.unregister_all_events()
    print("\nStopped.")
