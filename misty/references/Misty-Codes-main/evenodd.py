import os
from dotenv import load_dotenv
from mistyPy.Robot import Robot

# Load .env file
load_dotenv()

# Get Misty IP from environment
MISTY_IP = os.getenv("MISTY_IP")

# Connect to Misty
misty = Robot(MISTY_IP)

misty.speak("Hello, I am Misty. Today I will tell you whether a number is even or not?")

num = int(input("Enter a number: "))

if num % 2 == 0:
    misty.speak(f"{num} is an even number.")
else:
    misty.speak(f"{num} is an odd number.")