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

import gi
gi.require_version("Gtk", "3.0")


@Gtk.Template(resource_path="/org/freedesktop/TuhiGui/ui/SetupPerspective.ui")
class SetupDialog(Gtk.Dialog):
    __gtype_name__ = "SetupDialog"
    __gsignals__ = {
        'new-device':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    stack = Gtk.Template.Child()
    label_devicename_p1 = Gtk.Template.Child()
    btn_quit = Gtk.Template.Child()

    def __init__(self, tuhi, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tuhi = tuhi
        self._sig = tuhi.connect('unregistered-device', self._on_unregistered_device)
        tuhi.start_search()
        self.device = None

    def _on_unregistered_device(self, tuhi, device):
        tuhi.disconnect(self._sig)

        self.label_devicename_p1.set_text(_(f'Connecting to {device.name}'))
        self.stack.set_visible_child_name('page1')
        self._sig = device.connect('button-press-required', self._on_button_press_required)
        device.register()

    def _on_button_press_required(self, tuhi, device):
        tuhi.disconnect(self._sig)

        self.stack.set_visible_child_name('page2')
        self._sig = device.connect('registered', self._on_registered)

    def _on_registered(self, tuhi, device):
        tuhi.disconnect(self._sig)
        self.device = device
        self.response(Gtk.ResponseType.OK)

    @GObject.Property
    def name(self):
        return "setup_dialog"
