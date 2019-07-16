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
from .config import Config

import time
import gi
import logging

gi.require_version("Gtk", "3.0")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('drawingperspective')


def relative_time(seconds):
    MIN = 60
    H = 60 * MIN
    DAY = 24 * H
    WEEK = 7 * DAY

    if seconds < 30:
        return 'just now'
    if seconds < 5 * MIN:
        return 'a few minutes ago'
    if seconds < H:
        return f'{int(seconds/MIN/10) * 10} minutes ago'
    if seconds < DAY:
        return f'{int(seconds/H)} hours ago'
    if seconds < 4 * WEEK:
        return f'{int(seconds/DAY)} days ago'
    if seconds > 10 * 365 * DAY:
        return 'never'

    return 'a long time ago'


@Gtk.Template(resource_path="/org/freedesktop/TuhiGui/ui/DrawingPerspective.ui")
class DrawingPerspective(Gtk.Stack):
    __gtype_name__ = "DrawingPerspective"

    image_battery = Gtk.Template.Child()
    flowbox_drawings = Gtk.Template.Child()
    spinner_sync = Gtk.Template.Child()
    label_last_sync = Gtk.Template.Child()
    overlay_undo = Gtk.Template.Child()
    notification_delete_undo = Gtk.Template.Child()
    notification_delete_close = Gtk.Template.Child()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.known_drawings = []
        self.last_sync_time = 0
        self._sync_label_timer = GObject.timeout_add_seconds(60, self._update_sync_label)
        self._update_sync_label()
        Config.load().connect('notify::orientation', self._on_orientation_changed)

    def _on_orientation_changed(self, config, pspec):
        # When the orientation changes, we just re-generate all SVGs. This
        # isn't something that should happen very often anyway so meh.
        self.known_drawings = []
        child = self.flowbox_drawings.get_child_at_index(0)
        while child is not None:
            self.flowbox_drawings.remove(child)
            child = self.flowbox_drawings.get_child_at_index(0)

        self._update_drawings(Config.load(), None)

    def _cache_drawings(self, device, pspec):
        # The config backend filters duplicates anyway, so don't care here
        for ts in self.device.drawings_available:
            json_string = self.device.json(ts)
            Config.load().add_drawing(ts, json_string)

    def _update_drawings(self, config, pspec):
        for js in config.drawings:
            if js in self.known_drawings:
                continue

            self.known_drawings.append(js)

            svg = JsonSvg(js)
            drawing = Drawing(svg)

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

        # Remove deleted ones
        deleted = [d for d in self.known_drawings if d not in config.drawings]
        for d in deleted:
            child = self.flowbox_drawings.get_child_at_index(0)
            while child is not None:
                if child.get_child().timestamp == d['timestamp']:
                    self.flowbox_drawings.remove(child)
                    self.known_drawings.remove(d)
                    self.notification_delete_undo.deleted_drawing = d['timestamp']
                    self.overlay_undo.set_reveal_child(True)
                    break
                child = self.flowbox_drawings.get_child_at_index(0)

    @GObject.Property
    def device(self):
        return self._device

    @device.setter
    def device(self, device):
        self._device = device

        device.connect('notify::connected', self._on_connected)
        device.connect('notify::listening', self._on_listening_stopped)
        device.connect('notify::sync-state', self._on_sync_state)
        device.connect('notify::battery-percent', self._on_battery_changed)
        device.connect('notify::battery-state', self._on_battery_changed)

        # This is a bit convoluted. We need to cache all drawings
        # because Tuhi doesn't have guaranteed storage. So any json that
        # comes in from Tuhi, we pass to our config backend to save
        # somewhere.
        # The config backend adds the json file and emits a notify for the
        # json itself (once cached) that we then actually use for SVG
        # generation.
        device.connect('notify::drawings-available', self._cache_drawings)
        Config.load().connect('notify::drawings', self._update_drawings)

        self._on_battery_changed(device, None)

        self._update_drawings(Config.load(), None)

        # We always want to sync on startup
        logger.debug(f'{device.name} - starting to listen')
        device.start_listening()

    @GObject.Property
    def name(self):
        return "drawing_perspective"

    def _on_battery_changed(self, device, pspec):
        if device.battery_percent > 80:
            fill = 'full'
        elif device.battery_percent > 40:
            fill = 'good'
        elif device.battery_percent > 10:
            fill = 'low'
        else:
            fill = 'caution'

        if device.battery_state == 1:
            state = '-charging'
        elif device.battery_state == 0:  # unknown
            fill = 'missing'
            state = ''
        else:
            state = ''
        batt_icon_name = f'battery-{fill}{state}-symbolic'
        _, isize = self.image_battery.get_icon_name()
        self.image_battery.set_from_icon_name(batt_icon_name, isize)
        self.image_battery.set_tooltip_text(f'{device.battery_percent}%')

    def _on_sync_state(self, device, pspec):
        if device.sync_state:
            self.spinner_sync.start()
        else:
            self.spinner_sync.stop()
            self.last_sync_time = time.time()
            self._update_sync_label()

    def _update_sync_label(self):
        now = time.time()
        self.label_last_sync.set_text(f'{relative_time(now - self.last_sync_time)}')
        return True

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
        Config.load().undelete_drawing(button.deleted_drawing)
        self.overlay_undo.set_reveal_child(False)
