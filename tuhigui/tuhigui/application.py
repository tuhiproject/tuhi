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

from gi.repository import Gio, GLib, Gtk
from .window import MainWindow

import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.freedesktop.TuhiGui',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        GLib.set_application_name('TuhiGui')
        self._tuhi = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self._build_app_menu()

    def do_activate(self):
        window = MainWindow(application=self)
        window.present()

    def _build_app_menu(self):
        actions = [('about', self._about),
                   ('quit', self._quit),
                   ('help', self._help)]
        for (name, callback) in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)

    def _about(self, action, param):
        builder = Gtk.Builder().new_from_resource('/org/freedesktop/TuhiGui/AboutDialog.ui')
        about = builder.get_object('about_dialog')
        about.set_transient_for(self.get_active_window())
        about.connect('response', lambda about, param: about.destroy())
        about.show()

    def _quit(self, action, param):
        windows = self.get_windows()
        for window in windows:
            window.destroy()

    def _help(self, action, param):
        import time
        Gtk.show_uri(None, 'https://github.com/tuhiproject/tuhi/wiki', time.time())
