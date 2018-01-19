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


def is_btaddr(addr):
    return re.match('^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', addr) is not None


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

                if not is_btaddr(entry.name):
                    continue

                path = os.path.join(ROOT_PATH, entry.name, 'settings.ini')
                if not os.path.isfile(path):
                    continue

                logger.debug("{}: configuration found".format(entry.name))
                config = configparser.ConfigParser()
                config.read(path)

                assert config['Device']['Address'] == entry.name
                self._devices[entry.name] = config['Device']

    def new_device(self, address, uuid):
        assert is_btaddr(address)
        assert len(uuid) == 12

        logger.debug("{}: adding new config, uuid {}".format(address, uuid))
        path = os.path.join(ROOT_PATH, address)
        try:
            os.mkdir(path)
        except FileExistsError:
            pass

        # The ConfigParser default is to write out options as lowercase, but
        # the ini standard is Capitalized. But it's convenient to have
        # write-out nice but read-in flexible. So have two different config
        # parsers for writing and then for handling the reads later
        path = os.path.join(path, 'settings.ini')
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(path)

        config['Device'] = {
            'Address': address,
            'UUID': uuid,
        }

        with open(path, 'w') as configfile:
            config.write(configfile)

        config = configparser.ConfigParser()
        config.read(path)
        self._devices[address] = config['Device']
