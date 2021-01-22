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


def list2hex(lst, groupsize=8):
    '''Converts a list of integers to a two-letter hex string in the form
    "1a 2b c3"'''

    slices = []
    for idx in range(0, len(lst), groupsize):
        s = ' '.join([f'{x:02x}' for x in lst[idx:idx + groupsize]])
        slices.append(s)

    return '    '.join(slices)


def flatten(items):
    '''flatten an array of mixed int and arrays into a simple array of int'''
    for item in items:
        if isinstance(item, int):
            yield item
        else:
            yield from flatten(item)
