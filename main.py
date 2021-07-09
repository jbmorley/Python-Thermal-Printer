#!/usr/bin/env python3

# Main script for Adafruit Internet of Things Printer 2.  Monitors button
# for taps and holds, performs periodic actions (Twitter polling by default)
# and daily actions (Sudoku and weather by default).
# Written by Adafruit Industries.  MIT license.
#
# MUST BE RUN AS ROOT (due to GPIO access)
#
# Required software includes Adafruit_Thermal, Python Imaging and PySerial
# libraries. Other libraries used are part of stock Python install.
#
# Resources:
# http://www.adafruit.com/products/597 Mini Thermal Receipt Printer
# http://www.adafruit.com/products/600 Printer starter pack

from __future__ import print_function

import RPi.GPIO as GPIO
import datetime
import glob
import logging
import os
import socket
import subprocess
import time

import requests

from PIL import Image
from Adafruit_Thermal import *

ROOT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
QUEUE_DIRECTORY = os.path.join(ROOT_DIRECTORY, "queue")

verbose = '--verbose' in sys.argv[1:] or '-v' in sys.argv[1:]
logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="[%(levelname)s] %(message)s")

ledPin       = 18
buttonPin    = 23
holdTime     = 2     # Duration for button hold (shutdown)
tapTime      = 0.01  # Debounce time for button taps
nextInterval = 0.0   # Time of next recurring operation
dailyFlag    = False # Set after daily trigger occurs
lastId       = '1'   # State information passed to/from interval script
printer      = Adafruit_Thermal("/dev/serial0", 19200, timeout=5)


class Chdir(object):

    def __init__(self, path):
        self.path = os.path.abspath(path)

    def __enter__(self):
        self.pwd = os.getcwd()
        os.chdir(self.path)
        return self.path

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.pwd)


class LED(object):

  def __enter__(self):
    GPIO.output(ledPin, GPIO.HIGH)
    return self

  def __exit__(self, *args):
    GPIO.output(ledPin, GPIO.LOW)


# Called when button is briefly tapped.  Invokes time/temperature script.
def tap():
  with LED():
    # White space.
    printer.feed(6)

    # Release date.
    now = datetime.datetime.now()
    release = now + datetime.timedelta(days=2)
    release_string = release.strftime("%A, %e %B at %H:%M")
    printer.print(f"Your mail can be released from quarantine on {release_string}.")
    printer.feed(3)

    # Quote.
    text, author = get_quote()
    printer.println(text)
    printer.print(f"- {author}")
    printer.justify('R')
    printer.feed(3)
    printer.justify('L')

    # Statement.
    printer.justify('C')
    printer.println("Share and Enjoy <3")
    printer.justify('L')
    printer.feed(3)


def get_quote():
  response = requests.get("https://www.adafruit.com/api/quotes.php")
  json = response.json()
  text, author = json[0]["text"], json[0]["author"]
  return (text, author)


# Called when button is held down.  Prints image, invokes shutdown process.
def hold():
  GPIO.output(ledPin, GPIO.HIGH)
  #printer.printImage(Image.open('gfx/goodbye.png'), True)
  printer.print("Goodbye!")
  printer.feed(3)
  subprocess.call("sync")
  subprocess.call(["/sbin/shutdown", "-h", "now"])
  GPIO.output(ledPin, GPIO.LOW)


# Called at periodic intervals (30 seconds by default).
# Invokes twitter script.
def interval():
  return


# Called once per day (6:30am by default).
# Invokes weather forecast and sudoku-gfx scripts.
def daily():
  return


# Ensure the queue directory exists.
if not os.path.isdir(QUEUE_DIRECTORY):
    os.makedirs(QUEUE_DIRECTORY)

# Initialization

# Use Broadcom pin numbers (not Raspberry Pi pin numbers) for GPIO
GPIO.setmode(GPIO.BCM)

# Enable LED and button (w/pull-up on latter)
GPIO.setup(ledPin, GPIO.OUT)
GPIO.setup(buttonPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# LED on while working
GPIO.output(ledPin, GPIO.HIGH)

# Processor load is heavy at startup; wait a moment to avoid
# stalling during greeting.
# time.sleep(30)

printer.print("Hello!")
# printer.printImage('gfx/hello.png', True)
printer.feed(3)


GPIO.output(ledPin, GPIO.LOW)

# Poll initial button state and time
prevButtonState = GPIO.input(buttonPin)
prevTime        = time.time()
tapEnable       = False
holdEnable      = False

# Main loop
while(True):

  # Poll current button state and time
  buttonState = GPIO.input(buttonPin)
  t           = time.time()

  # Has button state changed?
  if buttonState != prevButtonState:
    prevButtonState = buttonState   # Yes, save new state/time
    prevTime        = t
  else:                             # Button state unchanged
    if (t - prevTime) >= holdTime:  # Button held more than 'holdTime'?
      # Yes it has.  Is the hold action as-yet untriggered?
      if holdEnable == True:        # Yep!
        hold()                      # Perform hold action (usu. shutdown)
        holdEnable = False          # 1 shot...don't repeat hold action
        tapEnable  = False          # Don't do tap action on release
    elif (t - prevTime) >= tapTime: # Not holdTime.  tapTime elapsed?
      # Yes.  Debounced press or release...
      if buttonState == True:       # Button released?
        if tapEnable == True:       # Ignore if prior hold()
          tap()                     # Tap triggered (button released)
          tapEnable  = False        # Disable tap and hold
          holdEnable = False
      else:                         # Button pressed
        tapEnable  = True           # Enable tap and hold actions
        holdEnable = True

  # LED blinks while idle, for a brief interval every 2 seconds.
  # Pin 18 is PWM-capable and a "sleep throb" would be nice, but
  # the PWM-related library is a hassle for average users to install
  # right now.  Might return to this later when it's more accessible.
  if ((int(t) & 1) == 0) and ((t - int(t)) < 0.15):
    GPIO.output(ledPin, GPIO.HIGH)
  else:
    GPIO.output(ledPin, GPIO.LOW)

  # Once per day (currently set for 6:30am local time, or when script
  # is first run, if after 6:30am), run forecast and sudoku scripts.
  l = time.localtime()
  if (60 * l.tm_hour + l.tm_min) > (60 * 6 + 30):
    if dailyFlag == False:
      daily()
      dailyFlag = True
  else:
    dailyFlag = False  # Reset daily trigger

  if t > nextInterval:
    nextInterval = t + 5.0
    logging.info("Checking spool...")
    with Chdir(QUEUE_DIRECTORY):
      files = glob.glob("*.png")
      for f in files:
        logging.info("Printing '%s'...", f)
        printer.printImage(f, False)
        printer.feed(10)
        os.remove(f)
