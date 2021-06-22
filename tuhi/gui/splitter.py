#!/usr/bin/env python3
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#

from gettext import gettext as _

import xdg.BaseDirectory
import os
import math
from pathlib import Path
from .config import Config
from tuhi.export import JsonPartialSvg
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GObject, Gtk, GdkPixbuf, Gdk  # NOQA
import cairo


DATA_PATH = Path(xdg.BaseDirectory.xdg_cache_home, 'tuhi')
SVG_DATA_PATH = Path(DATA_PATH, 'svg')
PNG_DATA_PATH = Path(DATA_PATH, 'png')


@Gtk.Template(resource_path='/org/freedesktop/Tuhi/ui/Splitter.ui')
class Splitter(Gtk.Dialog):
    __gtype_name__ = "Splitter"

    adjustment = Gtk.Template.Child("split_adjustment")
    ok_button = Gtk.Template.Child("ok_button")
    cancel_button = Gtk.Template.Child("cancel_button")
    drawing_area = Gtk.Template.Child("drawing_area")

    def __init__(self, json_data):
        super().__init__()
        self.json_data = json_data
        self.orientation = Config().orientation

        self.num_strokes = len(self.json_data["strokes"])
        self.max_strokes = self.num_strokes
        self.adjustment.set_upper(self.num_strokes)
        self.adjustment.connect("value-changed", self._on_split_value_changed)
        self.adjustment.set_value(self.num_strokes)
        self.drawing_area.connect("draw", self._on_draw_image)





    @Gtk.Template.Callback('_on_cancel')
    def _on_cancel(self, button):
        super().response(Gtk.ResponseType.CANCEL)
        print("CANCEL")

    @Gtk.Template.Callback('_on_ok')
    def _on_ok(self, button):
        super().response(Gtk.ResponseType.OK)
        print("OK")

    def _on_split_value_changed(self, adjustment):
        self.max_strokes = int(adjustment.get_value())
        self.drawing_area.queue_draw()

    def _on_draw_image(self, widget, cr):
        display_width, display_height = float(widget.get_allocated_width()), float(widget.get_allocated_height())

        dimensions = self.json_data["dimensions"]

        drawing_width, drawing_height = -1, -1

        if self.orientation in ['portrait', 'reverse-portrait']:
            drawing_width = float(dimensions[1])
            drawing_height = float(dimensions[0])
        else:
            drawing_width = float(dimensions[0])
            drawing_height = float(dimensions[1])


        aspect_ratio = drawing_width / drawing_height

        # Calculate margins and true display width to keep aspect ratio
        margin_x, margin_y = 0.0, 0.0
        if (display_width / display_height) < aspect_ratio:
            reduced_display_height = display_width / aspect_ratio
            margin_y = display_height - reduced_display_height
            display_height = reduced_display_height
        else:
            reduced_display_width = display_height * aspect_ratio
            margin_x = display_width - reduced_display_width
            display_width = reduced_display_width

        # Set up Cairo's transformation matrix to convert from Wacom device
        # coordinates to display coordinates (pixels)

        transform_matrix = cairo.Matrix()
        if self.orientation == 'reverse-portrait':
            transform_matrix = cairo.Matrix(xx=0.0,  xy=1.0,
                                            yx=-1.0, yy=0.0,
                                            x0=0.0,  y0=1.0)
        elif self.orientation == 'portrait':
            transform_matrix = cairo.Matrix(xx=0.0, xy=-1.0,
                                            yx=1.0, yy=0.0,
                                            x0=1.0, y0=0.0)
        elif self.orientation == 'reverse-landscape':
            transform_matrix = cairo.Matrix(xx=-1.0, xy=0.0,
                                            yx=0.0,  yy=-1.0,
                                            x0=1.0,  y0=1.0)

        # Apply Transformations:
        # 1. Normalize device coordinates to [0, 1] x [0, 1]
        # 2. Apply orientation specific transformation
        # 3. Scale up to display size in pixels
        # 4. Translate by half the margin to keep it centered
        #
        # In Code they are listed in reverse order, since transformations that
        # are multiplied last into the transformation matrix apply first.

        cr.translate(margin_x / 2.0, margin_y / 2.0)
        cr.scale(display_width, display_height)
        cr.transform(transform_matrix)
        cr.scale(1.0 / dimensions[0], 1.0 / dimensions[1])

        cr.set_line_width(300) # 0.3mm
        cr.set_source_rgb(0.0, 0.0, 0.0) # black
        cr.set_line_cap(cairo.LineCap.ROUND)

        for stroke in self.json_data["strokes"][:self.max_strokes]:
            cr.new_path()

            for iteration, point in enumerate(stroke["points"]):
                x, y = point["position"]

                if iteration == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)

            cr.stroke()

