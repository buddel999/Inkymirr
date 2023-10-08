#!python3
from inkycal import Inkycal  # Import Inkycal

inky = Inkycal('/home/gianluca/Inkymirr/inkycal/settings.json', render=True)  # Initialise Inkycal
# If your settings.json file is not in /boot, use the full path: inky = Inkycal('path/to/settings.json', render=True)
inky.run()  # If there were no issues, you can run Inkycal nonstop
