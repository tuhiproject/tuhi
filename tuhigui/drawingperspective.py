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

from gi.repository import GObject, Gtk
from .drawing import Drawing
from .svg import JsonSvg

import json
import gi
gi.require_version("Gtk", "3.0")


@Gtk.Template(resource_path="/org/freedesktop/TuhiGui/ui/DrawingPerspective.ui")
class DrawingPerspective(Gtk.Stack):
    __gtype_name__ = "DrawingPerspective"

    label_devicename = Gtk.Template.Child()
    image_battery = Gtk.Template.Child()
    flowbox_drawings = Gtk.Template.Child()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _init_drawings(self):
        for ts in self.device.drawings_available:
            js = json.loads(self.device.json(ts))
            svg = JsonSvg(js)
            drawing = Drawing(svg)
            self.flowbox_drawings.add(drawing)

    @GObject.Property
    def device(self):
        return self._device

    @device.setter
    def device(self, device):
        self._device = device
        self.label_devicename.set_text(f'{device.name} - {device.address}')

        # icon name is something like battery-020-charging, or battery-040
        # in 20-step increments
        if device.battery_state == 1:
            state = '-charging'
        else:
            state = ''
        percent = f'{int(device.battery_percent/20):03d}'
        batt_icon_name = f'battery-{percent}{state}'
        _, isize = self.image_battery.get_icon_name()
        self.image_battery.set_from_icon_name(batt_icon_name, isize)
        self._init_drawings()

    @GObject.Property
    def name(self):
        return "drawing_perspective"

    @Gtk.Template.Callback("_on_sync_button_clicked")
    def _on_quit_button_clicked(self, button):
        button.set_label('Stop')
        print('sync now')
