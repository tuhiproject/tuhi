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

from gi.repository import Gtk, Gdk

from .setupperspective import SetupPerspective
from .drawingperspective import DrawingPerspective
from .errorperspective import ErrorPerspective
from .tuhi import TuhiKeteManager

import logging
import gi
gi.require_version("Gtk", "3.0")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('window')

MENU_XML = """
<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <menu id="primary-menu">
    <item>
        <attribute name="label">About</attribute>
        <attribute name="action">app.about</attribute>
    </item>
  </menu>
</interface>
"""


@Gtk.Template(resource_path='/org/freedesktop/TuhiGui/ui/MainWindow.ui')
class MainWindow(Gtk.ApplicationWindow):
    __gtype_name__ = 'MainWindow'

    stack_perspectives = Gtk.Template.Child()
    headerbar = Gtk.Template.Child()
    menubutton1 = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._tuhi = TuhiKeteManager()

        builder = Gtk.Builder.new_from_string(MENU_XML, -1)
        menu = builder.get_object("primary-menu")
        self.menubutton1.set_menu_model(menu)

        ep = ErrorPerspective()
        self._add_perspective(ep)
        self.stack_perspectives.set_visible_child_name(ep.name)

        # the dbus bindings need more async...
        if not self._tuhi.online:
            self._tuhi.connect('notify::online', self._on_dbus_online)
        else:
            self._on_dbus_online()

    def _on_dbus_online(self, *args, **kwargs):
        logger.debug('dbus is online')

        dp = DrawingPerspective()
        self._add_perspective(dp)

        if not self._tuhi.devices:
            sp = SetupPerspective(self._tuhi)
            sp.connect('new-device', self._on_new_device_registered)
            self._add_perspective(sp)
            active = sp
        else:
            dp.device = self._tuhi.devices[0]
            active = dp
            self.headerbar.set_title(f'Tuhi - {dp.device.name}')

        self.stack_perspectives.set_visible_child_name(active.name)

    def _on_new_device_registered(self, setupperspective, device):
        logger.debug('device was registered')
        setupperspective.disconnect_by_func(self._on_new_device_registered)

        self.headerbar.set_title(f'Tuhi - {device.name}')

        dp = self._get_child('drawing_perspective')
        dp.device = device
        self.stack_perspectives.set_visible_child_name(dp.name)

    def _add_perspective(self, perspective):
        self.stack_perspectives.add_named(perspective, perspective.name)

    def _get_child(self, name):
        return self.stack_perspectives.get_child_by_name(name)

    def _on_reconnect_tuhi(self, tuhi):
        self._tuhi = tuhi
