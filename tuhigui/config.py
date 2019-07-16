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
import configparser
import logging
from pathlib import Path

logger = logging.getLogger('config')

ROOT_PATH = Path(xdg.BaseDirectory.xdg_data_home, 'tuhigui')


class Config(GObject.Object):
    _config_obj = None

    def __init__(self):
        super().__init__()
        self.path = Path(ROOT_PATH, 'tuhigui.ini')
        self.config = configparser.ConfigParser()
        # Don't lowercase options
        self.config.optionxform = str
        self._load()

    def _load(self):
        if not self.path.exists():
            return

        logger.debug(f'configuration found')
        self.config.read(self.path)

    def _write(self):
        self.path.resolve().parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w') as fd:
            self.config.write(fd)

    def _add_key(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
        self._write()

    @GObject.property
    def orientation(self):
        try:
            return self.config['Device']['Orientation']
        except KeyError:
            return 'landscape'

    @orientation.setter
    def orientation(self, orientation):
        assert(orientation in ['landscape', 'portrait'])
        self._add_key('Device', 'Orientation', orientation)

    @classmethod
    def load(cls):
        if cls._config_obj is None:
            cls._config_obj = Config()
        return cls._config_obj
