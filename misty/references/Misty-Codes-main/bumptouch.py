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

def bumped(data):   #functions
    print(data)
    
    message = data["message"]
    if message.get("isContacted") is True:
        misty.move_head(0, -10, 0, 50)
        misty.move_arms(90, -70, 50, 50)
        misty.change_led(255, 0, 0)
        misty.display_image("e_Love.jpg", 1)
        misty.speak("I love you!")
    else:
        misty.display_image("e_Anger.jpg", 1)
        misty.move_head(0, 0, 0, 50)
        misty.move_arms(-40, 90, 50, 50)
        misty.change_led(0, 255, 0)
        misty.speak("I do not love you anymore.")

def touched(data):
    print(data)
    misty.display_image("e_Anger.jpg", 1)
    misty.move_head(0, 0, 0, 50)
    misty.move_arms(-40, 90, 50, 50)
    misty.change_led(0, 255, 0)
    message = data["message"]

    msg = data["message"]
    position = msg.get("sensorPosition", "")

    if position == "HeadLeft" and msg.get("isContacted", True):
        misty.change_led(255, 0, 0)
        misty.move_head(-20, 0, 90, 90)
        misty.speak("Hello there", voice="English 12 (India)")
        print("✅ HeadLeft touched")

    time.sleep(2)

    misty.move_head(0, 0, 0, 90)





#events definitions
misty.register_event(event_name='bumped', event_type=Events.BumpSensor, callback_function=bumped, keep_alive=True)
misty.register_event(event_name='touch', event_type=Events.TouchSensor, callback_function=touched, keep_alive=True)

#"run until stopped" of blockly
misty.keep_alive()
