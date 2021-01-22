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

from .drawingperspective import DrawingPerspective
from .config import Config
from tuhi.dbusclient import TuhiDBusClientManager

from gettext import gettext as _
import logging

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, GObject  # NOQA

logger = logging.getLogger('tuhi.gui.window')


@Gtk.Template(resource_path="/org/freedesktop/Tuhi/ui/ErrorPerspective.ui")
class ErrorPerspective(Gtk.Box):
    '''
    The page loaded when we cannot connect to the Tuhi DBus server.
    '''
    __gtype_name__ = "ErrorPerspective"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @GObject.Property
    def name(self):
        return "error_perspective"


@Gtk.Template(resource_path="/org/freedesktop/Tuhi/ui/SetupPerspective.ui")
class SetupDialog(Gtk.Dialog):
    '''
    The setup dialog when we don't yet have a registered device with Tuhi.
    '''
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

    def _on_button_press_required(self, device):
        device.disconnect(self._sig)

        self.stack.set_visible_child_name('page2')
        self._sig = device.connect('registered', self._on_registered)

    def _on_registered(self, device):
        device.disconnect(self._sig)
        self.device = device
        self.response(Gtk.ResponseType.OK)

    @GObject.Property
    def name(self):
        return "setup_dialog"


@Gtk.Template(resource_path='/org/freedesktop/Tuhi/ui/MainWindow.ui')
class MainWindow(Gtk.ApplicationWindow):
    __gtype_name__ = 'MainWindow'

    stack_perspectives = Gtk.Template.Child()
    headerbar = Gtk.Template.Child()
    menubutton1 = Gtk.Template.Child()
    spinner_sync = Gtk.Template.Child()
    image_battery = Gtk.Template.Child()
    image_missing_tablet = Gtk.Template.Child()
    overlay_reauth = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.maximize()
        self._tuhi = TuhiDBusClientManager()

        action = Gio.SimpleAction.new_stateful('orientation', GLib.VariantType('s'),
                                               GLib.Variant('s', 'landscape'))
        action.connect('activate', self._on_orientation_changed)
        action.set_state(GLib.Variant.new_string(Config().orientation))
        self.add_action(action)

        builder = Gtk.Builder.new_from_resource('/org/freedesktop/Tuhi/ui/AppMenu.ui')
        menu = builder.get_object("primary-menu")
        self.menubutton1.set_menu_model(menu)

        ep = ErrorPerspective()
        self._add_perspective(ep)
        self.stack_perspectives.set_visible_child_name(ep.name)

        self._signals = []

        # the dbus bindings need more async...
        if not self._tuhi.online:
            self._tuhi.connect('notify::online', self._on_dbus_online)
        else:
            self._on_dbus_online()

    def _register_device(self):
        dialog = SetupDialog(self._tuhi)
        dialog.set_transient_for(self)
        dialog.connect('response', self._on_setup_dialog_closed)
        dialog.show()

    def _on_dbus_online(self, *args, **kwargs):
        logger.debug('dbus is online')

        dp = DrawingPerspective()
        self._add_perspective(dp)
        self.headerbar.set_title('Tuhi')
        self.stack_perspectives.set_visible_child_name(dp.name)

        if not self._tuhi.devices:
            self._register_device()
        else:
            device = self._tuhi.devices[0]
            self._init_device(device)
            dp.device = device
            self.headerbar.set_title(f'Tuhi - {dp.device.name}')

    def _init_device(self, device):
        sig = device.connect('notify::sync-state', self._on_sync_state)
        self._signals.append(sig)
        sig = device.connect('notify::battery-percent', self._on_battery_changed)
        self._signals.append(sig)
        sig = device.connect('notify::battery-state', self._on_battery_changed)
        self._signals.append(sig)
        sig = device.connect('device-error', self._on_device_error)
        self._signals.append(sig)
        self._on_battery_changed(device, None)

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
        self.image_missing_tablet.set_visible(False)
        if device.sync_state:
            self.spinner_sync.start()
        else:
            self.spinner_sync.stop()

    def _on_setup_dialog_closed(self, dialog, response):
        self.overlay_reauth.set_reveal_child(False)
        device = dialog.device
        dialog.destroy()

        if response != Gtk.ResponseType.OK or device is None:
            self.destroy()
            return

        logger.debug('device was registered')
        self.headerbar.set_title(f'Tuhi - {device.name}')

        dp = self._get_child('drawing_perspective')
        dp.device = device
        self._init_device(device)
        self.stack_perspectives.set_visible_child_name(dp.name)

    def _on_device_error(self, device, err):
        import errno
        logger.info(f'Device error: {err}')
        if err == -errno.EACCES:
            self.overlay_reauth.set_reveal_child(True)
            # No point to keep getting notified, it won't be able to
            # register.
            for sig in self._signals:
                device.disconnect(sig)
            self._signals = []

    def _add_perspective(self, perspective):
        self.stack_perspectives.add_named(perspective, perspective.name)

    def _get_child(self, name):
        return self.stack_perspectives.get_child_by_name(name)

    def _on_reconnect_tuhi(self, tuhi):
        self._tuhi = tuhi

    def _on_orientation_changed(self, action, label):
        action.set_state(label)
        Config().orientation = label.get_string()  # this is a GVariant

    @Gtk.Template.Callback('_on_zoom_changed')
    def _on_zoom_changed(self, adjustment):
        dp = self._get_child('drawing_perspective')
        dp.zoom = int(adjustment.get_value())

    @Gtk.Template.Callback('_on_reauth_clicked')
    def _on_reauth_clicked(self, button):
        self._register_device()
