#!/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2019 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import argparse
import os
import sys
from pathlib import Path
import yaml
import json
import logging

# This tool isn't installed, so we can assume that the tuhi module is always
# in the parent directory
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + '/..')  # noqa
from tuhi.util import flatten  # noqa
from tuhi.drawing import Drawing  # noqa
from tuhi.protocol import StrokeFile  # noqa
from tuhi.export import JsonSvg, JsonPng  # noqa
from tuhi.wacom import WacomProtocolSpark, WacomProtocolIntuosPro, WacomProtocolSlate  # noqa

logging.basicConfig(format='%(asctime)s %(levelname)s: %(name)s: %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S')
logger = logging.getLogger('tuhi')  # set the pseudo-root logger to take advantage of the other loggers


def parse_file(filename, file_format, tablet_model, orientation):
    width = tablet_model.width
    height = tablet_model.height
    pressure = tablet_model.pressure
    point_size = tablet_model.point_size
    orientation = orientation or tablet_model.orientation

    stem = Path(filename).stem
    with open(filename) as fd:
        yml = yaml.load(fd, Loader=yaml.Loader)
        if not yml:
            print(f'{filename}: empty file.')
            return

        # all recv lists that have source PEN
        pendata = [d['recv'] for d in yml['data'] if 'recv' in d and 'source' in d and d['source'] == 'PEN']
        data = list(flatten(pendata))
        if not data:
            print(f'{filename}: no pen data.')
            return

        f = StrokeFile(data)
        # Spark doesn't have timestamps in the strokes, so use the file
        # timestamp itself
        timestamp = f.timestamp or yml['time']
        # gotta convert to Drawings, then to json string, then to json, then
        # to svg. ffs.
        svgname = f'{stem}.svg'
        pngname = f'{stem}.png'
        jsonname = f'{stem}.json'
        d = Drawing(svgname, (width * point_size, height * point_size), timestamp)

        def normalize(p):
            NORMALIZED_RANGE = 0x10000
            return NORMALIZED_RANGE * p / pressure

        for s in f.strokes:
            stroke = d.new_stroke()
            for p in s.points:
                stroke.new_abs((p.x * point_size, p.y * point_size), normalize(p.p))
            stroke.seal()
        d.seal()
        if file_format == 'json':
            with open(jsonname, 'w') as fd:
                fd.write(d.to_json())
            return
        else:
            from io import StringIO
            js = json.load(StringIO(d.to_json()))
            if file_format == 'svg':
                JsonSvg(js, orientation, d.name)
            elif file_format == 'png':
                JsonPng(js, orientation, pngname)


def fetch_files():
    import xdg.BaseDirectory
    basedir = Path(xdg.BaseDirectory.xdg_data_home, 'tuhi')

    return [f for f in basedir.rglob('raw/*.yaml')]


def main(args=sys.argv):
    long_description = '''
    This tool is primarily a debugging tool but can be used to recover
    "lost" files. Use this tool if Tuhi failed to convert a drawing
    after downloading it from the device. Obviously after fixing the bug
    that failed to convert it.

    Input data is a raw log file. These are usually stored in
    \t$XDG_DATA_HOME/tuhi/<bluetooth address>/raw/

    Pass the log file to this tool and it will convert it to a JSON file or
    an SVG file. Alternatively, use --all to convert all
    all log files containing pen data in the above directory.

    Files are placed in $CWD and use file names containing the file time
    for easier identification.

    Copying the JSON files into the $XDG_DATA_HOME/tuhi/ will make them
    appear in the GUI.
    '''.replace('    ', '')

    parser = argparse.ArgumentParser(description='Converter tool from raw Tuhi log files to SVG and Tuhi JSON files.',
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=long_description)
    parser.add_argument('filename', help='The YAML file to load', nargs='?')
    parser.add_argument('--verbose',
                        help='Show some debugging informations',
                        action='store_true',
                        default=False)
    parser.add_argument('--all',
                        help='Convert all files in $XDG_DATA_DIR/tuhi/',
                        action='store_true',
                        default=False)
    parser.add_argument('--orientation',
                        help='The orientation of the tablet. Default: the tablet model\'s default',
                        default=None,
                        choices=['landscape', 'portrait', 'reverse-landscape', 'reverse-portrait'])
    parser.add_argument('--tablet-model',
                        help='Use defaults from the given tablet model',
                        default='intuos-pro',
                        choices=['intuos-pro', 'slate', 'spark'])
    parser.add_argument('--format',
                        help='The format to generate. Default: svg',
                        default='svg',
                        choices=['svg', 'png', 'json'])

    ns = parser.parse_args(args[1:])
    if ns.verbose:
        logger.setLevel(logging.DEBUG)

    if not ns.all:
        if ns.filename is None:
            print('filename is required, or use --all', file=sys.stderr)
            sys.exit(1)
        files = [ns.filename]
    else:
        files = fetch_files()

    model_map = {
        'intuos-pro': WacomProtocolIntuosPro,
        'slate': WacomProtocolSlate,
        'spark': WacomProtocolSpark,
    }
    for f in files:
        parse_file(f, ns.format, model_map[ns.tablet_model], ns.orientation)


if __name__ == '__main__':
    main()
