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
import logging

from .window import MainWindow
from .config import Config
import xdg.BaseDirectory
from pathlib import Path

import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")


logging.basicConfig(format='%(asctime)s %(levelname)s: %(name)s: %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S')
logger = logging.getLogger('tuhi.gui')

DEFAULT_CONFIG_PATH = Path(xdg.BaseDirectory.xdg_data_home, 'tuhi')


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.freedesktop.Tuhi',
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name('Tuhi')
        self.add_main_option('config-dir', 0,
                             GLib.OptionFlags.NONE,
                             GLib.OptionArg.STRING,
                             'path to configuration directory',
                             '/path/to/config-dir')
        self.add_main_option('verbose', 0,
                             GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE,
                             'enable verbose output')
        self._tuhi = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self._build_app_menu()

    def do_activate(self):
        window = MainWindow(application=self)
        window.present()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        # convert GVariantDict -> GVariant -> dict
        options = options.end().unpack()

        try:
            Config.set_base_path(options['config-dir'])
        except KeyError:
            Config.set_base_path(DEFAULT_CONFIG_PATH)

        if 'verbose' in options:
            logger.setLevel(logging.DEBUG)

        self.activate()
        return 0

    def _build_app_menu(self):
        actions = [('about', self._about),
                   ('quit', self._quit),
                   ('help', self._help)]
        for (name, callback) in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)

    def _about(self, action, param):
        builder = Gtk.Builder().new_from_resource('/org/freedesktop/Tuhi/AboutDialog.ui')
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
