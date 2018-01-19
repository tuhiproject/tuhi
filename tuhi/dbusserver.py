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
    <property type='uu' name='Dimensions' access='read'/>
    <property type='u' name='DrawingsAvailable' access='read'>
      <annotation name='org.freedesktop.DBus.Property.EmitsChangedSignal' value='true'/>
    </property>

    <method name='Pair'>
      <arg name='result' type='i' direction='out'/>
    </method>

    <method name='Listen'>
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


class TuhiDBusDevice(GObject.Object):
    """
    Class representing a DBus object for a Tuhi device. This class only
    handles the DBus bits, communication with the device is done elsewhere.
    """
    __gsignals__ = {
        "pair-requested":
            (GObject.SIGNAL_RUN_FIRST, None, ()),
    }

    def __init__(self, device, connection, paired=True):
        GObject.Object.__init__(self)

        self.name = device.name
        self.btaddr = device.address
        self.width, self.height = 0, 0
        self.drawings = []
        self.paired = paired
        objpath = device.address.replace(':', '_')
        self.objpath = "{}/{}".format(BASE_PATH, objpath)

        self._connection = connection
        self._dbusid = self._register_object(connection)

    def remove(self):
        self._connection.unregister_object(self._dbusid)
        self._dbusid = None

    def _register_object(self, connection):
        introspection = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        intf = introspection.lookup_interface(INTF_DEVICE)
        return connection.register_object(self.objpath,
                                          intf,
                                          self._method_cb,
                                          self._property_read_cb,
                                          self._property_write_cb)

    def _method_cb(self, connection, sender, objpath, interface, methodname, args, invocation):
        if interface != INTF_DEVICE:
            return None

        if methodname == 'Pair':
            # FIXME: we should cache the method invocation here, wait for a
            # successful result from Tuhi and then return the value
            self._pair()
            result = GLib.Variant.new_int32(0)
            invocation.return_value(GLib.Variant.new_tuple(result))
        elif methodname == 'Listen':
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

    def _pair(self):
        self.emit('pair-requested')

    def _listen(self):
        # FIXME: start listen asynchronously
        # FIXME: update property when listen finishes
        pass

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

    def notify_button_press_required(self):
        logger.debug("Sending ButtonPressRequired signal")
        self._connection.emit_signal(None, self.objpath, INTF_DEVICE,
                                     "ButtonPressRequired", None)


class TuhiDBusServer(GObject.Object):
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
        GObject.Object.__init__(self)
        self._devices = []
        self._pairable_devices = {}
        self._dbus = Gio.bus_own_name(Gio.BusType.SESSION,
                                      BUS_NAME,
                                      Gio.BusNameOwnerFlags.NONE,
                                      self._bus_aquired,
                                      self._bus_name_aquired,
                                      self._bus_name_lost)
        self._is_searching = False

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

        if methodname == 'StartSearch':
            self._start_search()
            invocation.return_value()
        elif methodname == 'StopSearch':
            self._stop_search()
            invocation.return_value()

    def _property_read_cb(self, connection, sender, objpath, interface, propname):
        if interface != INTF_MANAGER:
            return None

        if propname == 'Devices':
            return GLib.Variant.new_objv([d.objpath for d in self._devices if d.paired])

        return None

    def _property_write_cb(self):
        pass

    def _start_search(self):
        if self._is_searching:
            return

        self._is_searching = True
        self.emit("search-start-requested", self._on_search_stop)

    def _stop_search(self):
        if not self._is_searching:
            return

        self._is_searching = False
        self.emit("search-stop-requested")

    def _on_search_stop(self, status):
        """
        Called by whoever handles the search-start-requested signal
        """
        logger.debug("Search has stopped")
        self._is_searching = False
        status = GLib.Variant.new_int32(status)
        status = GLib.Variant.new_tuple(status)
        self._connection.emit_signal(None, BASE_PATH, INTF_MANAGER,
                                     "SearchStopped", status)

        for dev in self._devices:
            if dev.paired:
                continue

            dev.remove()
        self._devices = [d for d in self._devices if d.paired]

    def cleanup(self):
        Gio.bus_unown_name(self._dbus)

    def create_device(self, device, paired=True):
        dev = TuhiDBusDevice(device, self._connection, paired)
        self._devices.append(dev)
        if not paired:
            arg = GLib.Variant.new_object_path(dev.objpath)
            self._connection.emit_signal(None, BASE_PATH, INTF_MANAGER,
                                         "PairableDevice",
                                         GLib.Variant.new_tuple(arg))
        return dev
