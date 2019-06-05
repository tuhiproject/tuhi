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

import logging
from gi.repository import GObject, Gio, GLib

logger = logging.getLogger('tuhi.ble')

ORG_BLUEZ_GATTCHARACTERISTIC1 = 'org.bluez.GattCharacteristic1'
ORG_BLUEZ_GATTSERVICE1 = 'org.bluez.GattService1'
ORG_BLUEZ_DEVICE1 = 'org.bluez.Device1'
ORG_BLUEZ_ADAPTER1 = 'org.bluez.Adapter1'


class BlueZCharacteristic(GObject.Object):
    '''
    Abstraction for a org.bluez.GattCharacteristic1 object.

    Use start_notify() to receive notifications about the characteristics.
    Hook up a property with connect_property() first.

    '''
    def __init__(self, obj):
        '''
        :param obj: the org.bluez.GattCharacteristic1 DBus proxy object
        '''
        self.obj = obj
        self.objpath = obj.get_object_path()
        self.interface = obj.get_interface(ORG_BLUEZ_GATTCHARACTERISTIC1)
        assert(self.interface is not None)

        self.uuid = self.interface.get_cached_property('UUID').unpack()
        assert(self.uuid is not None)

        self._property_callbacks = {}
        self.interface.connect('g-properties-changed',
                               self._on_properties_changed)

    def connect_property(self, propname, callback):
        '''
        Connect the property with the given name to the callback function
        provide. When the property chages, callback is invoked as:

            callback(propname, value)

        The common way is connect_property('Value', do_something) to get
        notified about Value changes on this characteristic.
        '''
        self._property_callbacks[propname] = callback

    def start_notify(self):
        self.interface.StartNotify()

    def write_value(self, data):
        return self.interface.WriteValue('(aya{sv})', data, {})

    def _on_properties_changed(self, obj, properties, invalidated_properties):
        properties = properties.unpack()
        for name, value in properties.items():
            try:
                self._property_callbacks[name](name, value)
            except KeyError:
                pass

    def __repr__(self):
        return f'Characteristic {self.uuid}:{self.objpath}'


class BlueZDevice(GObject.Object):
    '''
    Abstraction for a org.bluez.Device1 object

    The device initializes itself based on the given object manager and
    object, specifically: it resolves its services and gatt characteristics.
    The device resolves itself where possible, if one of its
    services/characteristics comes in late, call resolve().

    To connect to the real device, call connect_to_device(). The 'connected'
    and 'disconnected' signals are emitted when the connection is
    established.

    The device's characteristics are in self.characteristics[uuid]
    '''
    __gsignals__ = {
        'connected':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        'disconnected':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        'updated':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, om, obj):
        '''
        :param om: The ObjectManager for name org.bluez path /
        :param obj: The org.bluez.Device1 DBus proxy object
        '''
        GObject.Object.__init__(self)
        self.objpath = obj.get_object_path()
        self.obj = obj
        self.interface = obj.get_interface(ORG_BLUEZ_DEVICE1)
        assert(self.interface is not None)

        logger.debug(f'Device {self.objpath} - {self.address} - {self.name}')

        self.characteristics = {}
        self.resolve(om)
        self.interface.connect('g-properties-changed', self._on_properties_changed)
        if self.connected:
            self.emit('connected')

    @GObject.Property
    def name(self):
        try:
            return self.interface.get_cached_property('Name').unpack()
        except AttributeError:
            return 'UNKNOWN'

    @GObject.Property
    def address(self):
        return self.interface.get_cached_property('Address').unpack()

    @GObject.Property
    def uuids(self):
        return self.interface.get_cached_property('UUIDs').unpack()

    @GObject.Property
    def vendor_id(self):
        md = self.interface.get_cached_property('ManufacturerData')
        if md is None:
            return None

        try:
            return next(iter(dict(md)))
        except StopIteration:
            # dict is empty
            pass

        return None

    @GObject.Property
    def connected(self):
        return (self.interface.get_cached_property('Connected').unpack() and
                self.interface.get_cached_property('ServicesResolved').unpack())

    @GObject.Property
    def manufacturer_data(self):
        md = self.interface.get_cached_property('ManufacturerData')
        if md is None:
            return None

        try:
            return next(iter(dict(md).values()))
        except StopIteration:
            # dict is empty
            pass

        return None

    def resolve(self, om):
        '''
        Resolve the GattServices and GattCharacteristics. This function does
        not need to be called for existing objects but if a device comes in
        at runtime not all services may have been resolved by the time the
        org.bluez.Device1 shows up.
        '''
        objects = om.get_objects()
        self._resolve_gatt_services(objects)

    def _resolve_gatt_services(self, objects):
        self.gatt_services = []
        for obj in objects:
            i = obj.get_interface(ORG_BLUEZ_GATTSERVICE1)
            if i is None:
                continue

            device = i.get_cached_property('Device').get_string()
            if device != self.objpath:
                continue

            logger.debug(f'GattService1: {obj.get_object_path()} for device {device}')
            self.gatt_services.append(obj)
            self._resolve_gatt_characteristics(obj, objects)

    def _resolve_gatt_characteristics(self, service_obj, objects):
        for obj in objects:
            i = obj.get_interface(ORG_BLUEZ_GATTCHARACTERISTIC1)
            if i is None:
                continue

            service = i.get_cached_property('Service').get_string()
            if service != service_obj.get_object_path():
                continue

            chrc = BlueZCharacteristic(obj)
            if chrc.uuid in self.characteristics:
                continue

            logger.debug(f'GattCharacteristic: {chrc.uuid} for service {service}')

            self.characteristics[chrc.uuid] = chrc

    def connect_device(self):
        '''
        Connect to the bluetooth device via bluez. This function is
        asynchronous and returns immediately.
        '''
        i = self.obj.get_interface(ORG_BLUEZ_DEVICE1)
        if self.connected:
            logger.info(f'{self.address}: Device is already connected')
            self.emit('connected')
            return

        logger.info(f'{self.address}: Connecting')
        i.Connect(result_handler=self._on_connect_result)

    def _on_connect_result(self, obj, result, user_data):
        if (isinstance(result, GLib.Error) and
                result.domain == 'g-io-error-quark' and
                result.code == Gio.IOErrorEnum.DBUS_ERROR and
                Gio.dbus_error_get_remote_error(result) == 'org.bluez.Error.Failed' and
                'Operation already in progress' in result.message):
            logger.debug(f'{self.address}: Already connecting')
        elif isinstance(result, Exception):
            logger.error(f'Connection failed: {result}')

    def disconnect_device(self):
        '''
        Disconnect the bluetooth device via bluez. This function is
        asynchronous and returns immediately.
        '''
        i = self.obj.get_interface(ORG_BLUEZ_DEVICE1)
        if not i.get_cached_property('Connected').get_boolean():
            logger.info(f'{self.address}: Device is already disconnected')
            self.emit('disconnected')
            return

        logger.info(f'{self.address}: Disconnecting')
        i.Disconnect(result_handler=self._on_disconnect_result)

    def _on_disconnect_result(self, obj, result, user_data):
        if isinstance(result, Exception):
            logger.error(f'Disconnection failed: {result}')

    def _on_properties_changed(self, obj, properties, invalidated_properties):
        properties = properties.unpack()

        if 'Connected' in properties:
            if properties['Connected']:
                logger.info('Connection established')
            else:
                logger.info('Disconnected')
                self.emit('disconnected')
        if 'ServicesResolved' in properties:
            if properties['ServicesResolved']:
                self.emit('connected')
        if 'RSSI' in properties:
            self.emit('updated')
        if 'ManufacturerData' in properties:
            self.notify('manufacturer-data')

    def connect_gatt_value(self, uuid, callback):
        '''
        Connects Value property changes of the given GATT Characteristics
        UUID to the callback.
        '''
        try:
            chrc = self.characteristics[uuid]
            chrc.connect_property('Value', callback)
            chrc.start_notify()
        except KeyError:
            pass

    def __repr__(self):
        return f'Device {self.name}:{self.objpath}'


class BlueZDeviceManager(GObject.Object):
    '''
    Manager object that connects to org.bluez's root object and handles the
    devices.
    '''
    __gsignals__ = {
        'device-added':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        'device-updated':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        'discovery-started':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        'discovery-stopped':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs):
        GObject.Object.__init__(self, **kwargs)
        self.devices = []
        self._discovery = False

    def connect_to_bluez(self):
        '''
        Connect to bluez's DBus interface. Once called, devices will be
        resolved as they come in. The device-added signal is emitted for
        each device.
        '''
        self._om = Gio.DBusObjectManagerClient.new_for_bus_sync(
            Gio.BusType.SYSTEM,
            Gio.DBusObjectManagerClientFlags.NONE,
            'org.bluez',
            '/',
            None,
            None,
            None)
        self._om.connect('object-added', self._on_om_object_added)
        self._om.connect('object-removed', self._on_om_object_removed)

        # We rely on nested object paths, so let's sort the objects by
        # object path length and process them in order, this way we're
        # guaranteed that the objects we need already exist.
        for obj in self._om.get_objects():
            self._process_object(obj)

    def _discovery_timeout_expired(self):
        self.stop_discovery()
        return False

    def start_discovery(self, timeout=0):
        '''
        Start discovery mode, terminating after the specified timeout (in
        seconds). If timeout is 0, no timeout is imposed and the discovery
        mode stays on.

        This emits the discovery-started signal
        '''
        self.emit('discovery-started')
        if self._discovery:
            return

        self._discovery = True

        for obj in self._om.get_objects():
            i = obj.get_interface(ORG_BLUEZ_ADAPTER1)
            if i is None:
                continue

            # remove the duplicate data filter so we get notifications as they come in
            i.SetDiscoveryFilter('(a{sv})', {'DuplicateData': GLib.Variant.new_boolean(False)})

            objpath = obj.get_object_path()
            try:
                i.StartDiscovery()
                logger.debug(f'{objpath}: Discovery started (timeout {timeout})')
            except GLib.Error as e:
                if (e.domain == 'g-io-error-quark' and
                        e.code == Gio.IOErrorEnum.DBUS_ERROR and
                        Gio.dbus_error_get_remote_error(e) == 'org.bluez.Error.InProgress'):
                    logger.debug(f'{objpath}: Already listening')

        if timeout > 0:
            GObject.timeout_add_seconds(timeout, self._discovery_timeout_expired)

        # FIXME: Any errors up to here should trigger discovery-stopped
        # signal with the status code

    def stop_discovery(self):
        '''
        Stop an ongoing discovery mode. Any errors are logged but ignored.

        This emits the discovery-stopped signal
        '''
        if not self._discovery:
            return

        self._discovery = False

        for obj in self._om.get_objects():
            i = obj.get_interface(ORG_BLUEZ_ADAPTER1)
            if i is None:
                continue

            objpath = obj.get_object_path()
            try:
                i.StopDiscovery()
                logger.debug(f'{objpath}: Discovery stopped')
            except GLib.Error as e:
                logger.debug(f'{objpath}: Failed to stop discovery ({e})')

            # reset the discovery filters
            i.SetDiscoveryFilter('(a{sv})', {})

        self.emit('discovery-stopped')

    def _on_device_updated(self, device):
        '''Callback for Device's properties-changed'''
        # logger.debug(f'Object updated: {device.name}')

        self.emit('device-updated', device)

    def _on_om_object_added(self, om, obj):
        '''Callback for ObjectManager's object-added'''
        objpath = obj.get_object_path()
        logger.debug(f'Object added: {objpath}')
        needs_resolve = self._process_object(obj, event=True)

        # we had at least one characteristic added, need to resolve the
        # devices.
        # FIXME: this isn't the most efficient way...
        if needs_resolve:
            for d in self.devices:
                d.resolve(om)

    def _on_om_object_removed(self, om, obj):
        '''Callback for ObjectManager's object-removed'''
        objpath = obj.get_object_path()
        logger.debug(f'Object removed: {objpath}')

    def _process_object(self, obj, event=True):
        '''Process a single DBusProxyObject'''

        if obj.get_interface(ORG_BLUEZ_ADAPTER1) is not None:
            self._process_adapter(obj)
        elif obj.get_interface(ORG_BLUEZ_DEVICE1) is not None:
            self._process_device(obj)
        elif obj.get_interface(ORG_BLUEZ_GATTCHARACTERISTIC1) is not None:
            return True

        return False

    def _process_adapter(self, obj):
        objpath = obj.get_object_path()
        logger.debug(f'Adapter: {objpath}')

    def _process_device(self, obj):
        dev = BlueZDevice(self._om, obj)
        self.devices.append(dev)
        dev.connect('updated', self._on_device_updated)
        self.emit('device-added', dev)

    def _process_characteristic(self, obj):
        objpath = obj.get_object_path()
        logger.debug(f'Characteristic {objpath}')
