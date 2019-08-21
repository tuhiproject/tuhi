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

import configparser
import re
import logging
from pathlib import Path
from .drawing import Drawing
from .protocol import ProtocolVersion

logger = logging.getLogger('tuhi.config')


def is_btaddr(addr):
    return re.match('^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', addr) is not None


class TuhiConfig(GObject.Object):
    _instance = None
    _base_path = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TuhiConfig, cls).__new__(cls)
            self = cls._instance
            self.__init__()  # for GObject to initialize
            logger.debug(f'Using config directory: {self._base_path}')
            Path(self._base_path).mkdir(parents=True, exist_ok=True)

            self._devices = {}
            self._scan_config_dir()
            self.peek_at_drawing = False
        return cls._instance

    @GObject.Property
    def devices(self):
        '''
        Returns a dictionary with the bluetooth address as key
        '''
        return self._devices

    def _scan_config_dir(self):
        dirs = [d for d in Path(self._base_path).iterdir() if d.is_dir() and is_btaddr(d.name)]
        for directory in dirs:
            settings = Path(directory, 'settings.ini')
            if not settings.is_file():
                continue

            logger.debug(f'{directory}: configuration found')
            config = configparser.ConfigParser()
            config.read(settings)

            self._purge_drawings(directory)

            btaddr = directory.name
            assert config['Device']['Address'] == btaddr
            if 'Protocol' not in config['Device']:
                config['Device']['Protocol'] = ProtocolVersion.ANY.name.lower()
            self._devices[btaddr] = config['Device']

    def new_device(self, address, uuid, protocol):
        assert is_btaddr(address)
        assert len(uuid) == 12
        assert protocol != ProtocolVersion.ANY

        logger.debug(f'{address}: adding new config, UUID {uuid}')
        path = Path(self._base_path, address)
        path.mkdir(exist_ok=True)

        # The ConfigParser default is to write out options as lowercase, but
        # the ini standard is Capitalized. But it's convenient to have
        # write-out nice but read-in flexible. So have two different config
        # parsers for writing and then for handling the reads later
        path = Path(path, 'settings.ini')
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(path)

        config['Device'] = {
            'Address': address,
            'UUID': uuid,
            'Protocol': protocol.name.lower(),
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
        path = Path(self._base_path, address, f'{drawing.timestamp}.json')

        with open(path, 'w') as f:
            f.write(drawing.to_json())

    def load_drawings(self, address):
        assert is_btaddr(address)

        if address not in self.devices:
            return []

        configdir = Path(self._base_path, address)
        return [Drawing.from_json(f) for f in configdir.glob('*.json')]

    def _purge_drawings(self, directory):
        '''Removes all but the most recent 10 files from the config
        directory. This is primarily done so that no-one relies on the tuhi
        daemon for permanent storage.'''

        files = [x for x in Path(directory).glob('*.json')]

        if len(files) > 10:
            files.sort(key=lambda e: e.name)
            for f in files[:-10]:
                logger.debug(f'{directory.name}: purging {f.name}')
                f.unlink()

    @classmethod
    def set_base_path(cls, path):
        if cls._instance is not None:
            logger.error('Trying to set config base path but we already have the singleton object')
            return

        cls._base_path = Path(path)
