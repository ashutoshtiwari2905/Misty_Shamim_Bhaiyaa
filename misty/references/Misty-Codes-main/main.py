import os
from dotenv import load_dotenv
from mistyPy.Robot import Robot

# Load .env file
load_dotenv()

# Get Misty IP from environment
MISTY_IP = os.getenv("MISTY_IP")

# Connect to Misty
misty = Robot(MISTY_IP)

misty.speak("Hello, I am Misty. Today I will tell you whether a number is prime or not?")

num = int(input("Enter a number: "))

for i in range(2, int(num**0.5) + 1):
    if num % i == 0:
        misty.speak(f"{num} is not a prime number.")
        break
else:
    misty.speak(f"{num} is a prime number.")