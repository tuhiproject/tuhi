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
import json
import logging

logger = logging.getLogger('tuhi.drawing')


class Point(GObject.Object):
    def __init__(self, stroke):
        GObject.Object.__init__(self)
        self.stroke = stroke
        self.position = None
        self.pressure = None

    def to_dict(self):
        d = {}
        for key in ['position', 'pressure']:
            val = getattr(self, key, None)
            if val is not None:
                d[key] = val
        return d


class Stroke(GObject.Object):
    def __init__(self, drawing):
        GObject.Object.__init__(self)
        self.drawing = drawing
        self.points = []
        self._position = (0, 0)
        self._pressure = 0
        self._is_sealed = False

    @GObject.Property
    def sealed(self):
        return self._is_sealed

    def seal(self):
        self._is_sealed = True

    def new_rel(self, position=None, pressure=None):
        assert not self._is_sealed

        p = Point(self)
        if position is not None:
            x, y = self._position
            self._position = (x + position[0], y + position[1])
            p.position = self._position
        if pressure is not None:
            self._pressure += pressure
            p.pressure = self._pressure

        self.points.append(p)

    def new_abs(self, position=None, pressure=None):
        assert not self._is_sealed

        p = Point(self)
        if position is not None:
            self._position = position
            p.position = position
        if pressure is not None:
            self._pressure = pressure
            p.pressure = pressure

        self.points.append(p)

    def to_dict(self):
        d = {}
        d['points'] = [p.to_dict() for p in self.points]
        return d


class Drawing(GObject.Object):
    '''
    Abstracts a drawing. The drawing is composed Strokes, each of which has
    Points.
    '''
    JSON_FILE_FORMAT_VERSION = 1

    def __init__(self, name, dimensions, timestamp):
        GObject.Object.__init__(self)
        self.name = name
        self.dimensions = dimensions
        self.timestamp = timestamp  # unix seconds
        self.strokes = []
        self._current_stroke = -1
        self.session_id = 'unset'

    def seal(self):
        # Drop empty strokes
        for s in self.strokes:
            s.seal()
        self.strokes = [s for s in self.strokes if s.points]

    # The way we're building drawings, we don't need to change the current
    # stroke at runtime, so this is read-ony
    @GObject.Property
    def current_stroke(self):
        if self._current_stroke < 0:
            return None

        s = self.strokes[self._current_stroke]
        return s if not s.sealed else None

    def new_stroke(self):
        '''
        Create a new stroke and make it the current stroke
        '''
        if self.current_stroke is not None:
            self.current_stroke.seal()

        s = Stroke(self)
        self.strokes.append(s)
        self._current_stroke += 1
        return s

    def to_json(self):
        json_data = {
            'version': self.JSON_FILE_FORMAT_VERSION,
            'devicename': self.name,
            'sessionid': self.session_id,
            'dimensions': list(self.dimensions),
            'timestamp': self.timestamp,
            'strokes': [s.to_dict() for s in self.strokes]
        }
        return json.dumps(json_data, indent=2)

    @classmethod
    def from_json(cls, path):
        d = None
        with open(path, 'r') as fp:
            json_data = json.load(fp)

            try:
                if json_data['version'] != cls.JSON_FILE_FORMAT_VERSION:
                    logger.error(f'{path}: Invalid file format version')
                    return d

                name = json_data['devicename']
                dimensions = tuple(json_data['dimensions'])
                timestamp = json_data['timestamp']
                d = Drawing(name, dimensions, timestamp)

                for s in json_data['strokes']:
                    stroke = d.new_stroke()
                    for p in s['points']:
                        position = p.get('position', None)
                        pressure = p.get('pressure', None)
                        stroke.new_abs(position, pressure)
            except KeyError:
                logger.error(f'{path}: failed to parse json file')

        return d

    def __repr__(self):
        return f'Drawing from {self.name} at {self.timestamp}, {len(self.strokes)} strokes'
