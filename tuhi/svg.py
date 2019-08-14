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
import svgwrite
import os
from pathlib import Path
from svgwrite import mm

DATA_PATH = Path(xdg.BaseDirectory.xdg_cache_home, 'tuhi', 'svg')


class JsonSvg(GObject.Object):
    def __init__(self, json, orientation, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.json = json
        DATA_PATH.mkdir(parents=True, exist_ok=True)

        self.timestamp = json['timestamp']
        self.filename = os.fspath(Path(DATA_PATH, f'{self.timestamp}.svg'))
        self.orientation = orientation
        self._convert()

    def _convert(self):
        js = self.json
        dimensions = js['dimensions']
        if dimensions == [0, 0]:
            width, height = 100, 100
        else:
            # Original dimensions are too big for SVG Standard
            # so we normalize them
            width, height = dimensions[0] / 1000, dimensions[1] / 1000

        if self.orientation in ['portrait', 'reverse-Portrait']:
            size = (height * mm, width * mm)
        else:
            size = (width * mm, height * mm)
        svg = svgwrite.Drawing(filename=self.filename, size=size)
        g = svgwrite.container.Group(id='layer0')
        for stroke_num, s in enumerate(js['strokes']):

            points_with_sk_width = []

            for p in s['points']:

                x, y = p['position']
                # Normalize coordinates too
                x, y = x / 1000, y / 1000

                if self.orientation == 'reverse-portrait':
                    x, y = y, width - x
                elif self.orientation == 'portrait':
                    x, y = height - y, x
                elif self.orientation == 'reverse-landscape':
                    x, y = width - x, height - y

                # Pressure normalized range is [0, 0xffff]
                delta = (p['pressure'] - 0x8000) / 0x8000
                stroke_width = 0.4 + 0.20 * delta
                points_with_sk_width.append((x, y, stroke_width))

            lines = svgwrite.container.Group(id=f'strokes_{stroke_num}', stroke='black')
            for i, (x, y, stroke_width) in enumerate(points_with_sk_width):
                if i != 0:
                    xp, yp, stroke_width_p = points_with_sk_width[i - 1]
                    lines.add(
                        svg.line(
                            start=(xp * mm, yp * mm),
                            end=(x * mm, y * mm),
                            stroke_width=stroke_width,
                            style='fill:none'
                        )
                    )
            g.add(lines)

        svg.add(g)
        svg.save()
