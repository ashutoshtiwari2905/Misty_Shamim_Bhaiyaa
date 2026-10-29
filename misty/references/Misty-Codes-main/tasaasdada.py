import pygame
import sys
import time

pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No controller detected!")
    sys.exit()

joystick = pygame.joystick.Joystick(0)
joystick.init()
print(f"Controller detected: {joystick.get_name()}")

while True:
    pygame.event.pump()

    # Axes
    axes = [round(joystick.get_axis(i), 2) for i in range(joystick.get_numaxes())]
    if any(abs(a) > 0.1 for a in axes):  # deadzone filter
        print(f"Axes: {axes}")

    # Buttons
    buttons = [joystick.get_button(i) for i in range(joystick.get_numbuttons())]
    for i, pressed in enumerate(buttons):
        if pressed:
            print(f"Button {i} pressed")

    # Hats (D-pad on many controllers)
    hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
    if any(h != (0, 0) for h in hats):
        print(f"Hats: {hats}")

    time.sleep(0.1)
