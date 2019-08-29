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
import logging
import os
import pwd
import sys
import multiprocessing
from multiprocessing import reduction

try:
    import tuhi.dbusclient
except ModuleNotFoundError:
    # If PYTHONPATH isn't set up or we never installed Tuhi, the module
    # isn't available. And since we don't install tuhi-live, we can assume that
    # we're still in the git repo, so messing with the path is "fine".
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + '/..')  # noqa
    import tuhi.dbusclient


manager = None
logger = None


def open_uhid_process(queue_in, conn_out):
    while True:
        try:
            pid = queue_in.get()
        except KeyboardInterrupt:
            return 0
        else:
            fd = os.open('/dev/uhid', os.O_RDWR)
            reduction.send_handle(conn_out, fd, pid)


def maybe_start_tuhi(queue):
    try:
        should_start, verbose = queue.get()
    except KeyboardInterrupt:
        return 0

    if not should_start:
        return

    sys.path.append(os.getcwd())

    import tuhi.base
    args = ['tuhi-live']  # argparse in tuhi.base.main skips argv[0]
    if verbose:
        args.append('--verbose')

    tuhi.base.main(args)


def start_tuhi_server(args):
    queue = multiprocessing.Queue()

    tuhi_process = multiprocessing.Process(target=maybe_start_tuhi, args=(queue,))
    tuhi_process.daemon = True
    tuhi_process.start()

    sys.path.append(os.path.join(os.getcwd(), 'tools'))

    # import after spawning the process, or the 2 processes will fight for GLib
    import kete
    from gi.repository import Gio, GLib

    global logger
    logger = logging.getLogger('tuhi-live')
    logger.addHandler(kete.logger_handler)
    logger.setLevel(logging.INFO)

    logger.debug('connecting to the bus')

    # connect to the session
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        if (e.domain == 'g-io-error-quark' and
                e.code == Gio.IOErrorEnum.DBUS_ERROR):
            raise tuhi.dbusclient.DBusError(e.message)
        else:
            raise e

    logger.debug('looking for tuhi on the bus')
    # attempt to connect to tuhi
    try:
        proxy = Gio.DBusProxy.new_sync(connection,
                                       Gio.DBusProxyFlags.NONE, None,
                                       tuhi.dbusclient.TUHI_DBUS_NAME,
                                       tuhi.dbusclient.ROOT_PATH,
                                       tuhi.dbusclient.ORG_FREEDESKTOP_TUHI1_MANAGER,
                                       None)
    except GLib.Error as e:
        if (e.domain == 'g-io-error-quark' and
                e.code == Gio.IOErrorEnum.DBUS_ERROR):
            raise tuhi.dbusclient.DBusError(e.message)
        else:
            raise e

    started = proxy.get_name_owner() is not None

    if not started:
        print(f'No-one is handling {tuhi.dbusclient.TUHI_DBUS_NAME}, attempting to start a daemon')

    queue.put((not started, args.verbose))


def run_live(request_fd_queue, conn_fd):
    from gi.repository import Gio, GLib

    def on_name_appeared(connection, name, client):
        global manager
        logger.info('Connected to the Tuhi daemon')
        manager = tuhi.dbusclient.TuhiDBusClientManager()

        for device in manager.devices:
            logger.info(f'starting live on {device}, please press button on the device')
            request_fd_queue.put(os.getpid())
            fd = reduction.recv_handle(conn_fd)
            device.start_live(fd)

    Gio.bus_watch_name(Gio.BusType.SESSION,
                       tuhi.dbusclient.TUHI_DBUS_NAME,
                       Gio.BusNameWatcherFlags.NONE,
                       on_name_appeared,
                       None)

    mainloop = GLib.MainLoop()

    connected_devices = 0

    def on_disconnect(dev, pspec):
        mainloop.quit()

    wait_for_disconnect = False

    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    finally:
        for device in manager.devices:
            if device.live:
                connected_devices += 1

        for device in manager.devices:
            if device.live and device.connected:
                logger.info(f'stopping live on {device}')
                device.connect('notify::connected', on_disconnect)
                device.stop_live()
                wait_for_disconnect = True

    # we re-run the mainloop to terminate the connections
    if wait_for_disconnect:
        try:
            mainloop.run()
        except KeyboardInterrupt:
            pass


def drop_privileges():
    sys.stderr.write('dropping privileges\n')

    os.setgroups([])
    gid = int(os.getenv('SUDO_GID'))
    uid = int(os.getenv('SUDO_UID'))
    pwname = os.getenv('SUDO_USER')
    os.setresgid(gid, gid, gid)
    os.initgroups(pwname, gid)
    os.setresuid(uid, uid, uid)

    pw = pwd.getpwuid(uid)

    # we completely clear the environment and start a new and controlled one
    os.environ.clear()
    os.environ['XDG_RUNTIME_DIR'] = f'/run/user/{uid}'
    os.environ['HOME'] = pw.pw_dir


def parse(args):
    desc = 'tool to start the live mode on all devices tuhi knows about'
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument('-v', '--verbose',
                        help='Show some debugging informations',
                        action='store_true',
                        default=False)

    return parser.parse_args(args[1:])


def main(args=sys.argv):
    if not os.geteuid() == 0:
        sys.exit('Script must be run as root')

    args = parse(args)

    request_fd_queue = multiprocessing.Queue()
    conn_in, conn_out = multiprocessing.Pipe()

    fd_process = multiprocessing.Process(target=open_uhid_process, args=(request_fd_queue, conn_out))
    fd_process.daemon = True
    fd_process.start()

    drop_privileges()

    start_tuhi_server(args)
    run_live(request_fd_queue, conn_in)


if __name__ == '__main__':
    main(sys.argv)
