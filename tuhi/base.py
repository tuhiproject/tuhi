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
import enum
import logging
import sys
import time
from gi.repository import GObject, GLib

from tuhi.dbusserver import TuhiDBusServer
from tuhi.ble import BlueZDeviceManager
from tuhi.wacom import WacomDevice, DeviceMode
from tuhi.config import TuhiConfig

logging.basicConfig(format='%(levelname)s: %(name)s: %(message)s',
                    level=logging.INFO)
logger = logging.getLogger('tuhi')

WACOM_COMPANY_IDS = [0x4755]


class TuhiDevice(GObject.Object):
    '''
    Glue object to combine the backend bluez DBus object (that talks to the
    real device) with the frontend DBusServer object that exports the device
    over Tuhi's DBus interface
    '''

    class BatteryState(enum.Enum):
        UNKNOWN = 0
        CHARGING = 1
        DISCHARGING = 2

    __gsignals__ = {
        # Signal sent when an error occurs on the device itself.
        # Argument is a Wacom*Exception
        'device-error':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    BATTERY_UPDATE_MIN_INTERVAL = 300

    def __init__(self, bluez_device, config, uuid=None, mode=DeviceMode.LISTEN):
        GObject.Object.__init__(self)
        self.config = config
        self._wacom_device = None
        # We need either uuid or registered as false
        assert uuid is not None or mode == DeviceMode.REGISTER
        self._mode = mode
        self._battery_state = TuhiDevice.BatteryState.UNKNOWN
        self._battery_percent = 0
        self._last_battery_update_time = 0
        self._battery_timer_source = None
        self._signals = {}

        self._bluez_device = bluez_device

        self._tuhi_dbus_device = None

    @GObject.Property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, mode):
        if self._mode != mode:
            self._mode = mode
            self.notify('registered')

    @GObject.Property
    def registered(self):
        return self.mode == DeviceMode.LISTEN

    @GObject.Property
    def name(self):
        return self._bluez_device.name

    @GObject.Property
    def address(self):
        return self._bluez_device.address

    @GObject.Property
    def bluez_device(self):
        return self._bluez_device

    @GObject.Property
    def dbus_device(self):
        return self._tuhi_dbus_device

    @dbus_device.setter
    def dbus_device(self, device):
        assert self._tuhi_dbus_device is None
        self._tuhi_dbus_device = device
        self._tuhi_dbus_device.connect('register-requested', self._on_register_requested)
        self._tuhi_dbus_device.connect('notify::listening', self._on_listening_updated)

        drawings = self.config.load_drawings(self.address)
        if drawings:
            logger.debug(f'{self.address}: loaded {len(drawings)} drawings from disk')
        for d in drawings:
            self._tuhi_dbus_device.add_drawing(d)

    @GObject.Property
    def listening(self):
        return self._tuhi_dbus_device.listening

    @GObject.Property
    def battery_percent(self):
        return self._battery_percent

    @battery_percent.setter
    def battery_percent(self, value):
        self._battery_percent = value

    @GObject.Property
    def battery_state(self):
        return self._battery_state

    @battery_state.setter
    def battery_state(self, value):
        self._battery_state = value

    def _connect_device(self, mode):
        self._signals['connected'] = self._bluez_device.connect('connected', self._on_bluez_device_connected, mode)
        self._signals['disconnected'] = self._bluez_device.connect('disconnected', self._on_bluez_device_disconnected)
        self._bluez_device.connect_device()

    def register(self):
        self._connect_device(DeviceMode.REGISTER)

    def listen(self):
        self._connect_device(DeviceMode.LISTEN)

    def _on_bluez_device_connected(self, bluez_device, mode):
        logger.debug(f'{bluez_device.address}: connected for {mode}')
        if self._wacom_device is None:
            self._wacom_device = WacomDevice(bluez_device, self.config)
            self._wacom_device.connect('drawing', self._on_drawing_received)
            self._wacom_device.connect('done', self._on_fetching_finished, bluez_device)
            self._wacom_device.connect('button-press-required', self._on_button_press_required)
            self._wacom_device.connect('notify::uuid', self._on_uuid_updated, bluez_device)
            self._wacom_device.connect('battery-status', self._on_battery_status, bluez_device)

        if mode == DeviceMode.REGISTER:
            self._wacom_device.start_register()
        else:
            self._wacom_device.start_listen()

        try:
            bluez_device.disconnect(self._signals['connected'])
            del self._signals['connected']
        except KeyError:
            pass

    def _on_bluez_device_disconnected(self, bluez_device):
        logger.debug(f'{bluez_device.address}: disconnected')
        try:
            bluez_device.disconnect(self._signals['disconnected'])
            del self._signals['disconnected']
        except KeyError:
            pass

    def _on_register_requested(self, dbus_device):
        # FIXME: this needs to throw an exception/return the value
        if self.mode == DeviceMode.LISTEN:
            return

        self.register()

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
        self.config.new_device(bluez_device.address, wacom_device.uuid, wacom_device.protocol)
        # FIXME: we have registered and that *should* set us to listen. But
        # the ManufacturerData doesn't update until (some time into) the
        # next connection request.
        self.mode = DeviceMode.LISTEN

    def _on_listening_updated(self, dbus_device, pspec):
        self.notify('listening')

    def _on_battery_status(self, wacom_device, percent, is_charging, bluez_device):
        if is_charging:
            self.battery_state = TuhiDevice.BatteryState.CHARGING
        else:
            self.battery_state = TuhiDevice.BatteryState.DISCHARGING
        self.battery_percent = percent

        # If we don't get battery updates for a while, switch the state
        # to unknown
        if self._battery_timer_source is not None:
            GObject.source_remove(self._battery_timer_source)
        self._battery_timer_source = \
            GObject.timeout_add_seconds(self.BATTERY_UPDATE_MIN_INTERVAL,
                                        self._on_battery_timeout)
        self._last_battery_update_time = time.time()

    def _on_battery_timeout(self):
        if self._last_battery_update_time < time.time() - self.BATTERY_UPDATE_MIN_INTERVAL:
            self.battery_state = TuhiDevice.BatteryState.UNKNOWN
        self._battery_timer_source = None  # gets auto-destroyed
        return False


class Tuhi(GObject.Object):
    __gsignals__ = {
        'device-added':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        'device-connected':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self):
        GObject.Object.__init__(self)
        self.server = TuhiDBusServer()
        self.server.connect('bus-name-acquired', self._on_tuhi_bus_name_acquired)
        self.server.connect('bus-name-lost', self._on_tuhi_bus_name_lost)
        self.server.connect('search-start-requested', self._on_start_search_requested)
        self.server.connect('search-stop-requested', self._on_stop_search_requested)
        self.bluez = BlueZDeviceManager()
        self.bluez.connect('discovery-started', self._on_bluez_discovery_started)
        self.bluez.connect('discovery-stopped', self._on_bluez_discovery_stopped)

        self.config = TuhiConfig()

        self.devices = {}

        self._search_stop_handler = None
        self.mainloop = GLib.MainLoop()

    def _on_tuhi_bus_name_acquired(self, dbus_server):
        self.bluez.connect_to_bluez()
        for dev in self.bluez.devices:
            self._add_device(self.bluez, dev)

        self.bluez.connect('device-added', self._on_bluez_device_updated)
        self.bluez.connect('device-updated', self._on_bluez_device_updated)

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
    def _device_in_register_mode(cls, bluez_device):
        if bluez_device.vendor_id not in WACOM_COMPANY_IDS:
            return False

        manufacturer_data = bluez_device.manufacturer_data
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

    def _add_device(self, manager, bluez_device, hotplugged=False):
        uuid = None

        # check if the device is already known by us
        try:
            config = self.config.devices[bluez_device.address]
            uuid = config['uuid']
        except KeyError:
            pass

        if uuid is None and bluez_device.vendor_id not in WACOM_COMPANY_IDS:
            return

        # if the device has been 'hotplugged' in the bluez stack,
        # ManufacturerData is reliable. Else, consider the device not in
        # register mode
        if hotplugged and Tuhi._device_in_register_mode(bluez_device):
            mode = DeviceMode.REGISTER
        else:
            mode = DeviceMode.LISTEN
            if uuid is None:
                logger.info(f'{bluez_device.address}: device without config, must be registered first')
                return
            logger.debug(f'{bluez_device.address}: UUID {uuid} protocol: {config["Protocol"]}')

        # create the device if unknown from us
        if bluez_device.address not in self.devices:
                d = TuhiDevice(bluez_device, self.config, uuid, mode)
                d.dbus_device = self.server.create_device(d)
                d.connect('notify::listening', self._on_listening_updated)
                self.devices[bluez_device.address] = d

        d = self.devices[bluez_device.address]

        if mode == DeviceMode.REGISTER:
            d.mode = mode
            logger.debug(f'{bluez_device.objpath}: call Register() on device')
        elif d.listening:
            d.listen()

    def _on_bluez_device_updated(self, manager, bluez_device):
        self._add_device(manager, bluez_device, True)

    def _on_listening_updated(self, tuhi_dbus_device, pspec):
        listen = self._search_stop_handler is not None
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
    if sys.version_info < (3, 6):
        sys.exit('Python 3.6 or later required')

    desc = 'Daemon to extract the pen stroke data from Wacom SmartPad devices'
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
