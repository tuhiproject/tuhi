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
import logging
import json
from pathlib import Path

logger = logging.getLogger('tuhi.gui.config')


class Config(GObject.Object):
    _instance = None
    _base_path = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)

            self = cls._instance
            self.__init__()  # for GObject to initialize
            self.path = Path(self._base_path, 'tuhigui.ini')
            self.base_path = self._base_path
            self.config = configparser.ConfigParser()
            # Don't lowercase options
            self.config.optionxform = str
            self._drawings = []
            self._load()
            self._load_cached_drawings()
        return cls._instance

    def _load(self):
        if not self.path.exists():
            return

        logger.debug('configuration found')
        self.config.read(self.path)

    def _load_cached_drawings(self):
        if not self.base_path.exists():
            return

        for filename in self.base_path.glob('*.json'):
            with open(filename) as fd:
                self._drawings.append(json.load(fd))
        self.notify('drawings')

    def _write(self):
        self.path.resolve().parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w') as fd:
            self.config.write(fd)

    def _add_key(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
        self._write()

    @GObject.Property
    def orientation(self):
        try:
            return self.config['Device']['Orientation']
        except KeyError:
            return 'landscape'

    @orientation.setter
    def orientation(self, orientation):
        assert(orientation in ['landscape', 'portrait'])
        self._add_key('Device', 'Orientation', orientation)

    @GObject.Property
    def drawings(self):
        return self._drawings

    def add_drawing(self, timestamp, json_string):
        '''Add a drawing JSON with the given timestamp to the backend
        storage. This will update self.drawings.'''
        self.base_path.mkdir(parents=True, exist_ok=True)

        path = Path(self.base_path, f'{timestamp}.json')
        if path.exists():
            return

        # Tuhi may still cache files we've 'deleted' locally. These need to
        # be ignored because they're still technically deleted.
        deleted = Path(self.base_path, f'{timestamp}.json.deleted')
        if deleted.exists():
            return

        with open(path, 'w') as fd:
            fd.write(json_string)

        self._drawings.append(json.loads(json_string))
        self.notify('drawings')

    def replace_drawing(self, timestamp, json_string):
        '''Replace the drawing JSON identified by the timestamp in the backend
        storage. This will update self.drawings.'''
        self.base_path.mkdir(parents=True, exist_ok=True)

        path = Path(self.base_path, f'{timestamp}.json')
        if not path.exists():
            return

        replaced_drawing = list(filter(lambda d: d["timestamp"] == timestamp,
                                self._drawings))

        if len(replaced_drawing) <= 0:
            return
        else:
            replaced_drawing = replaced_drawing[0]

        with open(path, 'w') as fd:
            fd.write(json_string)

        self._drawings.remove(replaced_drawing)
        self._drawings.append(json.loads(json_string))
        self.notify('drawings')


    def delete_drawing(self, timestamp):
        # We don't delete json files immediately, we just rename them
        # so we can resurrect them in the future if need be.
        path = Path(self.base_path, f'{timestamp}.json')
        target = Path(self.base_path, f'{timestamp}.json.deleted')
        path.rename(target)

        self._drawings = [d for d in self._drawings if d['timestamp'] != timestamp]
        self.notify('drawings')

    def undelete_drawing(self, timestamp):
        path = Path(self.base_path, f'{timestamp}.json')
        target = Path(self.base_path, f'{timestamp}.json.deleted')
        target.rename(path)

        with open(path) as fd:
            self._drawings.append(json.load(fd))
        self.notify('drawings')

    @classmethod
    def set_base_path(cls, path):
        if cls._instance is not None:
            logger.error('Trying to set config base path but we already have the singleton object')
            return

        cls._base_path = Path(path)
