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

import subprocess
from multiprocessing import Process


def start_tuhi():
    subprocess.run('tuhi')


def start_tuhigui():
    subprocess.run('tuhi-gui')


if __name__ == '__main__':
    tuhi = Process(target=start_tuhi)
    tuhi.daemon = True
    tuhi.start()
    tuhigui = Process(target=start_tuhigui)
    tuhigui.start()
    tuhigui.join()
