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

    def new_rel(self, position=None, pressure=None):
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
    """
    Abstracts a drawing. The drawing is composed Strokes, each of which has
    Points.
    """
    def __init__(self, name, dimensions, timestamp):
        GObject.Object.__init__(self)
        self.name = name
        self.dimensions = dimensions
        self.timestamp = timestamp  # unix seconds
        self.strokes = []
        self._current_stroke = -1

    # The way we're building drawings, we don't need to change the current
    # stroke at runtime, so this is read-ony
    @property
    def current_stroke(self):
        return self.strokes[self._current_stroke]

    def new_stroke(self):
        """
        Create a new stroke and make it the current stroke
        """
        l = Stroke(self)
        self.strokes.append(l)
        self._current_stroke += 1
        return l

    def to_json(self):
        JSON_FILE_FORMAT_VERSION = 1

        json_data = {
            'version': JSON_FILE_FORMAT_VERSION,
            'devicename': self.name,
            'dimensions': list(self.dimensions),
            'timestamp': self.timestamp,
            'strokes': [s.to_dict() for s in self.strokes]
        }
        return json.dumps(json_data)
