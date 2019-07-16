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

from .config import Config
from .svg import JsonSvg

import datetime
import time
import gi
gi.require_version("Gtk", "3.0")


def relative_date(timestamp):
    t = datetime.date.fromtimestamp(timestamp)
    today = datetime.date.today()
    diff = t - today

    if diff.days == 0:
        return 'Today'
    if diff.days == -1:
        return 'Yesterday'
    if diff.days > -4:  # last 4 days we convert to weekdays
        return t.strftime('%A')

    return t.strftime('%x')


@Gtk.Template(resource_path='/org/freedesktop/TuhiGui/ui/Drawing.ui')
class Drawing(Gtk.Box):
    __gtype_name__ = "Drawing"

    label_timestamp = Gtk.Template.Child()
    image_svg = Gtk.Template.Child()

    def __init__(self, json_data, *args, **kwargs):
        super().__init__()
        self.orientation = Config.instance().orientation

        self.json_data = json_data
        self.svg = svg = JsonSvg(json_data, orientation=self.orientation)
        day = relative_date(svg.timestamp)
        hour = time.strftime('%H:%M', time.localtime(svg.timestamp))

        self.label_timestamp.set_text(f'{day} {hour}')
        self.image_svg.set_from_file(svg.filename)
        self.timestamp = svg.timestamp

    def refresh(self):
        self.svg = svg = JsonSvg(self.json_data, self.orientation)
        self.image_svg.set_from_file(svg.filename)

    @GObject.Property
    def name(self):
        return "drawing"

    @Gtk.Template.Callback('_on_download_button_clicked')
    def _on_download_button_clicked(self, button):
        dialog = Gtk.FileChooserDialog('Please choose a file',
                                       None,
                                       Gtk.FileChooserAction.SAVE,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_SAVE, Gtk.ResponseType.OK))

        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name('untitled.svg')

        filter_any = Gtk.FileFilter()
        filter_any.set_name('Any files')
        filter_any.add_pattern('*')
        filter_svg = Gtk.FileFilter()
        filter_svg.set_name('SVG files')
        filter_svg.add_pattern('*.svg')
        dialog.add_filter(filter_svg)
        dialog.add_filter(filter_any)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            import shutil
            file = dialog.get_filename()
            shutil.copyfile(self.svg.filename, file)
            # FIXME: error handling

        dialog.destroy()

    @Gtk.Template.Callback('_on_delete_button_clicked')
    def _on_delete_button_clicked(self, button):
        Config.instance().delete_drawing(self.timestamp)

    @Gtk.Template.Callback('_on_rotate_button_clicked')
    def _on_rotate_button_clicked(self, button):
        orientations = ['portrait', 'landscape', 'reverse-portrait', 'reverse-landscape'] * 2
        o = orientations[orientations.index(self.orientation) + 1]
        self.orientation = o
        self.refresh()
