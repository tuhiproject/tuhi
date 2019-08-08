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
from gi.repository import GObject, Gtk
from .drawing import Drawing
from .config import Config

import time
import gi
import logging

gi.require_version("Gtk", "3.0")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('tuhi.gui.drawingperspective')


@Gtk.Template(resource_path="/org/freedesktop/Tuhi/ui/Flowbox.ui")
class Flowbox(Gtk.Box):
    __gtype_name__ = "Flowbox"

    label_date = Gtk.Template.Child()
    flowbox_drawings = Gtk.Template.Child()

    def __init__(self, timestruct, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.time = timestruct
        self.label_date.set_text(time.strftime('%B %Y', self.time))

    def insert(self, drawing):
        # We don't know which order we get drawings from the device, so
        # let's do a sorted insert here
        index = 0
        child = self.flowbox_drawings.get_child_at_index(index)
        while child is not None:
            if child.get_child().timestamp < drawing.timestamp:
                break
            index += 1
            child = self.flowbox_drawings.get_child_at_index(index)

        self.flowbox_drawings.insert(drawing, index)

    def delete(self, drawing):
        def delete_matching_child(child, drawing):
            if child.get_child() == drawing:
                self.flowbox_drawings.remove(child)
        self.flowbox_drawings.foreach(delete_matching_child, drawing)

    @GObject.property
    def is_empty(self):
        return not self.flowbox_drawings.get_children()


@Gtk.Template(resource_path="/org/freedesktop/Tuhi/ui/DrawingPerspective.ui")
class DrawingPerspective(Gtk.Stack):
    __gtype_name__ = "DrawingPerspective"

    viewport = Gtk.Template.Child()
    overlay_undo = Gtk.Template.Child()
    notification_delete_undo = Gtk.Template.Child()
    notification_delete_close = Gtk.Template.Child()
    box_all_drawings = Gtk.Template.Child()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.known_drawings = {}  # type {timestamp: Drawing()}
        self.flowboxes = {}
        self._zoom = 0

    def _cache_drawings(self, device, pspec):
        # The config backend filters duplicates anyway, so don't care here
        for ts in self.device.drawings_available:
            json_string = self.device.json(ts)
            Config.instance().add_drawing(ts, json_string)

    def _update_drawings(self, config, pspec):
        def _hash(drawing):
            return time.strftime('%Y%m', time.gmtime(drawing.timestamp))

        for js in config.drawings:
            ts = js['timestamp']
            if ts in self.known_drawings:
                continue

            drawing = Drawing(js)
            self.known_drawings[ts] = drawing

            # Now pick the right monthly flowbox to insert into
            key = _hash(drawing)
            try:
                fb = self.flowboxes[key]
            except KeyError:
                fb = Flowbox(time.gmtime(drawing.timestamp))
                self.flowboxes[key] = fb
                self.box_all_drawings.add(fb)
            finally:
                fb.insert(drawing)

        # Remove deleted drawings
        deleted = [ts for ts in self.known_drawings if ts not in
                        [ js['timestamp'] for js in config.drawings]]
        for ts in deleted:
            drawing = self.known_drawings[ts]
            fb = self.flowboxes[_hash(drawing)]
            fb.delete(drawing)
            if fb.is_empty:
                del self.flowboxes[_hash(drawing)]
                self.box_all_drawings.remove(fb)
            del self.known_drawings[ts]
            self.notification_delete_undo.deleted_drawing = drawing.timestamp
            self.overlay_undo.set_reveal_child(True)

    @GObject.Property
    def device(self):
        return self._device

    @device.setter
    def device(self, device):
        self._device = device

        device.connect('notify::connected', self._on_connected)
        device.connect('notify::listening', self._on_listening_stopped)

        # This is a bit convoluted. We need to cache all drawings
        # because Tuhi doesn't have guaranteed storage. So any json that
        # comes in from Tuhi, we pass to our config backend to save
        # somewhere.
        # The config backend adds the json file and emits a notify for the
        # json itself (once cached) that we then actually use for SVG
        # generation.
        device.connect('notify::drawings-available', self._cache_drawings)
        Config.instance().connect('notify::drawings', self._update_drawings)

        self._update_drawings(Config.instance(), None)

        # We always want to sync on startup
        logger.debug(f'{device.name} - starting to listen')
        device.start_listening()

    @GObject.Property
    def name(self):
        return "drawing_perspective"

    @GObject.Property
    def zoom(self):
        return self._zoom

    @zoom.setter
    def zoom(self, zoom):
        if zoom == self._zoom:
            return

        self._zoom = zoom
        for ts, drawing in self.known_drawings.items():
            drawing.zoom = zoom

    def _on_connected(self, device, pspec):
        # Turns out we don't really care about whether the device is
        # connected or not, it has little effect on how we work here
        pass

    def _on_listening_stopped(self, device, pspec):
        if not device.listening:
            logger.debug(f'{device.name} - listening stopped, restarting')
            # We never want to stop listening
            device.start_listening()

    @Gtk.Template.Callback('_on_undo_close_clicked')
    def _on_undo_close_clicked(self, button):
        self.overlay_undo.set_reveal_child(False)

    @Gtk.Template.Callback('_on_undo_clicked')
    def _on_undo_clicked(self, button):
        Config.instance().undelete_drawing(button.deleted_drawing)
        self.overlay_undo.set_reveal_child(False)
