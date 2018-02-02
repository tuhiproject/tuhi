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
import multiprocessing


def maybe_start_tuhi(queue):
    should_start = queue.get()

    if not should_start:
        return

    import tuhi.base
    tuhi.base.main(['tuhi'])


def main(args=sys.argv):

    queue = multiprocessing.Queue()

    tuhi_process = multiprocessing.Process(target=maybe_start_tuhi, args=(queue,))
    tuhi_process.daemon = True
    tuhi_process.start()

    # import after spawning the process, or the 2 processes will fight for GLib
    import tuhi_kete
    from gi.repository import Gio, GLib

    # connect to the session
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        if (e.domain == 'g-io-error-quark' and
                e.code == Gio.IOErrorEnum.DBUS_ERROR):
            raise tuhi_kete.DBusError(e.message)
        else:
            raise e

    # attempt to connect to tuhi
    try:
        proxy = Gio.DBusProxy.new_sync(connection,
                                       Gio.DBusProxyFlags.NONE, None,
                                       tuhi_kete.TUHI_DBUS_NAME,
                                       tuhi_kete.ROOT_PATH,
                                       tuhi_kete.ORG_FREEDESKTOP_TUHI1_MANAGER,
                                       None)
    except GLib.Error as e:
        if (e.domain == 'g-io-error-quark' and
                e.code == Gio.IOErrorEnum.DBUS_ERROR):
            raise tuhi_kete.DBusError(e.message)
        else:
            raise e

    started = proxy.get_name_owner() is not None

    if not started:
        print(f'No-one is handling {tuhi_kete.TUHI_DBUS_NAME}, attempting to start a daemon')

    queue.put(not started)

    tuhi_kete.main(args)


if __name__ == '__main__':
    main(sys.argv)
