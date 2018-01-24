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
import sys
import argparse
import json
import logging
import select
import time

logging.basicConfig(format='%(levelname)s: %(message)s',
                    level=logging.INFO)
logger = logging.getLogger('tuhi-kete')

TUHI_DBUS_NAME = 'org.freedesktop.tuhi1'
ORG_FREEDESKTOP_TUHI1_MANAGER = 'org.freedesktop.tuhi1.Manager'
ORG_FREEDESKTOP_TUHI1_DEVICE = 'org.freedesktop.tuhi1.Device'
ROOT_PATH = '/org/freedesktop/tuhi1'


class DBusError(Exception):
    def __init__(self, message):
        self.message = message


class _DBusObject(GObject.Object):
    _connection = None

    def __init__(self, name, interface, objpath):
        GObject.GObject.__init__(self)

        if _DBusObject._connection is None:
            self._connect_to_session()

        self.interface = interface
        self.objpath = objpath

        try:
            self.proxy = Gio.DBusProxy.new_sync(_DBusObject._connection,
                                                Gio.DBusProxyFlags.NONE, None,
                                                name, objpath, interface, None)
        except GLib.Error as e:
            if (e.domain == 'g-io-error-quark' and
                    e.code == Gio.IOErrorEnum.DBUS_ERROR):
                raise DBusError(e.message)
            else:
                raise e

        if self.proxy.get_name_owner() is None:
            raise DBusError('No-one is handling {}, is the daemon running?'.format(name))

        self.proxy.connect('g-properties-changed', self._on_properties_changed)
        self.proxy.connect('g-signal', self._on_signal_received)

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


class TuhiKeteDevice(_DBusObject):
    def __init__(self, manager, objpath):
        _DBusObject.__init__(self, TUHI_DBUS_NAME,
                             ORG_FREEDESKTOP_TUHI1_DEVICE,
                             objpath)
        self.manager = manager
        self.is_pairing = False

    @GObject.Property
    def address(self):
        return self.property('Address')

    @GObject.Property
    def name(self):
        return self.property('Name')

    @GObject.Property
    def listening(self):
        return self.property('Listening')

    @GObject.Property
    def drawings_available(self):
        return self.property('DrawingsAvailable')

    def pair(self):
        logger.debug('{}: Pairing'.format(self))
        # FIXME: Pair() doesn't return anything useful yet, so we wait until
        # the device is in the Manager's Devices property
        self.manager.connect('notify::devices', self._on_mgr_devices_updated)
        self.is_pairing = True
        self.proxy.Pair()

    def start_listening(self):
        self.proxy.StartListening()

    def stop_listening(self):
        self.proxy.StopListening()

    def json(self, index):
        return self.proxy.GetJSONData('(u)', index)

    def _on_signal_received(self, proxy, sender, signal, parameters):
        if signal == 'ButtonPressRequired':
            print("{}: Press button on device now".format(self))
        elif signal == 'ListeningStopped':
            self.notify('listening')

    def _on_properties_changed(self, proxy, changed_props, invalidated_props):
        if changed_props is None:
            return

        changed_props = changed_props.unpack()

        if 'DrawingsAvailable' in changed_props:
            self.notify('drawings-available')

    def __repr__(self):
        return '{} - {}'.format(self.address, self.name)

    def _on_mgr_devices_updated(self, manager, pspec):
        if not self.is_pairing:
            return

        for d in manager.devices:
            if d.address == self.address:
                self.is_pairing = False
                print('{}: Pairing successful'.format(self))
                self.manager.quit()


class TuhiKeteManager(_DBusObject):
    __gsignals__ = {
        "pairable-device":
            (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self):
        _DBusObject.__init__(self, TUHI_DBUS_NAME,
                             ORG_FREEDESKTOP_TUHI1_MANAGER,
                             ROOT_PATH)

        Gio.bus_watch_name(Gio.BusType.SESSION,
                           TUHI_DBUS_NAME,
                           Gio.BusNameWatcherFlags.NONE,
                           None,
                           self._on_name_vanished)

        self.mainloop = GObject.MainLoop()
        self._devices = {}
        self._pairable_devices = {}
        for objpath in self.property('Devices'):
            device = TuhiKeteDevice(self, objpath)
            self._devices[device.address] = device

    @GObject.Property
    def devices(self):
        return [v for k, v in self._devices.items()]

    @GObject.Property
    def searching(self):
        return self.proxy.get_cached_property('Searching')

    def start_search(self):
        self._pairable_devices = {}
        self.proxy.StartSearch()

    def stop_search(self):
        self.proxy.StopSearch()
        self._pairable_devices = {}

    def run(self):
        try:
            self.mainloop.run()
        except KeyboardInterrupt:
            print('\r', end='')  # to remove the ^C
            self.mainloop.quit()

    def quit(self):
        self.mainloop.quit()

    def _on_properties_changed(self, proxy, changed_props, invalidated_props):
        if changed_props is None:
            return

        changed_props = changed_props.unpack()

        if 'Devices' in changed_props:
            objpaths = changed_props['Devices']
            for objpath in objpaths:
                try:
                    d = self._pairable_devices[objpath]
                    self._devices[d.address] = d
                    del self._pairable_devices[objpath]
                except KeyError:
                    # if we called Pair() on an existing device it's not in
                    # pairable devices
                    pass
            self.notify('devices')

    def _on_signal_received(self, proxy, sender, signal, parameters):
        if signal == 'SearchStopped':
            self.notify('searching')
        elif signal == 'PairableDevice':
            objpath = parameters[0]
            device = TuhiKeteDevice(self, objpath)
            self._pairable_devices[objpath] = device
            logger.debug('Found pairable device: {}'.format(device))
            self.emit('pairable-device', device)

    def _on_name_vanished(self, connection, name):
        logger.error('Tuhi daemon went away')
        self.mainloop.quit()

    def __getitem__(self, btaddr):
        return self._devices[btaddr]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class Searcher(GObject.Object):
    def __init__(self, manager, address=None):
        GObject.GObject.__init__(self)
        self.manager = manager
        self.address = address
        self.is_pairing = False

    def run(self):
        if self.manager.searching:
            logger.error('Another client is already searching')
            return

        self.manager.connect('notify::searching', self._on_notify_search)
        self.manager.connect('pairable-device', self._on_pairable_device)
        self.manager.start_search()
        logger.debug('Started searching')

        for d in self.manager.devices:
            self._on_pairable_device(self.manager, d)

        self.manager.run()

        if self.manager.searching:
            logger.debug('Stopping search')
            self.manager.stop_search()

    def _on_notify_search(self, manager, pspec):
        if not manager.searching:
            logger.info('Search cancelled')
            if not self.is_pairing:
                self.manager.quit()

    def _on_pairable_device(self, manager, device):
        print('Pairable device: {}'.format(device))

        if self.address is None:
            print('Connect to device? [y/N] ', end='')
            sys.stdout.flush()
            i, o, e = select.select([sys.stdin], [], [], 5)
            if i:
                answer = sys.stdin.readline().strip()
                if answer.lower() == 'y':
                    self.address = device.address
            else:
                print('timed out')

        if device.address == self.address:
            self.is_pairing = True
            device.pair()


class Listener(GObject.Object):
    def __init__(self, manager, address):
        GObject.GObject.__init__(self)
        self.mainloop = GObject.MainLoop()

        self.manager = manager
        self.device = None
        for d in manager.devices:
            if d.address == address:
                self.device = d
                break
        else:
            logger.error("{}: device not found".format(address))
            return

    def run(self):
        if self.device is None:
            return

        if self.device.drawings_available > 0:
            logger.info('{}: drawings available: {}'.format(self.device, self.device.drawings_available))

        if self.device.listening:
            logger.info("{}: device already listening".format(self.device))
            return

        logger.debug("{}: starting listening".format(self.device))
        self.device.connect('notify::listening', self._on_device_listening)
        self.device.connect('notify::drawings-available', self._on_drawings_available)
        self.device.start_listening()

        self.manager.run()
        logger.debug("{}: stopping listening".format(self.device))
        try:
            self.device.stop_listening()
        except GLib.Error as e:
            if (e.domain != 'g-dbus-error-quark' or
                    e.code != Gio.IOErrorEnum.EXISTS or
                    Gio.dbus_error_get_remote_error(e) != 'org.freedesktop.DBus.Error.ServiceUnknown'):
                raise e

    def _on_device_listening(self, device, pspec):
        logger.info('{}: Listening stopped, exiting'.format(device))
        self.manager.quit()

    def _on_drawings_available(self, device, pspec):
        logger.info('{}: drawings available: {}'.format(device, device.drawings_available))


class Fetcher(GObject.Object):
    def __init__(self, manager, address, index):
        GObject.GObject.__init__(self)
        self.mainloop = GObject.MainLoop()
        self.manager = manager
        self.device = None
        self.indices = None

        for d in manager.devices:
            if d.address == address:
                self.device = d
                break
        else:
            logger.error("{}: device not found".format(address))
            return

        ndrawings = self.device.drawings_available
        if index != 'all':
            try:
                self.indices = [int(index)]
                if index >= ndrawings:
                    raise ValueError()
            except ValueError:
                logger.error("Invalid index {}".format(index))
                return
        else:
            self.indices = list(range(ndrawings))

    def run(self):
        if self.device is None or self.indices is None:
            return

        for idx in self.indices:
            jsondata = self.device.json(idx)
            data = json.loads(jsondata)
            timestamp = time.gmtime(int(data['timestamp']))
            logger.info("{}: drawing made on {}, {} strokes".format(
                data['devicename'],
                time.strftime('%Y-%m-%d %H:%M', timestamp),
                len(data['strokes'])))


def print_device(d):
    print('{}: {}'.format(d.address, d.name))


def cmd_list(manager, args):
    logger.debug('Listing available devices:')
    for d in manager.devices:
        print_device(d)


def cmd_pair(manager, args):
    Searcher(manager, args.address).run()


def cmd_listen(manager, args):
    Listener(manager, args.address).run()


def cmd_fetch(manager, args):
    Fetcher(manager, args.address, args.index).run()


def parse_list(parser):
    sub = parser.add_parser('list', help='list known devices')
    sub.set_defaults(func=cmd_list)


def parse_pair(parser):
    sub = parser.add_parser('pair', help='pair a new device')
    sub.add_argument('address', metavar='12:34:56:AB:CD:EF', type=str,
                     nargs='?', default=None,
                     help='the address of the device to pair')
    sub.set_defaults(func=cmd_pair)


def parse_listen(parser):
    sub = parser.add_parser('listen', help='listen to events from a device')
    sub.add_argument('address', metavar='12:34:56:AB:CD:EF', type=str,
                     default=None,
                     help='the address of the device to listen to')
    sub.set_defaults(func=cmd_listen)


def parse_fetch(parser):
    sub = parser.add_parser('fetch', help='download a drawing from a device')
    sub.add_argument('address', metavar='12:34:56:AB:CD:EF', type=str,
                     default=None,
                     help='the address of the device to fetch from')
    sub.add_argument('index', metavar='[<index>|all]', type=str,
                     default=None,
                     help='the index of the drawing to fetch or a literal "all"')
    sub.set_defaults(func=cmd_fetch)


def parse(args):
    desc = 'Commandline client to the Tuhi DBus daemon'
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument('-v', '--verbose',
                        help='Show some debugging informations',
                        action='store_true',
                        default=False)

    subparser = parser.add_subparsers(help='Available commands')
    parse_list(subparser)
    parse_pair(subparser)
    parse_listen(subparser)
    parse_fetch(subparser)

    return parser.parse_args(args[1:])


def main(args):
    args = parse(args)
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        with TuhiKeteManager() as mgr:
            if not hasattr(args, 'func'):
                args.func = cmd_list

            args.func(mgr, args)

    except DBusError as e:
        logger.error(e.message)


if __name__ == "__main__":
    main(sys.argv)
