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
from .drawing import Drawing
from .wacom import Protocol

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

    @GObject.Property
    def devices(self):
        '''
        Returns a dictionary with the bluetooth address as key
        '''
        return self._devices

    def _scan_config_dir(self):
        with os.scandir(ROOT_PATH) as it:
            for entry in it:
                if entry.is_file():
                    continue

                if not is_btaddr(entry.name):
                    continue

                path = os.path.join(entry, 'settings.ini')
                if not os.path.isfile(path):
                    continue

                logger.debug(f'{entry.name}: configuration found')
                config = configparser.ConfigParser()
                config.read(path)

                self._purge_drawings(entry)

                assert config['Device']['Address'] == entry.name
                if 'Protocol' not in config['Device']:
                    config['Device']['Protocol'] = Protocol.UNKNOWN.value
                self._devices[entry.name] = config['Device']

    def new_device(self, address, uuid, protocol):
        assert is_btaddr(address)
        assert len(uuid) == 12
        assert protocol != Protocol.UNKNOWN

        logger.debug(f'{address}: adding new config, UUID {uuid}')
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
            'Protocol': protocol.value,
        }

        with open(path, 'w') as configfile:
            config.write(configfile)

        config = configparser.ConfigParser()
        config.read(path)
        self._devices[address] = config['Device']

    def store_drawing(self, address, drawing):
        assert is_btaddr(address)
        assert drawing is not None

        if address not in self.devices:
            logger.error(f'{address}: cannot store drawings for unknown device')
            return

        logger.debug(f'{address}: adding new drawing, timestamp {drawing.timestamp}')
        path = os.path.join(ROOT_PATH, address, f'{drawing.timestamp}.json')

        with open(path, 'w') as f:
            f.write(drawing.to_json())

    def load_drawings(self, address):
        assert is_btaddr(address)

        drawings = []
        if address not in self.devices:
            return drawings

        configdir = os.path.join(ROOT_PATH, address)
        with os.scandir(configdir) as it:
            for entry in it:
                if not entry.is_file():
                    continue

                if not entry.name.endswith('.json'):
                    continue

                d = Drawing.from_json(entry)
                drawings.append(d)

        return drawings

    def _purge_drawings(self, directory):
        '''Removes all but the most recent 10 files from the config
        directory. This is primarily done so that no-one relies on the tuhi
        daemon for permanent storage.'''

        files = []
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith('.json'):
                    files.append(entry)

        if len(files) <= 10:
            return

        files.sort(key=lambda e: e.name)
        for f in files[:-10]:
            logger.debug(f'{directory.name}: purging {f.name}')
            os.remove(f)
