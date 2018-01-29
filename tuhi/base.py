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

import argparse
import logging
import sys
from gi.repository import GObject

from tuhi.dbusserver import TuhiDBusServer
from tuhi.ble import BlueZDeviceManager
from tuhi.wacom import WacomDevice
from tuhi.config import TuhiConfig

logging.basicConfig(format='%(levelname)s: %(name)s: %(message)s',
                    level=logging.INFO)
logger = logging.getLogger('tuhi')

WACOM_COMPANY_ID = 0x4755


class TuhiDevice(GObject.Object):
    """
    Glue object to combine the backend bluez DBus object (that talks to the
    real device) with the frontend DBusServer object that exports the device
    over Tuhi's DBus interface
    """
    __gsignals__ = {
        # Signal sent when an error occurs on the device itself.
        # Argument is a Wacom*Exception
        'device-error':
            (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self, bluez_device, config, uuid=None, paired=True):
        GObject.Object.__init__(self)
        self.config = config
        self._wacom_device = None
        # We need either uuid or paired as false
        assert uuid is not None or paired is False
        self.paired = paired
        self._uuid = uuid

        bluez_device.connect('connected', self._on_bluez_device_connected)
        bluez_device.connect('disconnected', self._on_bluez_device_disconnected)
        self._bluez_device = bluez_device

        self._tuhi_dbus_device = None

    @GObject.Property
    def paired(self):
        return self._paired

    @paired.setter
    def paired(self, paired):
        self._paired = paired

    @property
    def name(self):
        return self._bluez_device.name

    @property
    def address(self):
        return self._bluez_device.address

    @property
    def dbus_device(self):
        return self._tuhi_dbus_device

    @dbus_device.setter
    def dbus_device(self, device):
        assert self._tuhi_dbus_device is None
        self._tuhi_dbus_device = device
        self._tuhi_dbus_device.connect('pair-requested', self._on_pair_requested)
        self._tuhi_dbus_device.connect('notify::listening', self._on_listening_updated)

        drawings = self.config.load_drawings(self.address)
        if drawings:
            logger.debug(f'{self.address}: loaded {len(drawings)} drawings from disk')
        for d in drawings:
            self._tuhi_dbus_device.add_drawing(d)

    @GObject.Property
    def listening(self):
        return self._tuhi_dbus_device.listening

    def connect_device(self):
        self._bluez_device.connect_device()

    def _on_bluez_device_connected(self, bluez_device):
        logger.debug('{}: connected'.format(bluez_device.address))
        if self._wacom_device is None:
            self._wacom_device = WacomDevice(bluez_device, self._uuid)
            self._wacom_device.connect('drawing', self._on_drawing_received)
            self._wacom_device.connect('done', self._on_fetching_finished, bluez_device)
            self._wacom_device.connect('button-press-required', self._on_button_press_required)
            self._wacom_device.connect('notify::uuid', self._on_uuid_updated, bluez_device)

        self._wacom_device.start(not self.paired)
        self.pairing_mode = False

    def _on_bluez_device_disconnected(self, bluez_device):
        logger.debug('{}: disconnected'.format(bluez_device.address))

    def _on_pair_requested(self, dbus_device):
        if self.paired:
            return

        self.connect_device()

    def _on_drawing_received(self, device, drawing):
        logger.debug('Drawing received')
        self._tuhi_dbus_device.add_drawing(drawing)
        self.config.store_drawing(self.address, drawing)

    def _on_fetching_finished(self, device, exception, bluez_device):
        bluez_device.disconnect_device()
        if exception is not None:
            logger.info(exception)
            self.emit('device-error', exception)

    def _on_button_press_required(self, device):
        self._tuhi_dbus_device.notify_button_press_required()

    def _on_uuid_updated(self, wacom_device, pspec, bluez_device):
        self.config.new_device(bluez_device.address, wacom_device.uuid)
        self.paired = True

    def _on_listening_updated(self, dbus_device, pspec):
        self.notify('listening')


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
        self.server.connect('bus-name-lost', self._on_tuhi_bus_name_lost)
        self.server.connect('search-start-requested', self._on_start_search_requested)
        self.server.connect('search-stop-requested', self._on_stop_search_requested)
        self.bluez = BlueZDeviceManager()
        self.bluez.connect('device-added', self._on_bluez_device_updated)
        self.bluez.connect('device-updated', self._on_bluez_device_updated)
        self.bluez.connect('discovery-started', self._on_bluez_discovery_started)
        self.bluez.connect('discovery-stopped', self._on_bluez_discovery_stopped)

        self.config = TuhiConfig()

        self.devices = {}

        self._search_stop_handler = None
        self.mainloop = GObject.MainLoop()

    def _on_tuhi_bus_name_acquired(self, dbus_server):
        self.bluez.connect_to_bluez()

    def _on_tuhi_bus_name_lost(self, dbus_server):
        self.mainloop.quit()

    def _on_start_search_requested(self, dbus_server, stop_handler):
        self._search_stop_handler = stop_handler
        self.bluez.start_discovery()

    def _on_stop_search_requested(self, dbus_server):
        # If you request to stop, you get a successful stop and we ignore
        # anything the server does underneath
        self._search_stop_handler(0)
        self._search_stop_handler = None
        self.bluez.stop_discovery()
        self._search_device_handler = None

    @classmethod
    def _is_pairing_device(cls, bluez_device):
        if bluez_device.vendor_id != WACOM_COMPANY_ID:
            return False

        manufacturer_data = bluez_device.get_manufacturer_data(WACOM_COMPANY_ID)
        return manufacturer_data is not None and len(manufacturer_data) == 4

    def _on_bluez_discovery_started(self, manager):
        # Something else may turn discovery mode on, we don't care about
        # it then
        if not self._search_stop_handler:
            return

    def _on_bluez_discovery_stopped(self, manager):
        if self._search_stop_handler is not None:
            self._search_stop_handler(0)

        # restart discovery if some users are already in the listening mode
        self._on_listening_updated(None, None)

    def _on_bluez_device_updated(self, manager, bluez_device, event=True):
        uuid = None

        # check if the device is already known by us
        try:
            config = self.config.devices[bluez_device.address]
            uuid = config['uuid']
        except KeyError:
            pass

        if uuid is None and bluez_device.vendor_id != WACOM_COMPANY_ID:
            return

        # if event is set, the device has been 'hotplugged' in the bluez stack
        # so ManufacturerData is reliable. Else, consider the device not in
        # the pairing mode
        pairing_device = False
        if event:
            pairing_device = Tuhi._is_pairing_device(bluez_device)

        if not pairing_device:
            if uuid is None:
                logger.info('{}: device without config, must be paired first'.format(bluez_device.address))
                return
            logger.debug('{}: UUID {}'.format(bluez_device.address, uuid))

        # create the device if unknown from us
        if bluez_device.address not in self.devices:
                d = TuhiDevice(bluez_device, self.config, uuid=uuid, paired=not pairing_device)
                d.dbus_device = self.server.create_device(d)
                d.connect('notify::listening', self._on_listening_updated)
                self.devices[bluez_device.address] = d

        d = self.devices[bluez_device.address]

        if pairing_device:
            d.paired = False
            logger.debug('{}: call Pair() on device'.format(bluez_device.objpath))
        elif d.listening:
            d.connect_device()

    def _on_listening_updated(self, tuhi_dbus_device, pspec):
        listen = False
        for dev in self.devices.values():
            if dev.listening:
                listen = True
                break

        if listen:
            self.bluez.start_discovery()
        else:
            self.bluez.stop_discovery()

    def run(self):
        self.mainloop.run()


def main(args=sys.argv):
    desc = "Daemon to extract the pen stroke data from Wacom SmartPad devices"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument('-v', '--verbose',
                        help='Show some debugging informations',
                        action='store_true',
                        default=False)

    ns = parser.parse_args(args[1:])
    if ns.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        Tuhi().run()
    except KeyboardInterrupt:
        pass
    finally:
        pass
