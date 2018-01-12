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

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('tuhi')

WACOM_COMPANY_ID = 0x4755


class Tuhi(GObject.Object):
    def __init__(self):
        self.server = TuhiDBusServer()
        self.bluez = BlueZDeviceManager()

        self.bluez.connect('device-added', self._on_device_added)
        self.bluez.connect_to_bluez()

    def _on_device_added(self, manager, device):
        if device.vendor_id != WACOM_COMPANY_ID:
            return

        device.connect('connected', self._on_device_connected)
        device.connect_device()

    def _on_device_connected(self, device):
        logger.debug('{}: connected'.format(device.address))

        d = WacomDevice(device)
        d.start()


def main(args):
    t = Tuhi()
    try:
        GObject.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        pass


if __name__ == "__main__":
    main(sys.argv)
