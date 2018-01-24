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

logger = logging.getLogger('tuhi.dbus')

INTROSPECTION_XML = """
<node>
  <interface name='org.freedesktop.tuhi1.Manager'>
    <property type='ao' name='Devices' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <property type='ao' name='Searching' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
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

    <signal name='PairableDevice'>
       <arg name='info' type='o' />
    </signal>
  </interface>

  <interface name='org.freedesktop.tuhi1.Device'>
    <property type='s' name='Name' access='read'/>
    <property type='s' name='Address' access='read'/>
    <property type='uu' name='Dimensions' access='read'/>
    <property type='b' name='Listening' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>
    <property type='u' name='DrawingsAvailable' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <method name='Pair'>
      <arg name='result' type='i' direction='out'/>
    </method>

    <method name='StartListening'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <method name='StopListening'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <method name='GetJSONData'>
      <arg name='index' type='u' direction='in'/>
      <arg name='json' type='s' direction='out'/>
    </method>

    <signal name='ButtonPressRequired' />

    <signal name='ListenComplete'>
       <arg name='status' type='i' />
    </signal>
  </interface>
</node>
"""
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
        """
        Send a PropertiesChanged signal to the given destination (if any).
        The props argument is a { name: value } dictionary of the
        property values, the values are GVariant.bool, etc.
        """
        builder = GLib.VariantBuilder(GLib.VariantType('a{sv}'))
        for name, value in props.items():
            de = GLib.Variant.new_dict_entry(GLib.Variant.new_string(name),
                                             GLib.Variant.new_variant(value))
            builder.add_value(de)
        properties = builder.end()
        inval_props = GLib.VariantBuilder(GLib.VariantType('as'))
        inval_props = inval_props.end()
        self.connection.emit_signal(dest, self.objpath,
                                    "org.freedesktop.DBus.Properties",
                                    "PropertiesChanged",
                                    GLib.Variant.new_tuple(
                                        GLib.Variant.new_string(self.interface),
                                        properties,
                                        inval_props))

    def signal(self, name, arg=None, dest=None):
        if arg is not None:
            arg = GLib.Variant.new_tuple(arg)
        self.connection.emit_signal(dest, self.objpath, self.interface, name, arg)


class TuhiDBusDevice(_TuhiDBus):
    """
    Class representing a DBus object for a Tuhi device. This class only
    handles the DBus bits, communication with the device is done elsewhere.
    """
    __gsignals__ = {
        "pair-requested":
            (GObject.SIGNAL_RUN_FIRST, None, ()),
    }

    def __init__(self, device, connection):
        objpath = device.address.replace(':', '_')
        objpath = "{}/{}".format(BASE_PATH, objpath)
        _TuhiDBus.__init__(self, connection, objpath, INTF_DEVICE)

        self.name = device.name
        self.btaddr = device.address
        self.width, self.height = 0, 0
        self.drawings = []
        self.paired = device.paired
        self._listening = False
        self._listening_client = None
        self._dbusid = self._register_object(connection)
        device.connect('notify::paired', self._on_device_paired)

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
    def paired(self):
        return self._paired

    @paired.setter
    def paired(self, paired):
        self._paired = paired

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

        if methodname == 'Pair':
            # FIXME: we should cache the method invocation here, wait for a
            # successful result from Tuhi and then return the value
            self._pair()
            result = GLib.Variant.new_int32(0)
            invocation.return_value(GLib.Variant.new_tuple(result))
        elif methodname == 'StartListening':
            self._start_listening(connection, sender)
            invocation.return_value()
        elif methodname == 'StopListening':
            self._stop_listening(connection, sender)
            invocation.return_value()
        elif methodname == 'GetJSONData':
            json = GLib.Variant.new_string(self._json_data(args))
            invocation.return_value(GLib.Variant.new_tuple(json))

    def _property_read_cb(self, connection, sender, objpath, interface, propname):
        if interface != INTF_DEVICE:
            return None

        if propname == 'Name':
            return GLib.Variant.new_string(self.name)
        elif propname == 'Address':
            return GLib.Variant.new_string(self.btaddr)
        elif propname == 'Dimensions':
            w = GLib.Variant.new_uint32(self.width)
            h = GLib.Variant.new_uint32(self.height)
            return GLib.Variant.new_tuple(w, h)
        elif propname == 'DrawingsAvailable':
            return GLib.Variant.new_uint32(len(self.drawings))
        elif propname == 'Listening':
            return GLib.Variant.new_boolean(self.listening)

        return None

    def _property_write_cb(self):
        pass

    def _pair(self):
        self.emit('pair-requested')

    def _on_device_paired(self, device, pspec):
        if self.paired == device.paired:
            return
        self.paired = device.paired

    def _start_listening(self, connection, sender):
        if self.listening:
            logger.debug("{} - already listening".format(self))

            # silently ignore it for the current client but send EAGAIN to
            # other clients
            if sender != self._listening_client[0]:
                status = GLib.Variant.new_int32(-errno.EAGAIN)
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
        logger.debug('Listening started on {} for {}'.format(self.name, sender))

        self._listening = True
        self.notify('listening')

    def _on_name_owner_changed_signal_cb(self, connection, sender, object_path,
                                         interface_name, node,
                                         out_user_data, user_data):
        name, old_owner, new_owner = out_user_data
        if name != user_data:
            return

        self._stop_listening(connection, user_data)

    def _stop_listening(self, connection, sender):
        if not self.listening or sender != self._listening_client[0]:
            return

        connection.signal_unsubscribe(self._listening_client[1])
        self._listening_client = None
        logger.debug('Listening stopped on {} for {}'.format(self.name, sender))

        self.notify('listening')

        status = GLib.Variant.new_int32(0)
        self.signal('ListeningStopped', status, dest=sender)
        self.listening = False
        self.notify('listening')

    def _json_data(self, args):
        index = args[0]
        try:
            drawing = self.drawings[index]
        except IndexError:
            return ''
        else:
            return drawing.json()

    def add_drawing(self, drawing):
        self.drawings.append(drawing)
        self.properties_changed({'DrawingsAvailable':
                                 GLib.Variant.new_uint32(len(self.drawings))})

    def notify_button_press_required(self):
        logger.debug("Sending ButtonPressRequired signal")
        self.signal('ButtonPressRequired')

    def __repr__(self):
        return "{} - {}".format(self.objpath, self.name)


class TuhiDBusServer(_TuhiDBus):
    """
    Class for the DBus server.
    """
    __gsignals__ = {
        "bus-name-acquired":
            (GObject.SIGNAL_RUN_FIRST, None, ()),

        # Signal arguments:
        #    search_stop_handler(status)
        #        to be called when the search process has terminated, with
        #        an integer status code (0 == success, negative errno)
        "search-start-requested":
            (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        "search-stop-requested":
            (GObject.SIGNAL_RUN_FIRST, None, ()),
    }

    def __init__(self):
        _TuhiDBus.__init__(self, None, BASE_PATH, INTF_MANAGER)
        self._devices = []
        self._pairable_devices = {}
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
        pass

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
            return GLib.Variant.new_objv([d.objpath for d in self._devices if d.paired])
        elif propname == 'Searching':
            return GLib.Variant.new_boolean(self.is_searching)

        return None

    def _property_write_cb(self):
        pass

    def _start_search(self, connection, sender):
        if self.is_searching:
            logger.debug("Already searching")

            # silently ignore it for the current client but send EAGAIN to
            # other clients
            if sender != self._searching_client[0]:
                status = GLib.Variant.new_int32(-errno.EAGAIN)
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

        self.emit("search-start-requested", self._on_search_stop)
        for d in self._devices:
            if not d.paired:
                self._emit_pairable_signal(d)

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
        self._searching_client = None
        self.emit("search-stop-requested")

    def _on_search_stop(self, status):
        """
        Called by whoever handles the search-start-requested signal
        """
        logger.debug("Search has stopped")
        self.is_searching = False
        status = GLib.Variant.new_int32(status)
        self.signal("SearchStopped", status, dest=self._searching_client[0])
        self._searching_client = None

        for dev in self._devices:
            if dev.paired:
                continue

            dev.remove()
        self._devices = [d for d in self._devices if d.paired]

    def cleanup(self):
        Gio.bus_unown_name(self._dbus)

    def create_device(self, device):
        dev = TuhiDBusDevice(device, self.connection)
        dev.connect('notify::paired', self._on_device_paired)
        self._devices.append(dev)
        if not device.paired:
            self._emit_pairable_signal(dev)
        return dev

    def _on_device_paired(self, device, param):
        objpaths = GLib.Variant.new_array(GLib.VariantType('o'),
                                          [GLib.Variant.new_object_path(d.objpath)
                                              for d in self._devices if d.paired])
        self.properties_changed({'Devices': objpaths})

    def _emit_pairable_signal(self, device):
        arg = GLib.Variant.new_object_path(device.objpath)
        self.signal('PairableDevice', arg, dest=self._searching_client[0])
