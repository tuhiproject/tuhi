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

import logging
import sys
from gi.repository import GObject

from tuhi.dbusserver import TuhiDBusServer
from tuhi.ble import BlueZDeviceManager
from tuhi.wacom import WacomDevice

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('tuhi')

WACOM_COMPANY_ID = 0x4755


class TuhiDevice(GObject.Object):
    """
    Glue object to combine the backend bluez DBus object (that talks to the
    real device) with the frontend DBusServer object that exports the device
    over Tuhi's DBus interface
    """
    __gsignals__ = {
        "drawings-updated":
            (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self, bluez_device, tuhi_dbus_device):
        GObject.Object.__init__(self)
        self._tuhi_dbus_device = tuhi_dbus_device
        self._wacom_device = WacomDevice(bluez_device)
        self._wacom_device.connect('drawing', self._on_drawing_received)
        self.drawings = []

        bluez_device.connect('connected', self._on_bluez_device_connected)
        bluez_device.connect('disconnected', self._on_bluez_device_disconnected)
        bluez_device.connect_device()

    def _on_bluez_device_connected(self, bluez_device):
        logger.debug('{}: connected'.format(bluez_device.address))
        self._wacom_device.start()

    def _on_bluez_device_disconnected(self, bluez_device):
        # FIXME: immediately try to reconnect, at least until the DBusServer
        # is hooked up correctly
        logger.debug('{}: disconnected'.format(bluez_device.address))
        bluez_device.connect_device()

    def _on_drawing_received(self, device, drawing):
        logger.debug('Drawing received')
        self.drawings.append(drawing)
        self.emit('drawings-updated', self.drawings)


class Tuhi(GObject.Object):
    __gsignals__ = {
        "device-added":
            (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        "device-connected":
            (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self):
        GObject.Object.__init__(self)
        self.server = TuhiDBusServer()
        self.server.connect('bus-name-acquired', self._on_tuhi_bus_name_acquired)
        self.bluez = BlueZDeviceManager()
        self.bluez.connect('device-added', self._on_bluez_device_added)

        self.devices = {}

    def _on_tuhi_bus_name_acquired(self, dbus_server):
        self.bluez.connect_to_bluez()

    def _on_bluez_device_added(self, manager, bluez_device):
        if bluez_device.vendor_id != WACOM_COMPANY_ID:
            return

        tuhi_dbus_device = self.server.create_device(bluez_device)
        d = TuhiDevice(bluez_device, tuhi_dbus_device)
        self.devices[bluez_device.address] = d


def main(args):
    Tuhi()
    try:
        GObject.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        pass


if __name__ == "__main__":
    main(sys.argv)
