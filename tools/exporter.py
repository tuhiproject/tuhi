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

from pathlib import Path
import argparse
import json
import os
import sys

# This tool isn't installed, so we can assume that the tuhi module is always
# in the parent directory
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + '/..')  # noqa
from tuhi.export import JsonSvg, JsonPng

parser = argparse.ArgumentParser(description='Converter tool from Tuhi JSON files to SVG or PNG.')
parser.add_argument('filename', help='The JSON file to export ($HOME/.local/share/tuhi/*.json)')
parser.add_argument('--format',
                    help='The format to generate. Default: svg',
                    default='svg',
                    choices=['svg', 'png'])
parser.add_argument('--output',
                    type=str,
                    help='The output file name. Default: "$PWD/inputfile.suffix"',
                    default=None)
parser.add_argument('--orientation',
                    help='The orientation of the image',
                    default='landscape',
                    choices=['landscape', 'portrait', 'reverse-landscape', 'reverse-portrait'])

ns = parser.parse_args()

if ns.output is None:
    ns.output = f"{Path(ns.filename).stem}.{ns.format}"

js = json.load(open(ns.filename))
if ns.format == 'svg':
    JsonSvg(js, ns.orientation, ns.output)
elif ns.format == 'png':
    JsonPng(js, ns.orientation, ns.output)
