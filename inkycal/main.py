#!python3
# -*- coding: utf-8 -*-

"""
Main class for inkycal Project
Copyright by aceinnolab
"""

import glob
import hashlib
import json
import traceback
from logging.handlers import RotatingFileHandler

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from io import BytesIO

import arrow
import numpy

from inkycal.custom import *
from inkycal.display import Display

from PIL import Image

# On the console, set a logger to show only important logs
# (level ERROR or higher)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.ERROR)



if not os.path.exists(f'{top_level}/logs'):
    os.mkdir(f'{top_level}/logs')

# Save all logs to a file, which contains more detailed output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s |  %(levelname)s: %(message)s',
    datefmt='%d-%m-%Y %H:%M:%S',
    handlers=[

        stream_handler,  # add stream handler from above

        RotatingFileHandler(  # log to a file too
            f'{top_level}/logs/inkycal.log',  # file to log
            maxBytes=2097152,  # 2MB max filesize
            backupCount=5  # create max 5 log files
        )
    ]
)

# Show less logging for PIL module
logging.getLogger("PIL").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# TODO: autostart -> supervisor?

class Inkycal:
    """Inkycal main class

    Main class of Inkycal, test and run the main Inkycal program.

    Args:
      - settings_path = str -> the full path to your settings.json file
        if no path is given, tries looking for settings file in /boot folder.
      - render = bool (True/False) -> show the image on the epaper display?

    Attributes:
      - optimize = True/False. Reduce number of colours on the generated image
        to improve rendering on E-Papers. Set this to False for 9.7" E-Paper.
    """

    def __init__(self, settings_path=None, render=True):
        """Initialise Inkycal"""

        self._release = '2.0.2'

        # Check if render was set correctly
        if render not in [True, False]:
            raise Exception(f'render must be True or False, not "{render}"')
        self.render = render

        # load settings file - throw an error if file could not be found
        if settings_path:
            try:
                with open(settings_path) as settings_file:
                    settings = json.load(settings_file)
                    self.settings = settings

            except FileNotFoundError:
                raise SettingsFileNotFoundError

        else:
            try:
                with open('/boot/settings.json') as settings_file:
                    settings = json.load(settings_file)
                    self.settings = settings

            except FileNotFoundError:
                raise SettingsFileNotFoundError

        if not os.path.exists(image_folder):
            os.mkdir(image_folder)

        # Option to use epaper image optimisation, reduces colours
        self.optimize = True

        # Load drivers if image should be rendered
        if self.render:
            # Init Display class with model in settings file
            # from inkycal.display import Display
            self.Display = Display(settings["model"])

            # check if colours can be rendered
            self.supports_colour = True if 'colour' in settings['model'] else False

            # get calibration hours
            self._calibration_hours = self.settings['calibration_hours']

            # init calibration state
            self._calibration_state = False

        #Load and intialize browser with url specified in settings
        service = Service('/usr/bin/chromedriver')

        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        driver = webdriver.Chrome(service=service, options=options)
        driver.set_window_size(Display.get_display_size(self.settings["model"]))

        start_url = self.settings["mm_address"]
        driver.get(start_url)

        # Path to store images
        self.image_folder = image_folder

        # Remove old hashes
        self._remove_hashes(self.image_folder)

        # Give an OK message
        print('loaded inkycal')

    def countdown(self, interval_mins=None):
        """Returns the remaining time in seconds until next display update"""

        # Check if empty, if empty, use value from settings file
        if interval_mins is None:
            interval_mins = self.settings["update_interval"]

        # Find out at which minutes the update should happen
        now = arrow.now()
        update_timings = [(60 - int(interval_mins) * updates) for updates in
                          range(60 // int(interval_mins))][::-1]

        # Calculate time in mins until next update
        minutes = [_ for _ in update_timings if _ >= now.minute][0] - now.minute

        # Print the remaining time in mins until next update
        print(f'{minutes} minutes left until next refresh')

        # Calculate time in seconds until next update
        remaining_time = minutes * 60 + (60 - now.second)

        # Return seconds until next update
        return remaining_time

    def _image_hash(self, _in):
        """Create a md5sum of a path or a bytes stream."""
        if not isinstance(_in, str):
            image_bytes = _in.tobytes()
        else:
            try:
                with open(_in) as i:
                    return i.read()
            except FileNotFoundError:
                image_bytes = None
        return hashlib.md5(image_bytes).hexdigest() if image_bytes else ""

    def _remove_hashes(self, basepath):
        for _file in glob.glob(f"{basepath}/*.hash"):
            try:
                os.remove(_file)
            except:
                pass

    def _write_image_hash(self, path, _in):
        """Write hash to a file."""
        with open(path, "w") as o:
            o.write(self._image_hash(_in))

    def _needs_image_update(self, _list):
        """Check if any image has been updated or not.
        Input a list of tuples(str, image)."""
        res = False
        for item in _list:
            _a = self._image_hash(item[0])
            _b = self._image_hash(item[1])
            print("{f1}:{h1} -> {h2}".format(f1=item[0], h1=_a, h2=_b))
            if _a != _b:
                res = True
                self._write_image_hash(item[0], item[1])
            print("Refresh needed: {a}".format(a=res))
        return res


    def run(self):
        """Runs main program in nonstop mode.

        Uses an infinity loop to run Inkycal nonstop. Inkycal generates the image
        from all modules, assembles them in one image, refreshed the E-Paper and
        then sleeps until the next sheduled update.
        """

        # Get the time of initial run
        runtime = arrow.now()

        # Function to flip images upside down
        upside_down = lambda image: image.rotate(180, expand=True)

        # Count the number of times without any errors
        counter = 0

        print(f'Inkycal version: v{self._release}')
        print(f'Selected E-paper display: {self.settings["model"]}')

        while True:
            current_time = arrow.now(tz=get_system_tz())
            print(f"Date: {current_time.format('D MMM YY')} | "
                  f"Time: {current_time.format('HH:mm')}")
            print('Generating images for all modules...', end='')


            # short info for info-section
            if not self.settings.get('image_hash', False):
                self.info = f"{current_time.format('D MMM @ HH:mm')}  "
            else:
                self.info = ""


            #Generate Image from browser screenshot and save it to image folder
            img = Image.open(BytesIO(driver.get_screenshot_as_png()))
            img.save(self.image_folder + 'canvas.png', 'PNG')
            img.save(self.image_folder + 'canvas_colour.png', 'PNG')


            # Check if image should be rendered
            if self.render:
                display = self.Display

                self._calibration_check()
                if self._calibration_state:
                    # after calibration we have to forcefully rewrite the screen
                    self._remove_hashes(self.image_folder)

                if self.supports_colour:
                    im_black = Image.open(f"{self.image_folder}canvas.png")
                    im_colour = Image.open(f"{self.image_folder}canvas_colour.png")

                    # Flip the image by 180° if required
                    if self.settings['orientation'] == 180:
                        im_black = upside_down(im_black)
                        im_colour = upside_down(im_colour)

                    # render the image on the display
                    if not self.settings.get('image_hash', False) or self._needs_image_update([
                      (f"{self.image_folder}/canvas.png.hash", im_black),
                      (f"{self.image_folder}/canvas_colour.png.hash", im_colour)
                    ]):
                        # render the image on the display
                        display.render(im_black, im_colour)

                # Part for black-white ePapers
                elif not self.supports_colour:

                    #im_black = self._merge_bands()

                    # Flip the image by 180° if required
                    if self.settings['orientation'] == 180:
                        im_black = upside_down(im_black)

                    if not self.settings.get('image_hash', False) or self._needs_image_update([
                      (f"{self.image_folder}/canvas.png.hash", im_black),
                    ]):
                        display.render(im_black)

            print(f'\nNo errors since {counter} display updates \n'
                  f'program started {runtime.humanize()}')

            sleep_time = self.countdown()
            time.sleep(sleep_time)

    @staticmethod
    def _merge_bands():
        """Merges black and coloured bands for black-white ePapers
        returns the merged image
        """

        im1_path, im2_path = image_folder + 'canvas.png', image_folder + 'canvas_colour.png'

        # If there is an image for black and colour, merge them
        if os.path.exists(im1_path) and os.path.exists(im2_path):

            im1 = Image.open(im1_path).convert('RGBA')
            im2 = Image.open(im2_path).convert('RGBA')

            im1 = Images.merge(im1, im2)

        # If there is no image for the coloured-band, return the bw-image
        elif os.path.exists(im1_path) and not os.path.exists(im2_path):
            im1 = Image.open(im1_path).convert('RGBA')

        else:
            raise FileNotFoundError("Inkycal cannot find images to merge")

        return im1

    def calibrate(self):
        """Calibrate the E-Paper display

        Uses the Display class to calibrate the display with the default of 3
        cycles. After a refresh cycle, a new image is generated and shown.
        """

        self.Display.calibrate()

    def _calibration_check(self):
        """Calibration sheduler
        uses calibration hours from settings file to check if calibration is due"""
        now = arrow.now()
        # print('hour:', now.hour, 'hours:', self._calibration_hours)
        # print('state:', self._calibration_state)
        if now.hour in self._calibration_hours and self._calibration_state == False:
            self.calibrate()
            self._calibration_state = True
        else:
            self._calibration_state = False


if __name__ == '__main__':
    print(f'running inkycal main in standalone/debug mode')
