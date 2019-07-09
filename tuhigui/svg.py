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

DATA_PATH = os.path.join(xdg.BaseDirectory.xdg_data_home, 'tuhigui')


class JsonSvg(GObject.Object):
    def __init__(self, json, *args, **kwargs):
        self.json = json
        try:
            os.mkdir(DATA_PATH)
        except FileExistsError:
            pass

        self.timestamp = json['timestamp']
        self.filename = os.path.join(DATA_PATH, f'{self.timestamp}.svg')
        self.orientation = 'Landscape'
        self._convert()

    def _convert(self):
        js = self.json
        dimensions = js['dimensions']
        if dimensions == [0, 0]:
            width, height = 100, 100
        else:
            # Original dimensions are too big for SVG Standard
            # so we normalize them
            width, height = dimensions[0] / 100, dimensions[1] / 100

        if self.orientation in ['Portrait', 'Reverse-Portrait']:
            size = (height, width)
        else:
            size = (width, height)
        svg = svgwrite.Drawing(filename=self.filename, size=size)
        g = svgwrite.container.Group(id='layer0')
        for stroke_num, s in enumerate(js['strokes']):

            points_with_sk_width = []

            for p in s['points']:

                x, y = p['position']
                # Normalize coordinates too
                x, y = x / 100, y / 100

                if self.orientation == 'Reverse-Portrait':
                    x, y = y, width - x
                elif self.orientation == 'Portrait':
                    x, y = height - y, x
                elif self.orientation == 'Reverse-Landscape':
                    x, y = width - x, height - y

                delta = (p['pressure'] - 1000.0) / 1000.0
                stroke_width = 0.4 + 0.20 * delta
                points_with_sk_width.append((x, y, stroke_width))

            if False and self.handle_pressure:  # FIXME
                lines = svgwrite.container.Group(id=f'strokes_{stroke_num}', stroke='black')
                for i, (x, y, stroke_width) in enumerate(points_with_sk_width):
                    if i != 0:
                        xp, yp, stroke_width_p = points_with_sk_width[i - 1]
                        lines.add(
                            svg.line(
                                start=(xp, yp),
                                end=(x, y),
                                stroke_width=stroke_width,
                                style='fill:none'
                            )
                        )
            else:
                lines = svgwrite.path.Path(
                    d="M",
                    stroke='black',
                    stroke_width=0.2,
                    style='fill:none'
                )
                for x, y, stroke_width in points_with_sk_width:
                    lines.push(x, y)

            g.add(lines)

        svg.add(g)
        svg.save()
