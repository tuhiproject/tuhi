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


def list2hex(l, groupsize=8):
    '''Converts a list of integers to a two-letter hex string in the form
    "1a 2b c3"'''

    slices = []
    for idx in range(0, len(l), groupsize):
        s = ' '.join([f'{x:02x}' for x in l[idx:idx + groupsize]])
        slices.append(s)

    return '    '.join(slices)
