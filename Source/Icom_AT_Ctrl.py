#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Standalone Icom HF Automatic Antenna Tuner Control
# Software designed to run on the RP2040-Zero platform, or on the Raspberry Pi Pico with some GPIO pin re-assignment.
# Should operate with AH-3, AH-4, AT-120, AT-130, AT-140, AT-141 and AH-730 tuners. Not useable with AT-705.
# By Bert, VE2ZAZ / VA2IW
# Website: https://ve2zaz.net/Icom_Tuner_Ctrl/Icom_Tuner_Ctlr.htm
# Github: https://github.com/VE2ZAZ/Icom_Tuner_Controller
# Note: Please be forgiving about the coding style and its quality. The author's expertise is hardware, not software...
#
#  This software, along with all accompanying files and scripts, is free software: you can redistribute it
#  and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation,
#  either version 3 of the License, or any later version. see https://www.gnu.org/licenses/ . When modifying the
#  software, a mention of the original author, namely Bert-VE2ZAZ, would be a gracious consideration.
    
# Release History
#  - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# Version 1.0 (2026/02/07):
# - Initial Release
#  - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

from machine import Pin, I2C
import time
import ina226   	# Micropython driver for the INA226. By Christian Becker. File ina226.py must be included in local directory.
#import neopixel  	# Only required when using the RGB LED on the RP2040-Zero.
import _thread  # Adds multiple threading, can run another process one the 2nd CPU core.

print('=========CPU Reset==========')   # A confirmation that the code starts when using Thonny and its REPL shell.

# CONSTANTS
ON = True
OFF = False
LOW = 0
HIGH = 1
GREEN = 1
YELLOW = 2
YELLOW_FLASH = 3
RED = 4
RED_FLASH = 5

# GLOBAL VARIABLES
old_pbutton_ticks_ms = 0
old_start_ticks_ms = 0
old_key_ticks_ms = 0
old_in_tuning_ticks_ms = 0
old_led_flash_ticks_ms = time.ticks_ms()
in_tuning = False
in_start = False
key_detected = False
led_color = YELLOW
tuner_current = 0
tuner_detected = False
yellow_dwell_cntr = 0

# HARDWARE ASSIGNMENTS
Led_Red_Pin= Pin(14, Pin.OUT, HIGH)   			# Red LED color produced when this pin is set to low and the Led_Green_Pin is set to high.
Led_Green_Pin = Pin(15, Pin.OUT, LOW) 			# Green LED color produced when this pin is set to low and the Led_Red_Pin is set to high.
AT_Start_Pin = Pin(6, Pin.OUT, HIGH)			# The START signal sent to the antenna tuner. 
AT_Start_Pin.value(HIGH)						# High level is the idle state
PTT_Pin = Pin(5, Pin.OUT, HIGH)					# The PTT output signal to be sent to the HF transceiver. Active low.
PTT_Pin.value(HIGH)								# High level is the idle state
AT_Key_Pin = Pin(7, Pin.IN, Pin.PULL_UP)		# The KEY signal coming from the antenna tuner. Active low.
PButton_Pin = Pin(28, Pin.IN, Pin.PULL_UP)		# The front panel pushbutton. Active low.

ISense_I2C = I2C(1, scl=Pin(3), sda=Pin(2), freq=100000) 	# The INA226 I2C port definition
ISense = ina226.INA226(ISense_I2C, 0x40)   					# The INA226 instanciation

# Makes the LED flash red slowly 10 times to signal tuner failure to reply to tuning command
def Red_Led_Flash():
    global led_color
    for i in range(0,10):				# Flash LED 10 times
        led_color = RED
        time.sleep(0.1)
        led_color = OFF
        time.sleep(0.1)

# Makes the LED flash amber 5 times to indicate inability of the tuner to tune the antenna to low enough VSWR.   
def Yellow_Led_Flash():
    global led_color
    for i in range(0,5):				# Flash LED 5 times 
        led_color = YELLOW
        time.sleep(0.1)
        led_color = OFF
        time.sleep(0.1)

# This function creates the amber color by alternating between red and green, while dwelling longer on the red color vs. the green color
def Yellow_On_Tint_Adjusted():
    global yellow_dwell_cntr
    if (Led_Red_Pin.value() == LOW):  	# If red is shown, it will stay longer on before flipping to green
        if (yellow_dwell_cntr >= 3):
            Led_Red_Pin.value(HIGH)		# Flip to green
            Led_Green_Pin.value(LOW)
            yellow_dwell_cntr = 0
        else: yellow_dwell_cntr += 1
    else:								# Green is shown, just flip color to red
        Led_Green_Pin.value(HIGH)
        Led_Red_Pin.value(LOW)

# This is the second core's thread, which manages LED colors
# Caution, do not use print statements in this fast loop! Otherwise the thread will not be stoppable within Thonny
def LED_Thread():
    global led_color
    old_led_flash_ticks_thread_ms = time.ticks_ms()   	# Initialize old millisecond tick value to current tick value.
    # LED color management
    while(True):
        time.sleep(0.001)    							# Slow down loop to stabilize operation    
        if (led_color == YELLOW_FLASH):		
            if (time.ticks_diff(time.ticks_ms(), old_led_flash_ticks_thread_ms) > 40):   			# If at more than 40 ms, re-initialize old millisecond tick value to current tick value.
                old_led_flash_ticks_thread_ms = time.ticks_ms()
            elif (20 < time.ticks_diff(time.ticks_ms(), old_led_flash_ticks_thread_ms) <= 40):  	# If between 21 and 40 ms, turn off LED
                Led_Red_Pin.value(HIGH)					# Do not replace these two lines with "led_color == OFF"
                Led_Green_Pin.value(HIGH)
            elif (time.ticks_diff(time.ticks_ms(), old_led_flash_ticks_thread_ms) <= 20):  			# If between 0 and 20 ms, produce a quick flash to create yellow (amber)
                Yellow_On_Tint_Adjusted()
        elif (led_color == RED_FLASH):
            if (time.ticks_diff(time.ticks_ms(), old_led_flash_ticks_thread_ms) > 600):				# If at more than 600 ms, re-initialize old millisecond tick value to current tick value.
                old_led_flash_ticks_thread_ms = time.ticks_ms()
            elif (300 < time.ticks_diff(time.ticks_ms(), old_led_flash_ticks_thread_ms) <= 600):  	# If between 300 and 600 ms, turn off LED
                Led_Red_Pin.value(HIGH)
                Led_Green_Pin.value(HIGH)
            elif (time.ticks_diff(time.ticks_ms(), old_led_flash_ticks_thread_ms) <= 300):  		# If between 0 and 300 ms, produce a quick flash to create yellow (amber)
                Led_Green_Pin.value(HIGH)
                Led_Red_Pin.value(LOW)
        if (led_color == YELLOW):		
            Yellow_On_Tint_Adjusted()					# Need to dwell longer on thr red to look more amber
        if (led_color == GREEN):
            Led_Red_Pin.value(HIGH)
            Led_Green_Pin.value(LOW)
        if (led_color == RED):
            Led_Green_Pin.value(HIGH)
            Led_Red_Pin.value(LOW)
        if (led_color == OFF):
            Led_Red_Pin.value(HIGH)
            Led_Green_Pin.value(HIGH)

# Start LED management thread on second core
_thread.start_new_thread(LED_Thread, ())

# Main loop
while (True):
    time.sleep(0.001)    							# Slow down main loop to stabilize operation
    # Tuner Presence check
    if (ISense.current > 0.2):		# This reads the INA226 current in Ampères. If more than 200 ma detected, assumed that the tuner is present
        if (led_color == RED_FLASH): led_color = YELLOW		# Transition to tuner present if previously show absent.
        # Push Button Validation
        if ((PButton_Pin.value() == LOW) and (not(in_tuning))):  # Detect button being depressed.
            old_pbutton_ticks_ms = time.ticks_ms()
            time.sleep(0.05)   						# Debouncing delay
            while (PButton_Pin.value() == LOW):		# Button still being depressed. Wait in this loop until released.
                led_color = OFF						# Turn off LED
            # Tuning process start check and processing
            if (time.ticks_diff(time.ticks_ms(), old_pbutton_ticks_ms) > 700):  # Depressing pushbutton for more than 700 ms launches the tuning.
                in_tuning = True
                old_in_tuning_ticks_ms = time.ticks_ms()
                in_start = True
                old_start_ticks_ms = time.ticks_ms()
                print('start begins')
                AT_Start_Pin.value(LOW)				# Send the START signal to the tuner
                old_led_flash_ticks_ms = time.ticks_ms()
                led_color = YELLOW_FLASH			# Make the led flash amber fast while tuning operation is happening
            # Reset command (tuner removed from line) check and processing
            elif (time.ticks_diff(time.ticks_ms(), old_pbutton_ticks_ms) > 50): # Depressing pushbutton for more than 50ms but less than 700 ms resets the tuner.
                AT_Start_Pin.value(LOW)
                time.sleep(0.07)
                AT_Start_Pin.value(HIGH)
                in_tuning = False
                in_start = False
                led_color = YELLOW
                print('reset')
        # In-tuning check and processing
        if (in_tuning):
            time.sleep(.01)				# required to slow down input pin processing
            # catch aborted tuning process (no response from tuner)
            if (time.ticks_diff(time.ticks_ms(), old_in_tuning_ticks_ms) > 4000):  # 4 seconds and no reply from the tuner. Added to catch any jamming in the tuning process
                print('Tuner error, no response')
                in_tuning = False
                in_start = False
                key_detected = False
                PTT_Pin.value(HIGH)
                AT_Start_Pin.value(HIGH)
                Red_Led_Flash()				# Make LED flash red slowly 5 times 
                led_color = RED				# Then display a solid red.
            # process start signal end
            elif ((time.ticks_diff(time.ticks_ms(), old_start_ticks_ms) > 560) and (in_start)): # More than 560 ms elapsed since START line was asserted.
                AT_Start_Pin.value(HIGH)	# De-assert the START line going to tuner
                in_start = False
                print('start ends')
            # Test for Key signal presence
            if ((AT_Key_Pin.value() == LOW) and (not(key_detected))): # First tuner KEY signal transition to LOW level
                key_detected = True
                PTT_Pin.value(LOW)			# Send PTT to tranceiver to put RF into tuner
                print('keying detected')
                old_key_ticks_ms = time.ticks_ms()
            # Test for Key signal dissapearance
            if ((AT_Key_Pin.value() == HIGH) and (key_detected)):		# KEY signal gone idle (high)?
                key_detected = False
                print('keying stopped')
                PTT_Pin.value(HIGH)			# release PTT
                # Test for valid tuning process
                if (time.ticks_diff(time.ticks_ms(), old_key_ticks_ms) > 500):	# KEY signal lasted more than 500 ms: Tuning was successful
                    print('tuning success')
                    in_tuning = False
                    led_color = GREEN
                # Process tuning failure 
                else:						# KEY signal lasted less than 500 ms means that an error pulse was received: tuner failed to tune antenna
                    print('Tuning failure')
                    in_tuning = False
                    old_led_flash_ticks_ms = time.ticks_ms()
                    Yellow_Led_Flash()		# FLash yellow slowly for 5 times
                    led_color = YELLOW
        else:								# Not in tunig process, reset flags and make KEY signal high (idle)
            PTT_Pin.value(HIGH)
            AT_Start_Pin.value(HIGH)
            in_tuning = False
            key_detected = False
            in_start = False
    else:									# Tuner current not detected, system action is disabled and flashing red LED is shown
        PTT_Pin.value(HIGH)
        AT_Start_Pin.value(HIGH)
        in_tuning = False
        key_detected = False
        in_start = False
        led_color = RED_FLASH				# Tuner current not detected: Continually flash red slowly.

# End of code