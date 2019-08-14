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

from gettext import gettext as _
from gi.repository import GObject, Gtk, GdkPixbuf, Gdk

import xdg.BaseDirectory
import os
from pathlib import Path
from .config import Config
from tuhi.svg import JsonSvg

import gi
gi.require_version("Gtk", "3.0")

DATA_PATH = Path(xdg.BaseDirectory.xdg_cache_home, 'tuhi', 'svg')


@Gtk.Template(resource_path='/org/freedesktop/Tuhi/ui/Drawing.ui')
class Drawing(Gtk.EventBox):
    __gtype_name__ = "Drawing"

    box_toolbar = Gtk.Template.Child()
    image_svg = Gtk.Template.Child()
    btn_rotate_left = Gtk.Template.Child()
    btn_rotate_right = Gtk.Template.Child()

    def __init__(self, json_data, *args, **kwargs):
        super().__init__()
        self.orientation = Config.instance().orientation
        Config.instance().connect('notify::orientation', self._on_orientation_changed)
        DATA_PATH.mkdir(parents=True, exist_ok=True)

        self.json_data = json_data
        self._zoom = 0
        self.refresh()  # sets self.svg

        self.timestamp = self.svg.timestamp
        self.box_toolbar.set_opacity(0)

    def _on_orientation_changed(self, config, pspec):
        self.orientation = config.orientation
        self.refresh()

    def refresh(self):
        path = os.fspath(Path(DATA_PATH, f'{self.json_data["timestamp"]}.svg'))
        self.svg = JsonSvg(self.json_data, self.orientation, path)
        width, height = -1, -1
        if 'portrait' in self.orientation:
            height = 1000
        else:
            width = 1000
        self.pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(filename=self.svg.filename,
                                                              width=width,
                                                              height=height,
                                                              preserve_aspect_ratio=True)
        self.redraw()

    def redraw(self):
        ratio = self.pixbuf.get_height() / self.pixbuf.get_width()
        base = 250 + self.zoom * 50
        if 'portrait' in self.orientation:
            width = base / ratio
            height = base
        else:
            width = base
            height = base * ratio
        pb = self.pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
        self.image_svg.set_from_pixbuf(pb)

    @GObject.Property
    def name(self):
        return "drawing"

    @GObject.Property
    def zoom(self):
        return self._zoom

    @zoom.setter
    def zoom(self, zoom):
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self.redraw()

    @Gtk.Template.Callback('_on_download_button_clicked')
    def _on_download_button_clicked(self, button):
        dialog = Gtk.FileChooserDialog(_('Please choose a file'),
                                       None,
                                       Gtk.FileChooserAction.SAVE,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_SAVE, Gtk.ResponseType.OK))

        dialog.set_do_overwrite_confirmation(True)
        # Translators: the default filename to save to
        dialog.set_current_name(_('untitled.svg'))

        filter_any = Gtk.FileFilter()
        # Translators: filter name to show all/any files
        filter_any.set_name(_('Any files'))
        filter_any.add_pattern('*')
        filter_svg = Gtk.FileFilter()
        # Translators: filter to show svg files only
        filter_svg.set_name(_('SVG files'))
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
        if button == self.btn_rotate_left:
            advance = 1
        else:
            advance = 3

        orientations = ['portrait', 'landscape', 'reverse-portrait', 'reverse-landscape'] * 3
        o = orientations[orientations.index(self.orientation) + advance]
        self.orientation = o
        self.refresh()

    @Gtk.Template.Callback('_on_enter')
    def _on_enter(self, *args):
        self.box_toolbar.set_opacity(100)

    @Gtk.Template.Callback('_on_leave')
    def _on_leave(self, drawing, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return
        self.box_toolbar.set_opacity(0)
