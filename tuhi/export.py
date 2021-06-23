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
import svgwrite
import os
from svgwrite import mm
import cairo


class ImageExportBase(GObject.Object):

    def __init__(self, json, orientation, filename, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.json = json
        self.timestamp = json['timestamp']
        self.filename = filename
        self.orientation = orientation.lower()
        self._convert()

    @property
    def output_dimensions(self):
        dimensions = self.json['dimensions']
        if dimensions == [0, 0]:
            width, height = 100, 100
        else:
            # Original dimensions are too big for most Standards
            # so we scale them down
            width = dimensions[0] / self._output_scaling_factor
            height = dimensions[1] / self._output_scaling_factor

        if self.orientation in ['portrait', 'reverse-portrait']:
            return height, width
        else:
            return width, height

    @property
    def output_strokes(self):

        width, height = self.output_dimensions
        strokes = []

        for s in self.json['strokes']:
            points_with_sk_width = []

            for p in s['points']:

                x, y = p['position']
                # Scaling coordinates
                x = x / self._output_scaling_factor
                y = y / self._output_scaling_factor

                if self.orientation == 'reverse-portrait':
                    x, y = y, height - x
                elif self.orientation == 'portrait':
                    x, y = width - y, x
                elif self.orientation == 'reverse-landscape':
                    x, y = width - x, height - y

                # Pressure normalized range is [0, 0xffff]
                delta = (p['pressure'] - 0x8000) / 0x8000
                stroke_width = self._base_pen_width + self._pen_pressure_width_factor * delta
                points_with_sk_width.append((x, y, stroke_width))

            strokes.append(points_with_sk_width)

        return strokes


class JsonSvg(ImageExportBase):

    _output_scaling_factor = 1000
    _base_pen_width = 0.4
    _pen_pressure_width_factor = 0.2

    def _convert(self):
        if os.path.isfile(self.filename):
            return

        width, height = self.output_dimensions
        size = width * mm, height * mm
        svg = svgwrite.Drawing(filename=self.filename, size=size)

        g = svgwrite.container.Group(id='layer0')
        for sk_num, stroke_points in enumerate(self.output_strokes):
            lines = svgwrite.container.Group(id=f'sk_{sk_num}', stroke='black')
            for i, (x, y, stroke_width) in enumerate(stroke_points):
                if i != 0:
                    xp, yp, stroke_width_p = stroke_points[i - 1]
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


class JsonPng(ImageExportBase):

    _output_scaling_factor = 100
    _base_pen_width = 3
    _pen_pressure_width_factor = 1

    def _convert(self):

        width, height = self.output_dimensions
        width, height = int(width), int(height)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)

        # Paint a transparent background
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()

        ctx.set_antialias(cairo.Antialias.DEFAULT)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_source_rgb(0, 0, 0)

        for sk_num, stroke_points in enumerate(self.output_strokes):
            for i, (x, y, stroke_width) in enumerate(stroke_points):
                ctx.set_line_width(stroke_width)

                if i == 0:
                    ctx.move_to(x, y)
                else:
                    ctx.line_to(x, y)

            ctx.stroke()

        surface.write_to_png(self.filename)
