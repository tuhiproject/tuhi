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
import cmd
import os
import json
import logging
import re
import readline
import select
import threading
import time
import svgwrite


log_format = '%(levelname)s: %(message)s'
logger_handler = logging.StreamHandler()
logger_handler.setFormatter(logging.Formatter(log_format))
logger = logging.getLogger('tuhi-kete')
logger.addHandler(logger_handler)
logger.setLevel(logging.INFO)

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

    @classmethod
    def is_device_address(cls, string):
        if re.match(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}$", string.lower()):
            return string
        raise argparse.ArgumentTypeError(f'"{string}" is not a valid device address')

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
            logger.info(f'{self}: Press button on device now')
        elif signal == 'ListeningStopped':
            err = parameters[0]
            if err < 0:
                logger.error(f'{self}: an error occured: {os.strerror(err)}')
            self.notify('listening')

    def _on_properties_changed(self, proxy, changed_props, invalidated_props):
        if changed_props is None:
            return

        changed_props = changed_props.unpack()

        if 'DrawingsAvailable' in changed_props:
            self.notify('drawings-available')
        elif 'Listening' in changed_props:
            self.notify('listening')

    def __repr__(self):
        return '{} - {}'.format(self.address, self.name)

    def _on_mgr_devices_updated(self, manager, pspec):
        if not self.is_pairing:
            return

        for d in manager.devices:
            if d.address == self.address:
                self.is_pairing = False
                logger.info(f'{self}: Pairing successful')
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

        self.mainloop = None
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
        if self.mainloop is None:
            self.mainloop = GObject.MainLoop()

        try:
            self.mainloop.run()
        except KeyboardInterrupt:
            print('\r', end='')  # to remove the ^C
            self.mainloop.quit()

    def quit(self):
        if self.mainloop is not None:
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


class Args(object):
    pass


class Worker(GObject.Object):
    """Implements a command to be executed.
    Subclasses need to overwrite run() that will be executed
    to setup the command (before the mainloop).
    Subclass can also implement the stop() method which
    will be executed to terminate the command, once the
    mainloop has finished.

    The variable need_mainloop needs to be set from the
    subclass if the command requires the mainloop to be
    run from an undetermined amount of time."""

    need_mainloop = False

    def __init__(self, manager, args=None):
        GObject.GObject.__init__(self)
        self.manager = manager
        self._run = self.run
        self._stop = self.stop

    def run(self):
        pass

    def stop(self):
        pass

    def start(self):
        self._run()

        if self.need_mainloop:
            self.manager.run()

        self._stop()


class Searcher(Worker):
    need_mainloop = True
    interactive = True

    def __init__(self, manager, args):
        super(Searcher, self).__init__(manager)
        self.address = args.address
        self.is_pairing = False

    def run(self):
        if self.manager.searching:
            logger.error('Another client is already searching')
            return

        self.s1 = self.manager.connect('notify::searching', self._on_notify_search)
        self.s2 = self.manager.connect('pairable-device', self._on_pairable_device)
        self.manager.start_search()
        logger.debug('Started searching')

        for d in self.manager.devices:
            self._on_pairable_device(self.manager, d)

    def stop(self):
        if self.manager.searching:
            logger.debug('Stopping search')
            self.manager.stop_search()
        self.manager.disconnect(self.s1)
        self.manager.disconnect(self.s2)

    def _on_notify_search(self, manager, pspec):
        if not manager.searching:
            logger.info('Search cancelled')
            if not self.is_pairing and self.interactive:
                self.stop()

    def _on_pairable_device_interactive(self, manager, device):
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

    def _on_pairable_device(self, manager, device):
        logger.info('Pairable device: {}'.format(device))

        if self.interactive:
            self._on_pairable_device_interactive(manager, device)


class Listener(Worker):
    need_mainloop = True

    def __init__(self, manager, args):
        super(Listener, self).__init__(manager)

        self.device = None
        for d in manager.devices:
            if d.address == args.address:
                self.device = d
                break
        else:
            logger.error("{}: device not found".format(args.address))
            # FIXME: this should be an exception
            return

    def run(self):
        if self.device is None:
            return

        if self.device.drawings_available:
            self._log_drawings_available(self.device)

        if self.device.listening:
            logger.info("{}: device already listening".format(self.device))
            return

        logger.debug("{}: starting listening".format(self.device))
        self.s1 = self.device.connect('notify::listening', self._on_device_listening)
        self.s2 = self.device.connect('notify::drawings-available', self._on_drawings_available)
        self.device.start_listening()

    def stop(self):
        logger.debug("{}: stopping listening".format(self.device))
        try:
            self.device.stop_listening()
            self.device.disconnect(self.s1)
            self.device.disconnect(self.s2)
        except GLib.Error as e:
            if (e.domain != 'g-dbus-error-quark' or
                    e.code != Gio.IOErrorEnum.EXISTS or
                    Gio.dbus_error_get_remote_error(e) != 'org.freedesktop.DBus.Error.ServiceUnknown'):
                raise e

    def _on_device_listening(self, device, pspec):
        if self.device.listening:
            return

        logger.info('{}: Listening stopped'.format(device))

    def _on_drawings_available(self, device, pspec):
        self._log_drawings_available(device)

    def _log_drawings_available(self, device):
        s = ", ".join(["{}".format(t) for t in device.drawings_available])
        logger.info('{}: drawings available: {}'.format(device, s))


class Fetcher(Worker):
    def __init__(self, manager, args):
        super(Fetcher, self).__init__(manager)
        self.device = None
        self.indices = None
        address = args.address
        index = args.index

        for d in manager.devices:
            if d.address == address:
                self.device = d
                break
        else:
            logger.error("{}: device not found".format(address))
            return

        if index != 'all':
            try:
                index = int(index)
                if index not in self.device.drawings_available:
                    raise ValueError()
                self.indices = [index]
            except ValueError:
                logger.error("Invalid index {}".format(index))
                return
        else:
            self.indices = self.device.drawings_available

    def run(self):
        if self.device is None or self.indices is None:
            return

        for idx in self.indices:
            jsondata = self.device.json(idx)
            data = json.loads(jsondata)
            t = time.gmtime(data['timestamp'])
            t = time.strftime('%Y-%m-%d-%H-%M', t)
            path = f'{data["devicename"]}-{t}.svg'
            self.json_to_svg(data, path)
            logger.info(f'{data["devicename"]}: saved file "{path}"')

    def json_to_svg(self, js, filename):
        dimensions = js['dimensions']
        if dimensions == [0, 0]:
            dimensions = 100, 100
        svg = svgwrite.Drawing(filename=filename, size=dimensions)
        g = svgwrite.container.Group(id='layer0')
        for s in js['strokes']:
            svgpoints = []
            mode = 'M'
            for p in s['points']:
                x, y = p['position']
                svgpoints.append((mode, x, y))
                mode = 'L'
            path = svgwrite.path.Path(d=svgpoints,
                                      style="fill:none;stroke:black;stroke-width:5")
            g.add(path)

        svg.add(g)
        svg.save()


class Printer(Worker):
    def run(self):
        logger.debug('Listing available devices:')
        for d in self.manager.devices:
            print(d)


class TuhiKeteShellLogHandler(logging.StreamHandler):
    def __init__(self):
        super(TuhiKeteShellLogHandler, self).__init__(sys.stdout)
        self.setFormatter(logging.Formatter(log_format))
        self._prompt = ''

    def emit(self, record):
        self.terminator = f'\n{self._prompt}{readline.get_line_buffer()}'
        super(TuhiKeteShellLogHandler, self).emit(record)

    def set_normal_mode(self):
        self.acquire()
        self.setFormatter(logging.Formatter(log_format))
        self.terminator = '\n'
        self._prompt = ''
        self.release()

    def set_prompt_mode(self, prompt):
        self.acquire()
        # '\x1b[2K\r' clears the current line and start again from the beginning
        self.setFormatter(logging.Formatter(f'\x1b[2K\r{log_format}'))
        self._prompt = prompt
        self.release()


class TuhiKeteShell(cmd.Cmd):
    intro = 'Tuhi shell control'
    prompt = 'tuhi> '

    def __init__(self, manager, completekey='tab', stdin=None, stdout=None):
        super(TuhiKeteShell, self).__init__(completekey, stdin, stdout)
        self._manager = manager
        self._workers = []
        self._log_handler = TuhiKeteShellLogHandler()
        logger.removeHandler(logger_handler)
        logger.addHandler(self._log_handler)
        # patching get_names to hide some functions we do not want in the help
        self.get_names = self._filtered_get_names

    def _filtered_get_names(self):
        names = super(TuhiKeteShell, self).get_names()
        names.remove('do_EOF')
        return names

    def emptyline(self):
        # make sure we do not re-enter the last typed command
        pass

    def do_EOF(self, arg):
        print('\n\r', end='')  # to remove the appended weird char
        return self.do_exit(arg)

    def do_exit(self, args):
        '''leave the shell'''
        for worker in self._workers:
            worker.stop()
        return True

    def precmd(self, line):
        # Restore the logger facility to something sane:
        self._log_handler.set_normal_mode()
        return line

    def postcmd(self, stop, line):
        # overwrite the logger facility to remove the current prompt and append
        # a new one
        self._log_handler.set_prompt_mode(self.prompt)
        return stop

    def run(self, init=None):
        try:
            self.cmdloop(init)
        except KeyboardInterrupt as e:
            print("^C")
            self.run('')

    def start_worker(self, worker_class, args=None):
        worker = worker_class(self._manager, args)
        worker.run()
        self._workers.append(worker)

    def do_list(self, arg):
        '''list known devices'''
        self.start_worker(Printer)

    def help_listen(self):
        self.do_listen('-h')

    def do_listen(self, args):
        '''Listen to a specific device'''
        parser = argparse.ArgumentParser(prog='listen',
                                         description='Listen to a specific device',
                                         add_help=False)
        parser.add_argument('-h', action='help', help=argparse.SUPPRESS)
        parser.add_argument('address', metavar='12:34:56:AB:CD:EF',
                            type=TuhiKeteDevice.is_device_address,
                            default=None,
                            help='the address of the device to listen to')
        parser.add_argument('mode', choices=['on', 'off'], nargs='?',
                            const='on', default='on')
        try:
            parsed_args = parser.parse_args(args.split())
        except SystemExit:
            return

        address = parsed_args.address
        mode = parsed_args.mode

        for d in self._manager.devices:
            if d.address == address:
                if mode == 'on' and d.listening:
                    print(f'Already listening on {address}')
                    return
                elif mode == 'off' and not d.listening:
                    print(f'Not listening on {address}')
                    return
                break
        else:
            print(f'Device {address} not found')
            return

        if mode == 'off':
            for worker in [w for w in self._workers if isinstance(w, Listener)]:
                if worker.device.address == address:
                    worker.stop()
                    self._workers.remove(worker)
                    break
            return

        wargs = Args()
        wargs.address = address
        self.start_worker(Listener, wargs)

    def help_fetch(self):
        self.do_fetch('-h')

    def do_fetch(self, args):
        '''Fetches one or all drawing(s) from a specific device.'''

        def is_index_or_all(string):
            try:
                n = int(string)
            except ValueError:
                if string == 'all':
                    return string
                raise argparse.ArgumentTypeError(f'"{string}" is neither a timestamp nor "all"')
            else:
                return n

        parser = argparse.ArgumentParser(prog='fetch',
                                         description='Fetches a drawing or all drawings from a specific device.',
                                         add_help=False)
        parser.add_argument('-h', action='help', help=argparse.SUPPRESS)
        parser.add_argument('address', metavar='12:34:56:AB:CD:EF',
                            type=TuhiKeteDevice.is_device_address,
                            default=None,
                            help='the address of the device to fetch drawing from')
        parser.add_argument('index', metavar='{<index>|all}',
                            type=is_index_or_all,
                            const='all', nargs='?', default='all',
                            help='the index of the drawing to fetch or a literal "all"')

        try:
            parsed_args = parser.parse_args(args.split())
        except SystemExit:
            return

        address = parsed_args.address
        index = parsed_args.index

        address = args[0]
        try:
            index = args[1]
        except IndexError:
            index = 'all'

        if index != 'all':
            try:
                int(index)
            except ValueError:
                print(self._fetch_usage)
                return

        wargs = Args()
        wargs.address = address
        wargs.index = index
        self.start_worker(Fetcher, wargs)

    def help_search(self):
        self.do_search('-h')

    def do_search(self, args):
        '''Start/Stop listening for devices in pairable mode'''
        parser = argparse.ArgumentParser(prog='search',
                                         description='Start/Stop listening for devices in pairable mode.',
                                         add_help=False)
        parser.add_argument('-h', action='help', help=argparse.SUPPRESS)
        parser.add_argument('mode', choices=['on', 'off'], nargs='?',
                            const='on', default='on')

        try:
            parsed_args = parser.parse_args(args.split())
        except SystemExit:
            return

        if parsed_args.mode == 'off':
            self._manager.stop_search()
            return

        Searcher.interactive = False
        wargs = Args()
        wargs.address = None
        self.start_worker(Searcher, wargs)

    def help_pair(self):
        self.do_pair('-h')

    def do_pair(self, args):
        '''Pair a specific device in pairable mode'''
        if not self._manager.searching and '-h' not in args.split():
            print("please call search first")
            return

        parser = argparse.ArgumentParser(prog='pair',
                                         description='Pair a specific device in pairable mode.',
                                         add_help=False)
        parser.add_argument('-h', action='help', help=argparse.SUPPRESS)
        parser.add_argument('address', metavar='12:34:56:AB:CD:EF',
                            type=TuhiKeteDevice.is_device_address,
                            default=None,
                            help='the address of the device to pair')

        try:
            parsed_args = parser.parse_args(args.split())
        except SystemExit:
            return

        address = parsed_args.address

        device = None

        for d in self._manager.devices:
            if d.address == address:
                device = d
                break
        else:
            logger.error("{}: device not found".format(address))
            return

        device.pair()

    def help_info(self):
        self.do_info('-h')

    def do_info(self, args):
        '''Show some informations about a given device or all of them'''

        parser = argparse.ArgumentParser(prog='info',
                                         description='Show some informations about a given device or all of them',
                                         add_help=False)
        parser.add_argument('-h', action='help', help=argparse.SUPPRESS)
        parser.add_argument('address', metavar='12:34:56:AB:CD:EF',
                            type=TuhiKeteDevice.is_device_address,
                            default=None, nargs='?',
                            help='the address of the device to listen to')

        try:
            parsed_args = parser.parse_args(args.split())
        except SystemExit:
            return

        for device in self._manager.devices:
            if parsed_args.address is None or parsed_args.address == device.address:
                print(device)
                print('\tAvailable drawings:')
                for d in device.drawings_available:
                    t = time.gmtime(d)
                    t = time.strftime('%Y-%m-%d at %H:%M', t)
                    print(f'\t\t* {d}: drawn on the {t}')


class TuhiKeteShellWorker(Worker):
    def __init__(self, manager, args):
        super(TuhiKeteShellWorker, self).__init__(manager)

    def start_mainloop(self):
        # we can not call GLib.MainLoop() here or it will install a unix signal
        # handler for SIGINT, and we will not be able to catch
        # KeyboardInterrupt in cmdloop()
        mainloop = GLib.MainLoop.new(None, False)

        mainloop.run()

    def start(self):
        self._glib_thread = threading.Thread(target=self.start_mainloop)
        self._glib_thread.daemon = True
        self._glib_thread.start()

        self.run()

        self.stop()

    def run(self):
        self._shell = TuhiKeteShell(self.manager)
        self._shell.run()


def parse_list(parser):
    sub = parser.add_parser('list', help='list known devices')
    sub.set_defaults(worker=Printer)


def parse_pair(parser):
    sub = parser.add_parser('pair', help='pair a new device')
    sub.add_argument('address', metavar='12:34:56:AB:CD:EF',
                     type=TuhiKeteDevice.is_device_address,
                     nargs='?', default=None,
                     help='the address of the device to pair')
    sub.set_defaults(worker=Searcher)


def parse_listen(parser):
    sub = parser.add_parser('listen', help='listen to events from a device')
    sub.add_argument('address', metavar='12:34:56:AB:CD:EF',
                     type=TuhiKeteDevice.is_device_address,
                     default=None,
                     help='the address of the device to listen to')
    sub.set_defaults(worker=Listener)


def parse_fetch(parser):
    sub = parser.add_parser('fetch', help='download a drawing from a device and save as svg in $PWD')
    sub.add_argument('address', metavar='12:34:56:AB:CD:EF',
                     type=TuhiKeteDevice.is_device_address,
                     default=None,
                     help='the address of the device to fetch from')
    sub.add_argument('index', metavar='[<index>|all]', type=str,
                     default=None,
                     help='the index of the drawing to fetch or a literal "all"')
    sub.set_defaults(worker=Fetcher)


def parse_shell(parser):
    sub = parser.add_parser('shell', help='run a bash-like shell')
    sub.set_defaults(worker=TuhiKeteShellWorker)


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
    parse_shell(subparser)

    return parser.parse_args(args[1:])


def main(args):
    args = parse(args)
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if not hasattr(args, 'worker'):
        args.worker = TuhiKeteShellWorker

    try:
        with TuhiKeteManager() as mgr:
            worker = args.worker(mgr, args)
            worker.start()

    except DBusError as e:
        logger.error(e.message)


if __name__ == "__main__":
    main(sys.argv)
