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

import xdg.BaseDirectory
import os
import json
from pathlib import Path
from .config import Config
from .splitter import Splitter
from tuhi.export import JsonSvg, JsonPng

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GObject, Gtk, GdkPixbuf, Gdk  # NOQA


DATA_PATH = Path(xdg.BaseDirectory.xdg_cache_home, 'tuhi')
SVG_DATA_PATH = Path(DATA_PATH, 'svg')
PNG_DATA_PATH = Path(DATA_PATH, 'png')


@Gtk.Template(resource_path='/org/freedesktop/Tuhi/ui/Drawing.ui')
class Drawing(Gtk.EventBox):
    __gtype_name__ = "Drawing"

    box_toolbar = Gtk.Template.Child()
    image_svg = Gtk.Template.Child()
    btn_rotate_left = Gtk.Template.Child()
    btn_rotate_right = Gtk.Template.Child()

    def __init__(self, json_data, zoom, *args, **kwargs):
        super().__init__()
        self.orientation = Config().orientation
        Config().connect('notify::orientation', self._on_orientation_changed)
        SVG_DATA_PATH.mkdir(parents=True, exist_ok=True)
        PNG_DATA_PATH.mkdir(parents=True, exist_ok=True)

        self.json_data = json_data
        self._zoom = zoom
        self.process_svg()  # sets self.svg
        self.redraw()

        self.timestamp = self.svg.timestamp
        self.box_toolbar.set_opacity(0)

    def _on_orientation_changed(self, config, pspec):
        self.orientation = config.orientation
        self.process_svg()
        self.redraw()

    def process_svg(self):
        path = os.fspath(Path(SVG_DATA_PATH, f'{self.json_data["timestamp"]}.svg'))
        self.svg = JsonSvg(
            self.json_data,
            self.orientation,
            path
        )
        width, height = -1, -1
        if 'portrait' in self.orientation:
            height = 1000
        else:
            width = 1000
        self.pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(filename=self.svg.filename,
                                                              width=width,
                                                              height=height,
                                                              preserve_aspect_ratio=True)

    def process_png(self):
        path = os.fspath(Path(PNG_DATA_PATH, f'{self.json_data["timestamp"]}.png'))
        self.png = JsonPng(
            self.json_data,
            self.orientation,
            path
        )

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
        dialog = Gtk.FileChooserNative()
        dialog.set_action(Gtk.FileChooserAction.SAVE)
        dialog.set_transient_for(self.get_toplevel())

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
        filter_png = Gtk.FileFilter()
        # Translators: filter to show png files only
        filter_png.set_name(_('PNG files'))
        filter_png.add_pattern('*.png')
        dialog.add_filter(filter_svg)
        dialog.add_filter(filter_png)
        dialog.add_filter(filter_any)

        response = dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            import shutil

            file = dialog.get_filename()

            if file.lower().endswith('.png'):
                # regenerate the PNG based on the current rotation.
                # where we used the orientation buttons, we haven't updated the
                # file itself.
                self.process_png()
                shutil.move(self.png.filename, file)
            else:
                # regenerate the SVG based on the current rotation.
                # where we used the orientation buttons, we haven't updated the
                # file itself.
                self.process_svg()
                shutil.copyfile(self.svg.filename, file)
                # FIXME: error handling

        dialog.destroy()

    @Gtk.Template.Callback('_on_split_button_clicked')
    def _on_split_button_clicked(self, button):
        dialog = Splitter(self)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self._save_split_drawings(*dialog.split_drawings)

        dialog.destroy()

    def _save_split_drawings(self, json1, json2):
        timestamp1 = json1["timestamp"]
        timestamp2 = json1["timestamp"]

        if timestamp2 in map(lambda d: d["timestamp"], Config().drawings):
            error_dialog = Gtk.MessageDialog(
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Error while splitting drawing"
            )
            error_dialog.format_secondary_text(
                    f"A drawing with timestamp {timestamp2} already exists. Cannot proceed to save split drawing, otherwise data loss might occur"
            )
            error_dialog.run()
            error_dialog.destroy()
            return

        Config().replace_drawing(timestamp1, json.dumps(json1))
        Config().add_drawing(timestamp2, json.dumps(json2))

        # Force redraw of this drawing
        os.remove(self.svg.filename)
        self.process_svg()
        self.redraw()

    @Gtk.Template.Callback('_on_delete_button_clicked')
    def _on_delete_button_clicked(self, button):
        Config().delete_drawing(self.timestamp)

    @Gtk.Template.Callback('_on_rotate_button_clicked')
    def _on_rotate_button_clicked(self, button):
        if button == self.btn_rotate_left:
            self.pixbuf = self.pixbuf.rotate_simple(GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE)
            advance = 1
        else:
            self.pixbuf = self.pixbuf.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
            advance = 3

        orientations = ['portrait', 'landscape', 'reverse-portrait', 'reverse-landscape'] * 3
        o = orientations[orientations.index(self.orientation) + advance]
        self.orientation = o
        self.redraw()

    @Gtk.Template.Callback('_on_enter')
    def _on_enter(self, *args):
        self.box_toolbar.set_opacity(100)

    @Gtk.Template.Callback('_on_leave')
    def _on_leave(self, drawing, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return
        self.box_toolbar.set_opacity(0)
