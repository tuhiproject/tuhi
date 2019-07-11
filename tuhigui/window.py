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

import gi
gi.require_version("Gtk", "3.0")


@Gtk.Template(resource_path='/org/freedesktop/TuhiGui/ui/MainWindow.ui')
class MainWindow(Gtk.ApplicationWindow):
    __gtype_name__ = 'MainWindow'

    stack_perspectives = Gtk.Template.Child()
    primary_menu = Gtk.Template.Child()
    headerbar = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._tuhi = TuhiKeteManager()

        ep = ErrorPerspective()
        self._add_perspective(ep)
        self.stack_perspectives.set_visible_child_name(ep.name)

        # the dbus bindings need more async...
        if not self._tuhi.online:
            self._tuhi.connect('notify::online', self._on_dbus_online)
        else:
            self._on_dbus_online()

        self._add_primary_menu()

    def _on_dbus_online(self, *args, **kwargs):
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

        self.stack_perspectives.set_visible_child_name(active.name)

    def _on_new_device_registered(self, setupperspective, device):
        setupperspective.disconnect_by_func(self._on_new_device_registered)

        dp = self._get_child('drawing_perspective')
        dp.device = device
        self.stack_perspectives.set_visible_child_name(dp.name)

    def _add_perspective(self, perspective):
        self.stack_perspectives.add_named(perspective, perspective.name)

    def _get_child(self, name):
        return self.stack_perspectives.get_child_by_name(name)

    def _add_primary_menu(self):
        hamburger = Gtk.Image.new_from_icon_name("open-menu-symbolic",
                                                 Gtk.IconSize.BUTTON)
        hamburger.set_visible(True)
        button_primary_menu = Gtk.MenuButton.new()
        button_primary_menu.add(hamburger)
        button_primary_menu.set_visible(True)
        button_primary_menu.set_menu_model(self.primary_menu)
        self.headerbar.pack_end(button_primary_menu)
        # Place the button last in the titlebar.
        self.headerbar.child_set_property(button_primary_menu, "position", 0)

    def _on_reconnect_tuhi(self, tuhi):
        self._tuhi = tuhi

    @Gtk.Template.Callback("_on_quit_button_clicked")
    def _on_quit_button_clicked(self, button):
        window = button.get_toplevel()
        if not window.emit("delete-event", Gdk.Event.new(Gdk.EventType.DELETE)):
            window.destroy()
