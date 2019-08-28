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

from gi.repository import GObject, Gio, GLib
import argparse
import errno
import os
import logging
import re

logger = logging.getLogger('tuhi.dbusclient')

TUHI_DBUS_NAME = 'org.freedesktop.tuhi1'
ORG_FREEDESKTOP_TUHI1_MANAGER = 'org.freedesktop.tuhi1.Manager'
ORG_FREEDESKTOP_TUHI1_DEVICE = 'org.freedesktop.tuhi1.Device'
ROOT_PATH = '/org/freedesktop/tuhi1'

ORG_BLUEZ_DEVICE1 = 'org.bluez.Device1'


class DBusError(Exception):
    def __init__(self, message):
        self.message = message


class _DBusObject(GObject.Object):
    _connection = None

    def __init__(self, name, interface, objpath):
        super().__init__()

        # this is not handled asynchronously because if we fail to
        # get the session bus, we have other issues
        if _DBusObject._connection is None:
            self._connect_to_session()

        self.interface = interface
        self.objpath = objpath
        self._online = False
        self._name = name
        try:
            self._connect()
        except DBusError:
            self._reconnect_timer = GObject.timeout_add_seconds(2, self._on_reconnect_timer)

    def _connect(self):
        try:
            self.proxy = Gio.DBusProxy.new_sync(self._connection,
                                                Gio.DBusProxyFlags.NONE, None,
                                                self._name, self.objpath,
                                                self.interface, None)
            if self.proxy.get_name_owner() is None:
                raise DBusError(f'No-one is handling {self._name}, is the daemon running?')

            self._online = True
            self.notify('online')
        except GLib.Error as e:
            if (e.domain == 'g-io-error-quark' and
                    e.code == Gio.IOErrorEnum.DBUS_ERROR):
                raise DBusError(e.message)
            else:
                raise e

        self.proxy.connect('g-properties-changed', self._on_properties_changed)
        self.proxy.connect('g-signal', self._on_signal_received)

    def _on_reconnect_timer(self):
        try:
            logger.debug('reconnecting')
            self._connect()
            return False
        except DBusError:
            return True

    @GObject.Property
    def online(self):
        return self._online

    def _connect_to_session(self):
        try:
            _DBusObject._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            if (e.domain == 'g-io-error-quark' and
                    e.code == Gio.IOErrorEnum.DBUS_ERROR):
                raise DBusError(e.message)
            else:
                raise e

    def _on_properties_changed(self, proxy, changed_props, invalidated_props):
        # Implement this in derived classes to respond to property changes
        pass

    def _on_signal_received(self, proxy, sender, signal, parameters):
        # Implement this in derived classes to respond to signals
        pass

    def property(self, name):
        p = self.proxy.get_cached_property(name)
        if p is not None:
            return p.unpack()
        return p

    def terminate(self):
        del(self.proxy)


class _DBusSystemObject(_DBusObject):
    '''
    Same as the _DBusObject, but connects to the system bus instead
    '''
    def __init__(self, name, interface, objpath):
        self._connect_to_system()
        super().__init__(name, interface, objpath)

    def _connect_to_system(self):
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error as e:
            if (e.domain == 'g-io-error-quark' and
                    e.code == Gio.IOErrorEnum.DBUS_ERROR):
                raise DBusError(e.message)
            else:
                raise e


class BlueZDevice(_DBusSystemObject):
    def __init__(self, objpath):
        super().__init__('org.bluez', ORG_BLUEZ_DEVICE1, objpath)
        self.proxy.connect('g-properties-changed', self._on_properties_changed)

    @GObject.Property
    def connected(self):
        return self.proxy.get_cached_property('Connected').unpack()

    def _on_properties_changed(self, obj, properties, invalidated_properties):
        properties = properties.unpack()

        if 'Connected' in properties:
            self.notify('connected')


class TuhiDBusClientDevice(_DBusObject):
    __gsignals__ = {
        'button-press-required':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        'registered':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        'device-error':
            (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, manager, objpath):
        super().__init__(TUHI_DBUS_NAME, ORG_FREEDESKTOP_TUHI1_DEVICE, objpath)
        self.manager = manager
        self.is_registering = False
        self._bluez_device = BlueZDevice(self.property('BlueZDevice'))
        self._bluez_device.connect('notify::connected', self._on_connected)
        self._sync_state = 0

    @classmethod
    def is_device_address(cls, string):
        if re.match(r'[0-9a-f]{2}(:[0-9a-f]{2}){5}$', string.lower()):
            return string
        raise argparse.ArgumentTypeError(f'"{string}" is not a valid device address')

    @GObject.Property
    def address(self):
        return self._bluez_device.property('Address')

    @GObject.Property
    def name(self):
        return self._bluez_device.property('Name')

    @GObject.Property
    def dimensions(self):
        return self.property('Dimensions')

    @GObject.Property
    def listening(self):
        return self.property('Listening')

    @GObject.Property
    def drawings_available(self):
        return self.property('DrawingsAvailable')

    @GObject.Property
    def battery_percent(self):
        return self.property('BatteryPercent')

    @GObject.Property
    def battery_state(self):
        return self.property('BatteryState')

    @GObject.Property
    def connected(self):
        return self._bluez_device.connected

    @GObject.Property
    def sync_state(self):
        return self._sync_state

    def _on_connected(self, bluez_device, pspec):
        self.notify('connected')

    def register(self):
        logger.debug(f'{self}: Register')
        # FIXME: Register() doesn't return anything useful yet, so we wait until
        # the device is in the Manager's Devices property
        self.s1 = self.manager.connect('notify::devices', self._on_mgr_devices_updated)
        self.is_registering = True
        self.proxy.Register()

    def start_listening(self):
        self.proxy.StartListening()

    def stop_listening(self):
        try:
            self.proxy.StopListening()
        except GLib.Error as e:
            if (e.domain != 'g-dbus-error-quark' or
                    e.code != Gio.IOErrorEnum.EXISTS or
                    Gio.dbus_error_get_remote_error(e) != 'org.freedesktop.DBus.Error.ServiceUnknown'):
                raise e

    def json(self, timestamp):
        SUPPORTED_FILE_FORMAT = 1
        return self.proxy.GetJSONData('(ut)', SUPPORTED_FILE_FORMAT, timestamp)

    def _on_signal_received(self, proxy, sender, signal, parameters):
        if signal == 'ButtonPressRequired':
            logger.info(f'{self}: Press button on device now')
            self.emit('button-press-required')
        elif signal == 'ListeningStopped':
            err = parameters[0]
            if err == -errno.EACCES:
                logger.error(f'{self}: wrong device, please re-register.')
            elif err < 0:
                logger.error(f'{self}: an error occured: {os.strerror(-err)}')
            self.emit('device-error', err)
            self.notify('listening')
        elif signal == 'SyncState':
            self._sync_state = parameters[0]
            self.notify('sync-state')

    def _on_properties_changed(self, proxy, changed_props, invalidated_props):
        if changed_props is None:
            return

        changed_props = changed_props.unpack()

        if 'DrawingsAvailable' in changed_props:
            self.notify('drawings-available')
        elif 'Listening' in changed_props:
            self.notify('listening')
        elif 'BatteryPercent' in changed_props:
            self.notify('battery-percent')
        elif 'BatteryState' in changed_props:
            self.notify('battery-state')

    def __repr__(self):
        return f'{self.address} - {self.name}'

    def _on_mgr_devices_updated(self, manager, pspec):
        if not self.is_registering:
            return

        for d in manager.devices:
            if d.address == self.address:
                self.is_registering = False
                self.manager.disconnect(self.s1)
                del(self.s1)
                logger.info(f'{self}: Registration successful')
                self.emit('registered')

    def terminate(self):
        try:
            self.manager.disconnect(self.s1)
        except AttributeError:
            pass
        self._bluez_device.terminate()
        super().terminate()


class TuhiDBusClientManager(_DBusObject):
    __gsignals__ = {
        'unregistered-device':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self):
        super().__init__(TUHI_DBUS_NAME, ORG_FREEDESKTOP_TUHI1_MANAGER, ROOT_PATH)

        self._devices = {}
        self._unregistered_devices = {}
        logger.info('starting up')

        if not self.online:
            self.connect('notify::online', self._init)
        else:
            self._init()

    def _init(self, *args, **kwargs):
        logger.info('manager is online')
        for objpath in self.property('Devices'):
            device = TuhiDBusClientDevice(self, objpath)
            self._devices[device.address] = device

    @GObject.Property
    def devices(self):
        return [v for k, v in self._devices.items()]

    @GObject.Property
    def unregistered_devices(self):
        return [v for k, v in self._unregistered_devices.items()]

    @GObject.Property
    def searching(self):
        return self.proxy.get_cached_property('Searching')

    def start_search(self):
        self._unregistered_devices = {}
        self.proxy.StartSearch()

    def stop_search(self):
        try:
            self.proxy.StopSearch()
        except GLib.Error as e:
            if (e.domain != 'g-dbus-error-quark' or
                    e.code != Gio.IOErrorEnum.EXISTS or
                    Gio.dbus_error_get_remote_error(e) != 'org.freedesktop.DBus.Error.ServiceUnknown'):
                raise e
        self._unregistered_devices = {}

    def terminate(self):
        for dev in self._devices.values():
            dev.terminate()
        self._devices = {}
        self._unregistered_devices = {}
        super().terminate()

    def _on_properties_changed(self, proxy, changed_props, invalidated_props):
        if changed_props is None:
            return

        changed_props = changed_props.unpack()

        if 'Devices' in changed_props:
            objpaths = changed_props['Devices']
            for objpath in objpaths:
                try:
                    d = self._unregistered_devices[objpath]
                    self._devices[d.address] = d
                    del self._unregistered_devices[objpath]
                except KeyError:
                    # if we called Register() on an existing device it's not
                    # in unregistered devices
                    pass
            self.notify('devices')
        if 'Searching' in changed_props:
            self.notify('searching')

    def _handle_unregistered_device(self, objpath):
        for addr, dev in self._devices.items():
            if dev.objpath == objpath:
                self.emit('unregistered-device', dev)
                return

        device = TuhiDBusClientDevice(self, objpath)
        self._unregistered_devices[objpath] = device

        logger.debug(f'New unregistered device: {device}')
        self.emit('unregistered-device', device)

    def _on_signal_received(self, proxy, sender, signal, parameters):
        if signal == 'SearchStopped':
            self.notify('searching')
        elif signal == 'UnregisteredDevice':
            objpath = parameters[0]
            self._handle_unregistered_device(objpath)

    def __getitem__(self, btaddr):
        return self._devices[btaddr]
