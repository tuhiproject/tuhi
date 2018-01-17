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

from gi.repository import GObject, Gio, GLib

logger = logging.getLogger('tuhi.dbus')

INTROSPECTION_XML = """
<node>
  <interface name='org.freedesktop.tuhi1.Manager'>
    <property type='ao' name='Devices' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>
    <property type='a(ss)' name='PairingDevices' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <method name='StartPairing'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

  </interface>

  <interface name='org.freedesktop.tuhi1.Device'>
    <property type='s' name='Name' access='read'/>
    <property type='uu' name='Dimensions' access='read'/>
    <property type='u' name='DrawingsAvailable' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <method name='Listen'>
      <annotation name='org.freedesktop.DBus.Method.NoReply' value='true'/>
    </method>

    <method name='GetJSONData'>
      <arg name='index' type='u' direction='in'/>
      <arg name='json' type='s' direction='out'/>
    </method>

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


class TuhiDBusDevice(GObject.Object):
    """
    Class representing a DBus object for a Tuhi device. This class only
    handles the DBus bits, communication with the device is done elsewhere.
    """
    def __init__(self, device, connection):
        GObject.Object.__init__(self)

        self.name = device.name
        self.btaddr = device.address
        self.width, self.height = 0, 0
        self.drawings = []
        objpath = device.address.replace(':', '_')
        self.objpath = "{}/{}".format(BASE_PATH, objpath)

        self._register_object(connection)

    def _register_object(self, connection):
        introspection = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        intf = introspection.lookup_interface(INTF_DEVICE)
        Gio.DBusConnection.register_object(connection,
                                           self.objpath,
                                           intf,
                                           self._method_cb,
                                           self._property_read_cb,
                                           self._property_write_cb)

    def _method_cb(self, connection, sender, objpath, interface, methodname, args, invocation):
        if interface != INTF_DEVICE:
            return None

        if methodname == 'Listen':
            self._listen()
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

        return None

    def _property_write_cb(self):
        pass

    def _listen(self):
        # FIXME: start listen asynchronously
        # FIXME: update property when listen finishes
        pass

    def _json_data(self, args):
        index = args[0]
        return self.drawings[index].json()

    def add_drawing(self, drawing):
        self.drawings.append(drawing)


class TuhiDBusServer(GObject.Object):
    """
    Class for the DBus server.
    """
    __gsignals__ = {
        "bus-name-acquired":
            (GObject.SIGNAL_RUN_FIRST, None, ()),
        "start-pairing-requested":
            (GObject.SIGNAL_RUN_FIRST, None, ()),
    }

    def __init__(self):
        GObject.Object.__init__(self)
        self._devices = []
        self._pairing_devices = {}
        self._dbus = Gio.bus_own_name(Gio.BusType.SESSION,
                                      BUS_NAME,
                                      Gio.BusNameOwnerFlags.NONE,
                                      self._bus_aquired,
                                      self._bus_name_aquired,
                                      self._bus_name_lost)

    def _bus_aquired(self, connection, name):
        introspection = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        intf = introspection.lookup_interface(INTF_MANAGER)
        Gio.DBusConnection.register_object(connection,
                                           BASE_PATH,
                                           intf,
                                           self._method_cb,
                                           self._property_read_cb,
                                           self._property_write_cb)
        self._connection = connection

    def _bus_name_aquired(self, connection, name):
        logger.debug('Bus name aquired')
        self.emit('bus-name-acquired')

    def _bus_name_lost(self, connection, name):
        pass

    def _method_cb(self, connection, sender, objpath, interface, methodname, args, invocation):
        if interface != INTF_MANAGER:
            return None

        if methodname == 'StartPairing':
            self._start_pairing()
            invocation.return_value()

    def _property_read_cb(self, connection, sender, objpath, interface, propname):
        if interface != INTF_MANAGER:
            return None

        if propname == 'Devices':
            return GLib.Variant.new_objv([d.objpath for d in self._devices])
        elif propname == 'PairingDevices':
            return GLib.Variant.new_array(GLib.VariantType.new('(ss)'),
                                          [GLib.Variant.new_tuple(
                                              GLib.Variant.new_string(k),
                                              GLib.Variant.new_string(v.name))
                                           for k, v in self._pairing_devices.items()])

        return None

    def _property_write_cb(self):
        pass

    def _start_pairing(self):
        self.emit("start-pairing-requested")

    def cleanup(self):
        Gio.bus_unown_name(self._dbus)

    def create_device(self, device):
        dev = TuhiDBusDevice(device, self._connection)
        self._devices.append(dev)
        return dev

    def add_pairing_device(self, bluez_device):
        address = bluez_device.address
        if address in self._pairing_devices:
            return

        self._pairing_devices[address] = bluez_device

    def reset_pairing_devices(self):
        self._pairing_devices = {}
