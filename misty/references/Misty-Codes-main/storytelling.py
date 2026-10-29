import os
from dotenv import load_dotenv
from mistyPy.Robot import Robot
import google.generativeai as genai
import time
import random
# Load .env file
load_dotenv()

# Get Misty IP from environment
MISTY_IP = os.getenv("MISTY_IP")

# Connect to Misty
misty = Robot(MISTY_IP)

API_KEY = "AIzaSyBcgeqaPLaf-ye2CuJOjjSxpCMBB37ohUo"

# Init Misty & AI
misty = Robot(MISTY_IP)
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# === FUNCTIONS ===
def tell_story(topic):
    # 1. Generate a fun short story
    prompt = f"Tell a fun, engaging short story for kids about {topic}."
    response = model.generate_content(prompt)
    story = response.text
    
    # 2. Add some expressions & gestures
    misty.display_image("e_Joy.jpg")  # happy face
    misty.move_head(pitch=10, roll=0, yaw=0, velocity=50)
    time.sleep(1)
    
    # 3. Speak the story in chunks (so it sounds more natural)
    for line in story.split(". "):
        misty.speak(line.strip())
        time.sleep(2)
        # Random LED colors for fun
        misty.change_led(random.randint(0,255), random.randint(0,255), random.randint(0,255))
    
    # Reset Misty
    misty.display_image("e_DefaultContent.jpg")
    misty.change_led(255,255,255)
    misty.move_head(0,0,0,50)

# === MAIN ===
if __name__ == "__main__":
    topic = input("Enter a topic for Misty’s story: ")
    tell_story(topic)
