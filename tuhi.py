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

from tuhi.dbusserver import TuhiDBusServer
from gi.repository import GObject
import sys

def main(args):
    t = TuhiDBusServer()
    try:
        import tuhi.ble
        tuhi.ble.main(None)
        GObject.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        t.cleanup()

if __name__ == "__main__":
    main(sys.argv)
