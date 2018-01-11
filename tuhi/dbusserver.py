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

import sys
import json

from gi.repository import GObject, Gio, GLib

INTROSPECTION_XML = """
<node>
  <interface name='org.freedesktop.tuhi1.Manager'>
    <property type='ao' name='Devices' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>
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
JSON_FILE_FORMAT_VERSION = 1

class TuhiDrawing(object):
    class TuhiDrawingStroke(object):
        def __init__(self):
            pass

        def to_dict(self):
            d = {}
            for key in ['toffset', 'position', 'pressure']:
                val = getattr(self, key, None)
                if val is not None:
                    d['key'] = val
            return d

    def __init__(self, device):
        self.device = device
        self.timestamp = 0
        self.strokes = []

    def json(self):
        json_data = {
                'version': JSON_FILE_FORMAT_VERSION,
                'devicename': self.device.name,
                'dimensions' : [self.device.width, self.device.height],
                'strokes': [s.to_dict for s in self.strokes]
        }
        return json.dumps(json_data)


class TuhiDBusDevice(object):
    """
    Class representing a DBus object for a Tuhi device. This class only
    handles the DBus bits, communication with the device is done elsewhere.
    """
    def __init__(self, btaddr, connection):
        self.name = 'UNKNOWN'
        self.btaddr = btaddr
        self.width, self.height = 0, 0
        self.drawings = []
        self.objpath = "{}/{}".format(BASE_PATH, btaddr)

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


class TuhiDBusServer(object):
    """
    Class for the DBus server.
    """
    def __init__(self):
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

        # FIXME this shold be using the btaddr
        self._devices = [TuhiDBusDevice(0, connection)]

    def _bus_name_aquired(self, connection, name):
        pass

    def _bus_name_lost(self, connection, name):
        pass

    def _method_cb(self):
        pass

    def _property_read_cb(self, connection, sender, objpath, interface, propname):
        if interface != INTF_MANAGER:
            return None

        if propname == 'Devices':
            return GLib.Variant.new_objv([d.objpath for d in self._devices])

        return None

    def _property_write_cb(self):
        pass

    def cleanup(self):
        Gio.bus_unown_name(self._dbus)


def main(args):
    t = TuhiDBusServer()
    try:
        GObject.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        t.cleanup()


if __name__ == "__main__":
    main(sys.argv)
