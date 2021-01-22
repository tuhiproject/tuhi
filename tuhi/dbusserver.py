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
import errno

from gi.repository import GObject, Gio, GLib
from .drawing import Drawing

logger = logging.getLogger('tuhi.dbus')

INTROSPECTION_XML = '''
<node>
  <interface name='org.freedesktop.tuhi1.Manager'>
    <property type='ao' name='Devices' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <property type='ao' name='Searching' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <property type='au' name='JSONDataVersions' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='const'/>
    </property>

    <method name='StartSearch'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <method name='StopSearch'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <signal name='SearchStopped'>
       <arg name='status' type='i' />
    </signal>

    <signal name='UnregisteredDevice'>
       <arg name='info' type='o' />
    </signal>
  </interface>

  <interface name='org.freedesktop.tuhi1.Device'>
    <property type='o' name='BlueZDevice' access='read'/>
    <property type='uu' name='Dimensions' access='read'/>
    <property type='b' name='Listening' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>
    <property type='b' name='Live' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>
    <property type='u' name='BatteryPercent' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>
    <property type='b' name='BatteryState' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>
    <property type='at' name='DrawingsAvailable' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <method name='Register'>
      <arg name='result' type='i' direction='out'/>
    </method>

    <method name='StartListening'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <method name='StopListening'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <method name='StartLive'>
      <arg name='uhid_fd' type='h' />
      <arg name='result' type='i' direction='out'/>
    </method>

    <method name='StopLive'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <method name='GetJSONData'>
      <arg name='file_version' type='u' direction='in'/>
      <arg name='timestamp' type='t' direction='in'/>
      <arg name='json' type='s' direction='out'/>
    </method>

    <signal name='ButtonPressRequired' />

    <signal name='ListeningStopped'>
       <arg name='status' type='i' />
    </signal>

    <signal name='LiveStopped'>
       <arg name='status' type='i' />
    </signal>

    <signal name='SyncState'>
       <arg name='status' type='i' />
    </signal>
  </interface>
</node>
'''
BASE_PATH = '/org/freedesktop/tuhi1'
BUS_NAME = 'org.freedesktop.tuhi1'
INTF_MANAGER = 'org.freedesktop.tuhi1.Manager'
INTF_DEVICE = 'org.freedesktop.tuhi1.Device'


class _TuhiDBus(GObject.Object):
    def __init__(self, connection, objpath, interface):
        GObject.Object.__init__(self)
        self.connection = connection
        self.objpath = objpath
        self.interface = interface

    def properties_changed(self, props, dest=None):
        '''
        Send a PropertiesChanged signal to the given destination (if any).
        The props argument is a { name: value } dictionary of the
        property values, the values are GVariant.bool, etc.
        '''
        builder = GLib.VariantBuilder(GLib.VariantType('a{sv}'))
        for name, value in props.items():
            de = GLib.Variant.new_dict_entry(GLib.Variant.new_string(name),
                                             GLib.Variant.new_variant(value))
            builder.add_value(de)
        properties = builder.end()
        inval_props = GLib.VariantBuilder(GLib.VariantType('as'))
        inval_props = inval_props.end()
        self.connection.emit_signal(dest, self.objpath,
                                    'org.freedesktop.DBus.Properties',
                                    'PropertiesChanged',
                                    GLib.Variant.new_tuple(
                                        GLib.Variant.new_string(self.interface),
                                        properties,
                                        inval_props))

    def signal(self, name, arg=None, dest=None):
        if arg is not None:
            arg = GLib.Variant.new_tuple(arg)
        self.connection.emit_signal(dest, self.objpath, self.interface, name, arg)


class TuhiDBusDevice(_TuhiDBus):
    '''
    Class representing a DBus object for a Tuhi device. This class only
    handles the DBus bits, communication with the device is done elsewhere.
    '''
    __gsignals__ = {
        'register-requested':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, device, connection):
        objpath = device.address.replace(':', '_')
        objpath = f'{BASE_PATH}/{objpath}'
        _TuhiDBus.__init__(self, connection, objpath, INTF_DEVICE)

        self.bluez_device_objpath = device.bluez_device.objpath
        self.name = device.name
        self.width, self.height = device.dimensions
        self.drawings = {}
        self.registered = device.registered
        self._listening = False
        self._listening_client = None
        self._live = False
        self._uhid_fd = None
        self._live_client = None
        self._dbusid = self._register_object(connection)
        self._battery_percent = 0
        self._battery_state = device.battery_state
        device.connect('notify::registered', self._on_device_registered)
        device.connect('notify::battery-percent', self._on_battery_percent)
        device.connect('notify::battery-state', self._on_battery_state)
        device.connect('device-error', self._on_device_error)
        device.connect('notify::sync-state', self._on_sync_state)
        device.connect('notify::dimensions', self._on_dimensions)

    @GObject.Property
    def listening(self):
        return self._listening

    @listening.setter
    def listening(self, value):
        if self._listening == value:
            return

        self._listening = value
        self.properties_changed({'Listening': GLib.Variant.new_boolean(value)})

    @GObject.Property
    def live(self):
        return self._live

    @live.setter
    def live(self, value):
        if self._live == value:
            return

        self._live = value
        self.properties_changed({'Live': GLib.Variant.new_boolean(value)})

    @GObject.Property
    def uhid_fd(self):
        return self._uhid_fd

    @GObject.Property
    def registered(self):
        return self._registered

    @registered.setter
    def registered(self, registered):
        self._registered = registered

    @GObject.Property
    def battery_percent(self):
        return self._battery_percent

    @battery_percent.setter
    def battery_percent(self, value):
        if self._battery_percent == value:
            return

        self._battery_percent = value
        self.properties_changed({'BatteryPercent': GLib.Variant.new_uint32(value)})

    @GObject.Property
    def battery_state(self):
        return self._battery_state

    @battery_state.setter
    def battery_state(self, value):
        if self._battery_state == value:
            return

        self._battery_state = value
        self.properties_changed({'BatteryState': GLib.Variant.new_uint32(value.value)})

    def remove(self):
        self.connection.unregister_object(self._dbusid)
        self._dbusid = None

    def _register_object(self, connection):
        introspection = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        intf = introspection.lookup_interface(self.interface)
        return connection.register_object(self.objpath,
                                          intf,
                                          self._method_cb,
                                          self._property_read_cb,
                                          self._property_write_cb)

    def _method_cb(self, connection, sender, objpath, interface, methodname, args, invocation):
        if interface != self.interface:
            return None

        if methodname == 'Register':
            # FIXME: we should cache the method invocation here, wait for a
            # successful result from Tuhi and then return the value
            self._register()
            result = GLib.Variant.new_int32(0)
            invocation.return_value(GLib.Variant.new_tuple(result))
        elif methodname == 'StartListening':
            self._start_listening(connection, sender)
            invocation.return_value()
        elif methodname == 'StopListening':
            self._stop_listening(connection, sender)
            invocation.return_value()
        elif methodname == 'StartLive':
            self._start_live(connection, sender, args, invocation)
        elif methodname == 'StopLive':
            self._stop_live(connection, sender)
            invocation.return_value()
        elif methodname == 'GetJSONData':
            json = GLib.Variant.new_string(self._json_data(args))
            invocation.return_value(GLib.Variant.new_tuple(json))

    def _property_read_cb(self, connection, sender, objpath, interface, propname):
        if interface != INTF_DEVICE:
            return None

        if propname == 'BlueZDevice':
            return GLib.Variant.new_object_path(self.bluez_device_objpath)
        elif propname == 'Dimensions':
            w = GLib.Variant.new_uint32(self.width)
            h = GLib.Variant.new_uint32(self.height)
            return GLib.Variant.new_tuple(w, h)
        elif propname == 'DrawingsAvailable':
            ts = GLib.Variant.new_array(GLib.VariantType('t'),
                                        [GLib.Variant.new_uint64(t)
                                            for t in self.drawings.keys()])
            return ts
        elif propname == 'Listening':
            return GLib.Variant.new_boolean(self.listening)
        elif propname == 'Live':
            return GLib.Variant.new_boolean(self.live)
        elif propname == 'BatteryPercent':
            return GLib.Variant.new_uint32(self.battery_percent)
        elif propname == 'BatteryState':
            return GLib.Variant.new_uint32(self.battery_state.value)

        return None

    def _property_write_cb(self):
        pass

    def _register(self):
        self.emit('register-requested')

    def _on_device_registered(self, device, pspec):
        if self.registered == device.registered:
            return
        self.registered = device.registered

    def _on_battery_percent(self, device, pspec):
        self.battery_percent = device.battery_percent

    def _on_battery_state(self, device, pspec):
        self.battery_state = device.battery_state

    def _on_device_error(self, device, exception):
        logger.info('An error occured while synching the device')
        if self.listening:
            self._stop_listening(self.connection, self._listening_client[0],
                                 -exception.errno)

    def _on_dimensions(self, device, pspec):
        self.width, self.height = device.dimensions
        w = GLib.Variant.new_uint32(self.width)
        h = GLib.Variant.new_uint32(self.height)
        self.properties_changed({'Dimensions': GLib.Variant.new_tuple(w, h)})

    def _on_sync_state(self, device, pspec):
        if self._listening_client is None:
            return

        dest = self._listening_client[0]
        status = GLib.Variant.new_int32(device.sync_state)
        self.signal('SyncState', status, dest=dest)

    def _start_listening(self, connection, sender):
        if self.listening:
            logger.debug(f'{self} - already listening')

            # silently ignore it for the current client but send EBUSY to
            # other clients
            if sender != self._listening_client[0]:
                status = GLib.Variant.new_int32(-errno.EBUSY)
                self.signal('ListeningStopped', status, dest=sender)
            return

        s = connection.signal_subscribe(sender='org.freedesktop.DBus',
                                        interface_name='org.freedesktop.DBus',
                                        member='NameOwnerChanged',
                                        object_path='/org/freedesktop/DBus',
                                        arg0=None,
                                        flags=Gio.DBusSignalFlags.NONE,
                                        callback=self._on_name_owner_changed_signal_cb,
                                        user_data=sender)
        self._listening_client = (sender, s)
        logger.debug(f'Listening started on {self.name} for {sender}')

        self.listening = True
        self.notify('listening')

    def _on_name_owner_changed_signal_cb(self, connection, sender, object_path,
                                         interface_name, node,
                                         out_user_data, user_data):
        name, old_owner, new_owner = out_user_data
        if name != user_data:
            return

        self._stop_listening(connection, user_data)
        self._stop_live(connection, user_data)

    def _stop_listening(self, connection, sender, errno=0):
        if not self.listening or sender != self._listening_client[0]:
            return

        connection.signal_unsubscribe(self._listening_client[1])
        self._listening_client = None
        logger.debug(f'Listening stopped on {self.name} for {sender}')

        self.notify('listening')

        status = GLib.Variant.new_int32(errno)
        self.signal('ListeningStopped', status, dest=sender)
        self.listening = False
        self.notify('listening')

    def _start_live(self, connection, sender, args, invocation):
        if self.live:
            logger.debug(f'{self} - already in live mode')

            # silently ignore it for the current client but send EBUSY to
            # other clients
            if sender != self._listening_client[0]:
                status = GLib.Variant.new_int32(-errno.EBUSY)
                self.signal('LiveStopped', status, dest=sender)
            return

        s = connection.signal_subscribe(sender='org.freedesktop.DBus',
                                        interface_name='org.freedesktop.DBus',
                                        member='NameOwnerChanged',
                                        object_path='/org/freedesktop/DBus',
                                        arg0=None,
                                        flags=Gio.DBusSignalFlags.NONE,
                                        callback=self._on_name_owner_changed_signal_cb,
                                        user_data=sender)
        self._live_client = (sender, s)
        logger.debug(f'Live mode started on {self.name} for {sender}')

        message = invocation.get_message()
        fds_list = message.get_unix_fd_list()

        if fds_list is None or fds_list.get_length() != 1:
            logger.error('uhid fds not provided')
            result = GLib.Variant.new_int32(-errno.EINVAL)
            invocation.return_value(GLib.Variant.new_tuple(result))
            return

        fds_list = fds_list.steal_fds()

        self._uhid_fd = fds_list[0]

        self.live = True

        result = GLib.Variant.new_int32(0)
        invocation.return_value(GLib.Variant.new_tuple(result))

    def _stop_live(self, connection, sender, errno=0):
        if not self.live or sender != self._live_client[0]:
            return

        connection.signal_unsubscribe(self._live_client[1])
        self._live_client = None
        logger.debug(f'Live mode stopped on {self.name} for {sender}')

        status = GLib.Variant.new_int32(errno)
        self.signal('LiveStopped', status, dest=sender)
        self.live = False

    def _json_data(self, args):
        file_format = args[0]
        if file_format != Drawing.JSON_FILE_FORMAT_VERSION:
            logger.info(f'Unsupported file format requested: {file_format}')
            return ''

        index = args[1]
        try:
            drawing = self.drawings[index]
        except KeyError:
            return ''
        else:
            return drawing.to_json()

    def add_drawing(self, drawing):
        self.drawings[drawing.timestamp] = drawing
        ts = GLib.Variant.new_array(GLib.VariantType('t'),
                                    [GLib.Variant.new_uint64(t)
                                        for t in self.drawings.keys()])
        self.properties_changed({'DrawingsAvailable': ts})

    def notify_button_press_required(self):
        logger.debug('Sending ButtonPressRequired signal')
        self.signal('ButtonPressRequired')

    def __repr__(self):
        return f'{self.objpath} - {self.name}'


class TuhiDBusServer(_TuhiDBus):
    '''
    Class for the DBus server.
    '''
    __gsignals__ = {
        'bus-name-acquired':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        'bus-name-lost':
            (GObject.SignalFlags.RUN_FIRST, None, ()),

        # Signal arguments:
        #    search_stop_handler(status)
        #        to be called when the search process has terminated, with
        #        an integer status code (0 == success, negative errno)
        'search-start-requested':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        'search-stop-requested':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        _TuhiDBus.__init__(self, None, BASE_PATH, INTF_MANAGER)
        self._devices = []
        self._unregistered_devices = {}
        self._dbus = Gio.bus_own_name(Gio.BusType.SESSION,
                                      BUS_NAME,
                                      Gio.BusNameOwnerFlags.NONE,
                                      self._bus_aquired,
                                      self._bus_name_aquired,
                                      self._bus_name_lost)
        self._is_searching = False
        self._searching_client = None

    @GObject.Property
    def is_searching(self):
        return self._is_searching

    @is_searching.setter
    def is_searching(self, value):
        if self._is_searching == value:
            return

        self._is_searching = value
        self.properties_changed({'Searching': GLib.Variant.new_boolean(value)})

    def _bus_aquired(self, connection, name):
        introspection = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        intf = introspection.lookup_interface(self.interface)
        self.connection = connection
        Gio.DBusConnection.register_object(connection,
                                           self.objpath,
                                           intf,
                                           self._method_cb,
                                           self._property_read_cb,
                                           self._property_write_cb)

    def _bus_name_aquired(self, connection, name):
        logger.debug('Bus name aquired')
        self.emit('bus-name-acquired')

    def _bus_name_lost(self, connection, name):
        logger.error('Bus not available, is there another Tuhi process running?')
        self.emit('bus-name-lost')

    def _method_cb(self, connection, sender, objpath, interface, methodname, args, invocation):
        if interface != self.interface:
            return None

        if methodname == 'StartSearch':
            self._start_search(connection, sender)
            invocation.return_value()
        elif methodname == 'StopSearch':
            self._stop_search(connection, sender)
            invocation.return_value()

    def _property_read_cb(self, connection, sender, objpath, interface, propname):
        if interface != self.interface:
            return None

        if propname == 'Devices':
            return GLib.Variant.new_objv([d.objpath for d in self._devices if d.registered])
        elif propname == 'Searching':
            return GLib.Variant.new_boolean(self.is_searching)
        elif propname == 'JSONDataVersions':
            return GLib.Variant.new_array(GLib.VariantType('u'),
                                          [GLib.Variant.new_uint32(Drawing.JSON_FILE_FORMAT_VERSION)])

        return None

    def _property_write_cb(self):
        pass

    def _start_search(self, connection, sender):
        if self.is_searching:
            logger.debug('Already searching')

            # silently ignore it for the current client but send EBUSY to
            # other clients
            if sender != self._searching_client[0]:
                status = GLib.Variant.new_int32(-errno.EBUSY)
                self.signal('SearchStopped', status)
            return

        self.is_searching = True

        s = connection.signal_subscribe(sender='org.freedesktop.DBus',
                                        interface_name='org.freedesktop.DBus',
                                        member='NameOwnerChanged',
                                        object_path='/org/freedesktop/DBus',
                                        arg0=None,
                                        flags=Gio.DBusSignalFlags.NONE,
                                        callback=self._on_name_owner_changed_signal_cb,
                                        user_data=sender)
        self._searching_client = (sender, s)

        self.emit('search-start-requested', self._on_search_stop)
        for d in self._devices:
            if not d.registered:
                self._emit_unregistered_signal(d)

    def _on_name_owner_changed_signal_cb(self, connection, sender, object_path,
                                         interface_name, node,
                                         out_user_data, user_data):
        name, old_owner, new_owner = out_user_data
        if name != user_data:
            return

        self._stop_search(connection, user_data)

    def _stop_search(self, connection, sender):
        if not self.is_searching or sender != self._searching_client[0]:
            return

        connection.signal_unsubscribe(self._searching_client[1])
        self.is_searching = False
        self.emit('search-stop-requested')

    def _on_search_stop(self, status):
        '''
        Called by whoever handles the search-start-requested signal
        '''
        logger.debug('Search has stopped')
        self.is_searching = False
        status = GLib.Variant.new_int32(status)
        self.signal('SearchStopped', status, dest=self._searching_client[0])
        self._searching_client = None

        for dev in self._devices:
            if dev.registered:
                continue

            dev.remove()
        self._devices = [d for d in self._devices if d.registered]

    def cleanup(self):
        Gio.bus_unown_name(self._dbus)

    def create_device(self, device):
        dev = TuhiDBusDevice(device, self.connection)
        dev.connect('notify::registered', self._on_device_registered)
        self._devices.append(dev)
        if not device.registered:
            self._emit_unregistered_signal(dev)
        return dev

    def _on_device_registered(self, device, param):
        objpaths = GLib.Variant.new_array(GLib.VariantType('o'),
                                          [GLib.Variant.new_object_path(d.objpath)
                                              for d in self._devices if d.registered])
        self.properties_changed({'Devices': objpaths})

        if not device.registered and self._is_searching:
            self._emit_unregistered_signal(device)

    def _emit_unregistered_signal(self, device):
        arg = GLib.Variant.new_object_path(device.objpath)
        self.signal('UnregisteredDevice', arg, dest=self._searching_client[0])
