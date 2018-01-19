#!/usr/bin/env python3
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#

from gi.repository import GObject

import xdg.BaseDirectory
import os
import configparser
import re
import logging

logger = logging.getLogger('tuhi.config')

ROOT_PATH = os.path.join(xdg.BaseDirectory.xdg_data_home, 'tuhi')


class TuhiConfig(GObject.Object):
    def __init__(self):
        GObject.Object.__init__(self)
        try:
            os.mkdir(ROOT_PATH)
        except FileExistsError:
            pass

        self._devices = {}
        self._scan_config_dir()

    @property
    def devices(self):
        """
        Returns a dictionary with the bluetooth address as key
        """
        return self._devices

    def _scan_config_dir(self):
        with os.scandir(ROOT_PATH) as it:
            for entry in it:
                if entry.is_file():
                    continue

                if not re.match('^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', entry.name):
                    continue

                path = os.path.join(ROOT_PATH, entry.name, 'settings.ini')
                if not os.path.isfile(path):
                    continue

                logger.debug("{}: configuration found".format(entry.name))
                config = configparser.ConfigParser()
                config.read(path)

                assert config['Device']['Address'] == entry.name
                self._devices[entry.name] = config['Device']

