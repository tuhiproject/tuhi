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

import os
import pytest
import sys
import xdg.BaseDirectory
from pathlib import Path
import yaml
import logging

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + '/..')  # noqa

from tuhi.protocol import *  # noqa
from tuhi.util import flatten  # noqa

logger = logging.getLogger('tuhi')  # piggyback the debug messages
logger.setLevel(logging.DEBUG)


def pytest_generate_tests(metafunc):
    # for any test function that takes a "logfile" argument return the list
    # of all current logfiles in XDG_DATA_HOME/tuhi
    # This means the test gets better the more logfiles are present on the
    # user's machine.
    if 'logfile' in metafunc.fixturenames:
        basedir = Path(xdg.BaseDirectory.xdg_data_home) / 'tuhi'

        def loads_and_has_data(filename):
            with open(filename) as fd:
                try:
                    yml = yaml.load(fd, Loader=yaml.Loader)
                    return yml is not None
                except Exception as e:
                    logger.error(f'Exception triggered by file {filename}')
                    raise e

        logfiles = [f for f in basedir.glob('**/raw/log-*.yaml') if loads_and_has_data(f)]
        metafunc.parametrize('logfile', logfiles)


def test_log_files(logfile):
    def load_pen_data(filename):
        with open(filename) as fd:
            yml = yaml.load(fd, Loader=yaml.Loader)
            # all recv lists that have source PEN
            pendata = [d['recv'] for d in yml['data'] if 'recv' in d and 'source' in d and d['source'] == 'PEN']
        return list(flatten(pendata))

    data = load_pen_data(logfile)
    if not data:  # Recordings without Pen data can be skipped
        pytest.skip('Recording without pen data')
    StrokeFile(data)


class TestStrokeParsers(object):
    def test_identify_file_header(self):
        data = [0x67, 0x82, 0x69, 0x65]
        assert StrokeDataType.identify(data) == StrokeDataType.FILE_HEADER
        data = [0x62, 0x38, 0x62, 0x74]
        assert StrokeDataType.identify(data) == StrokeDataType.FILE_HEADER

        others = [
            # with header
            [0xff, 0x62, 0x38, 0x62, 0x74],
            [0xff, 0x67, 0x82, 0x69, 0x65],
            # wrong size
            [0x67, 0x82, 0x69],
            [0x67, 0x82],
            [0x67],
            [0x62, 0x38, 0x62],
            [0x62, 0x38],
            [0x62],
            # wrong numbers
            [0x67, 0x82, 0x69, 0x64],
            [0x62, 0x38, 0x62, 0x73],
        ]
        for data in others:
            assert StrokeDataType.identify(data) != StrokeDataType.FILE_HEADER, data

    def test_identify_stroke_header(self):
        data = [0xff, 0xfa]  # two bytes are enough to identify
        assert StrokeDataType.identify(data) == StrokeDataType.STROKE_HEADER

        data = [0x3, 0xfa]  # lowest bits set, not a correct packet but identify doesn't care
        assert StrokeDataType.identify(data) == StrokeDataType.STROKE_HEADER

        data = [0xfc, 0xfa]  # lowest bits unset, must be something else
        assert StrokeDataType.identify(data) != StrokeDataType.STROKE_HEADER

    def test_identify_stroke_point(self):
        data = [0xff, 0xff, 0xff]  # three bytes are enough to identify
        assert StrokeDataType.identify(data) == StrokeDataType.POINT

        data = [0xff, 0xff, 0xff, 1, 2, 3, 4, 5, 6]
        assert StrokeDataType.identify(data) == StrokeDataType.POINT

        # wrong header, but observed in the wild
        data = [0xbf, 0xff, 0xff, 1, 2, 3, 4, 5, 6]
        assert StrokeDataType.identify(data) == StrokeDataType.POINT

        data = [0xfc, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]  # stroke end
        assert StrokeDataType.identify(data) != StrokeDataType.POINT

        data = [0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]  # EOF
        assert StrokeDataType.identify(data) != StrokeDataType.POINT

    def test_identify_stroke_lost_point(self):
        data = [0xff, 0xdd, 0xdd]
        assert StrokeDataType.identify(data) == StrokeDataType.LOST_POINT

    def test_identify_eof(self):
        data = [0xff] * 9
        assert StrokeDataType.identify(data) == StrokeDataType.EOF

    def test_identify_stroke_end(self):
        data = [0xfc, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]
        assert StrokeDataType.identify(data) == StrokeDataType.STROKE_END

    def test_identify_delta(self):
        for i in range(256):
            data = [i, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6]
            if i & 0x3 == 0:
                assert StrokeDataType.identify(data), StrokeDataType.DELTA == f'packet: {data}'
            else:
                assert StrokeDataType.identify(data), StrokeDataType.DELTA != f'packet: {data}'

    def test_parse_stroke_header(self):
        F_NEW_LAYER = 0x40
        F_PEN_ID = 0x80
        pen_type = 3
        flags = F_NEW_LAYER | pen_type

        data = [0xff, 0xfa, flags, 0x1f, 0x73, 0x53, 0x5d, 0x2e, 0x01]
        packet = StrokeHeader(data)
        assert packet.size == 9
        assert packet.is_new_layer == 1
        assert packet.pen_id == 0
        assert packet.pen_type == pen_type
        assert packet.timestamp == 1565750047

        # new layer off
        flags = pen_type
        data = [0xff, 0xfa, flags, 0x1f, 0x73, 0x53, 0x5d, 0x2e, 0x01]
        packet = StrokeHeader(data)
        assert packet.size == 9
        assert packet.is_new_layer == 0
        assert packet.pen_id == 0
        assert packet.pen_type == pen_type
        assert packet.timestamp == 1565750047

        # pen type change
        pen_type = 1
        flags = F_NEW_LAYER | pen_type
        data = [0xff, 0xfa, flags, 0x1f, 0x73, 0x53, 0x5d, 0x2e, 0x01]
        packet = StrokeHeader(data)
        assert packet.size == 9
        assert packet.is_new_layer == 1
        assert packet.pen_id == 0
        assert packet.pen_type == pen_type
        assert packet.timestamp == 1565750047

        # with pen id
        flags = F_NEW_LAYER | F_PEN_ID | pen_type
        pen_id = [0xff, 0x0a, 0x87, 0x75, 0x80, 0x28, 0x42, 0x00, 0x10]
        data = [0xff, 0xfa, flags, 0x1f, 0x73, 0x53, 0x5d, 0x2e, 0x01] + pen_id
        packet = StrokeHeader(data)
        assert packet.size == 18
        assert packet.is_new_layer == 1
        assert packet.pen_id == 0x100042288075870a
        assert packet.pen_type == pen_type
        assert packet.timestamp == 1565750047

    def test_parse_stroke_point(self):
        # 0xff means 2 bytes each for abs coords
        data = [0xff, 0xff, 0xff, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6]
        packet = StrokePoint(data)
        assert packet.size == 9
        assert packet.x == 0x0201
        assert packet.y == 0x0403
        assert packet.p == 0x0605
        assert packet.dx is None
        assert packet.dy is None
        assert packet.dp is None

        # 0xbf means: 1 byte for pressure delta, i.e. the 0x6 is skipped
        data = [0xbf, 0xff, 0xff, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6]
        packet = StrokePoint(data)
        assert packet.size == 8
        assert packet.x == 0x0201
        assert packet.y == 0x0403
        assert packet.p is None
        assert packet.dx is None
        assert packet.dy is None
        assert packet.dp == 0x5

    def test_parse_lost_point(self):
        data = [0xff, 0xdd, 0xdd, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6]
        packet = StrokeLostPoint(data)
        assert packet.size == 9
        assert packet.nlost == 0x0201

    def test_parse_eof(self):
        data = [0xff] * 9
        packet = StrokeEOF(data)
        assert packet.size == 9

        data = [0xfc] + [0xff] * 6
        packet = StrokeEOF(data)
        assert packet.size == 7

    def test_parse_delta(self):
        x_delta = 0b00001000  # noqa
        x_abs   = 0b00001100  # noqa
        y_delta = 0b00100000  # noqa
        y_abs   = 0b00110000  # noqa
        p_delta = 0b10000000  # noqa
        p_abs   = 0b11000000  # noqa

        flags = x_delta
        data = [flags, 1]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.dx == 1
        assert packet.dy is None
        assert packet.dp is None
        assert packet.x is None
        assert packet.y is None
        assert packet.p is None

        flags = y_delta
        data = [flags, 2]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.dx is None
        assert packet.dy == 2
        assert packet.dp is None
        assert packet.x is None
        assert packet.y is None
        assert packet.p is None

        flags = p_delta
        data = [flags, 3]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.dx is None
        assert packet.dy is None
        assert packet.dp == 3
        assert packet.x is None
        assert packet.y is None
        assert packet.p is None

        flags = x_delta | p_delta
        data = [flags, 3, 5]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.dx == 3
        assert packet.dy is None
        assert packet.dp == 5
        assert packet.x is None
        assert packet.y is None
        assert packet.p is None

        flags = x_delta | y_delta | p_delta
        data = [flags, 3, 5, 7]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.dx == 3
        assert packet.dy == 5
        assert packet.dp == 7
        assert packet.x is None
        assert packet.y is None
        assert packet.p is None

        flags = x_abs | y_abs | p_abs
        data = [flags, 1, 2, 3, 4, 5, 6]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.x == 0x0201
        assert packet.y == 0x0403
        assert packet.p == 0x0605
        assert packet.dx is None
        assert packet.dy is None
        assert packet.dp is None

        flags = y_abs
        data = [flags, 2, 3]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.x is None
        assert packet.y == 0x0302
        assert packet.p is None
        assert packet.dx is None
        assert packet.dy is None
        assert packet.dp is None

        flags = x_abs | y_delta | p_delta
        data = [flags, 2, 3, 4, 5]
        packet = StrokeDelta(data)
        assert packet.size == len(data)
        assert packet.x == 0x0302
        assert packet.y is None
        assert packet.p is None
        assert packet.dx is None
        assert packet.dy == 4
        assert packet.dp == 5


class TestStrokes(object):
    def test_single_stroke(self):
        data = '''
            67 82 69 65 22 73 53 5d    00 00 02 00 00 00 00 00    ff fa c3 1f
            73 53 5d 2e 01 ff 0a 87    75 80 28 42 00 10 ff ff    ff 41 3c 13
            30 72 03 c8 01 cb 04 e8    ff 01 0f 06 e0 ff 5f 07    e0 ff 91 08
            c0 78 09 e8 02 01 2f 0a    e8 fe 01 ce 0a e0 ff 55    0b e8 01 01
            dc 0b c8 fe 6f 0c a8 03    ff 75 a8 fe 02 f4 a8 02    ff 06 88 ff
            ee 88 01 f1 80 fd 88 ff    f4 88 01 f4 a8 fe ff f7    a8 01 01 fa
            88 ff f7 80 f4 a8 01 01    f3 88 ff 01 a8 ff ff fd    a0 03 f4 80
            d3 a0 02 df a0 02 be a8    fe 02 b2 a0 02 c7 e8 ff    02 8e 0a e8
            fe 01 15 08 e8 01 03 91    04 e8 f3 26 94 01 ff fa    03 21 73 53
            5d 46 02 ff ff ff d3 6f    5a 38 c0 03 e8 fb 2b 5c    04 a8 fa 2c
            78 a8 02 ff 4e a8 01 ff    0c a0 fd be 88 02 d6 a8    ff fe f7 a8
            ff ff d3 a0 01 fd a8 01    ff 15 88 fd 15 a0 ff d9    80 fd 88 fe
            f4 a8 01 ff f1 a8 ff fe    fd 80 09 a8 fe fc 03 88    01 03 a8 ff
            ff 1e a8 ff ff c6 88 01    1c a8 ff ff f7 a8 02 01    ee 28 01 fe
            a8 01 ff fd 88 03 f4 a8    ff ff 0b a8 01 fe ff 80    f6 80 0c a0
            ff f1 a8 ff 01 0f 88 01    02 a8 01 fe 10 a8 fe 01    05 88 01 e9
            88 fe e2 a0 02 1e a0 02    0c a8 ff ff f4 a8 01 02    fd a8 ff fe
            ee 80 ee a8 01 ff 03 28    ff fe 80 09 88 01 06 a8    ff fe eb a8
            02 01 29 88 ff 01 a0 01    02 a8 01 ff fe a8 ff 01    f6 80 0a 88
            02 03 08 ff 88 01 33 a8    01 ff 09 a0 01 24 a8 01    01 fd a0 ff
            df a0 02 09 a0 02 0c a8    ff 02 f4 a8 ff 03 03 a8    01 02 f1 88
            fe 0f a0 01 eb 80 06 a8    ff 01 f1 28 fe 02 88 01    09 a8 ff 01
            03 a8 ff 01 f4 a8 02 ff    0f a0 01 09 88 02 eb a8    ff ff fa a8
            01 ff d6 a8 ff ff ee a8    ff fd c4 a0 fe dc a8 01    fd 12 a8 01
            fd c4 a8 02 fd dc a8 01    fd a6 a0 fc 94 e8 ff fc    8a 06 fc ff
            ff ff ff ff ff
        '''
        b = [d.strip() for d in data.split(' ') if d not in ['', '\n']]
        b = [int(x, 16) for x in b]

        p = Protocol(ProtocolVersion.INTUOS_PRO, None, None)
        p.parse_pen_data(b)

    def test_double_stroke(self):
        data = '''
            67 82 69 65 28 c7 53 5d    00 00 02 00 00 00 00 00    ff fa c3 26
            c7 53 5d a8 01 ff 0a 87    75 80 28 42 00 10 ff ff    ff f6 29 da
            1d a4 04 e0 02 0c 06 e0    04 b7 06 e0 04 47 07 e8    01 08 2e 08
            e0 09 06 09 e0 09 ab 09    e8 01 0a 4d 0a a8 ff 0b    72 a0 0b 06
            a0 05 e5 a8 ff 05 f7 a8    02 01 15 a8 fe 01 d6 a0    ff e5 a8 01
            fe 15 a8 ff fe f7 a8 02    fd e5 a8 01 fe eb a8 01    fe ff a0 fd
            ff a8 ff fd 01 a8 02 fd    e6 a8 fd fd 18 a0 fd d9    a0 ff dc a8
            fd fc 04 a8 01 fe 49 28    ff fc a0 fc ff a0 fa ed    a8 01 f9 12
            a8 fe f9 03 a8 01 f8 fd    a8 01 fa d0 a0 fd b5 a8    01 fd d9 a0
            fd bb e8 ff f9 12 08 e8    ff cc 3b 03 ff fa 03 26    c7 53 5d 6d
            00 ff ff ff 42 2f fb 1c    65 0a e0 fd f1 0b e8 ff    fd b7 0c a8
            02 03 75 a0 04 09 a0 05    18 a8 03 0a 15 a8 01 0d    eb a8 03 0e
            d0 a8 ff 0f d0 a8 ff 0d    12 a0 0b e2 a8 fd 08 fa    28 ff 07 a8
            ff 05 f1 20 3a a8 01 02    0c a8 f6 03 f4 28 01 c5    a8 05 fa 0f
            a8 02 c8 f7 a0 fc fd a0    fe fa a8 02 24 ee a8 ff    f6 fe a8 02
            f6 f3 a8 ff f6 d9 a0 f7    ee a0 f6 d0 a8 ff f9 e2    a0 fb f1 a8
            ff fa dc e8 01 fd 2a 0d    e8 ff f9 57 0a e8 fa e7    9c 04 fc ff
            ff ff ff ff ff
        '''
        b = [d.strip() for d in data.split(' ') if d not in ['', '\n']]
        b = [int(x, 16) for x in b]

        p = Protocol(ProtocolVersion.INTUOS_PRO, None, None)
        p.parse_pen_data(b)

    def test_quint_stroke(self):
        data = '''
            67 82 69 65 cc ce 53 5d    00 00 05 00 00 00 00 00    ff fa c3 c7
            ce 53 5d 8d 00 ff 0a 87    75 80 28 42 00 10 ff ff    ff 95 29 a9
            1e 23 06 e0 01 a0 07 e8    ff ff db 08 e8 01 01 e9    09 e0 ff bb
            0a e0 01 81 0b c0 1a 0c    80 7b a0 02 f1 a8 ff 03    09 a8 ff 03
            18 a0 04 e2 a8 fd 02 03    a8 02 03 df a8 fe 03 f7    a0 03 0c a8
            ff 06 e2 a0 03 e8 a8 01    03 f4 a8 01 03 ee a8 01    01 fe a0 03
            d8 a8 01 03 c7 a0 02 fd    a8 01 03 06 a8 ff 01 f7    a8 ff 02 1b
            08 ff a8 ff 03 1e a0 02    09 a0 03 15 a8 fe 05 fa    a8 ff 02 18
            a0 04 10 a8 ff 01 f0 80    fa a0 ff 06 a0 fe 0f a0    fc f1 a8 01
            fc 01 28 02 fa a8 01 f8    17 a8 01 f9 e8 28 03 f9    28 01 f9 28
            ff f9 a0 f9 02 a0 fa ff    a0 fb ff a8 01 fb e9 a8    01 fa c3 a8
            01 f9 91 e0 f8 cc 0a e8    05 c4 76 06 ff fa 03 c8    ce 53 5d 10
            02 ff ff ff bc 36 40 1e    00 08 e8 f2 26 14 09 e8    02 0d d7 09
            e8 01 0b 7c 0a a0 0b 69    a0 0a 51 a8 ff 06 f1 a8    ff 07 e8 a8
            fe 03 e5 a8 f7 35 eb 88    ff fa a8 10 99 f7 20 01    28 f8 2f a8
            ff fe d6 a8 01 fa eb 28    01 fb 28 02 fa 28 03 fc    a8 02 fa eb
            28 03 fc a8 02 f8 df a8    03 fb f4 a8 01 f9 d6 a8    02 f9 b8 a8
            02 f7 03 a0 f8 94 e8 02    f7 a3 0a e0 f9 bd 06 e8    0a eb 05 02
            ff fa 03 c8 ce 53 5d 5b    00 ff ff ff 0a 40 19 1e    5b 05 e8 fe
            0d b7 06 e8 fd 0e b3 07    e8 ff 07 88 08 e0 07 2d    09 a0 06 54
            a0 06 75 a8 ff 04 18 a0    05 e8 a8 ff 03 d0 a8 fe    01 fd a8 01
            02 dc a8 fe 02 ee a0 ff    fa 80 f4 a8 ff fe fd a8    01 ff df a8
            01 fe df a0 fd fa a8 03    ff fd a0 fd 0c a8 01 fd    f4 a8 01 fd
            f1 a0 fc f4 a8 01 fe af    a0 fc b8 a8 02 fb c1 e0    fb 64 0b e8
            01 fa b3 07 e8 03 0b 18    02 ff fa 03 c9 ce 53 5d    b2 02 ff ff
            ff dc 46 82 1d 44 06 e8    fe 1b da 06 e8 ff 08 67    07 e8 ff 05
            ee 07 e8 01 08 81 08 a8    fe 06 7e a8 03 06 42 a8    fe 07 12 a8
            01 04 cd a8 ff 04 d0 a8    fe 03 c4 a8 ff 01 d0 88    ff 21 a8 01
            fe fd a8 01 fd 0c a8 01    fb fd a8 02 fa d9 a8 01    fc fd a8 01
            fa e5 a0 fb fa a8 01 fb    dc a8 01 f9 f1 e8 ff fa    be 0a e0 fa
            41 09 e8 ff fa 3d 07 e8    ff f9 00 05 ff fa 03 c9    ce 53 5d a9
            00 ff ff ff 0b 1d ae 23    e4 03 e8 21 fc b6 04 e8    20 fb 3a 05
            c8 06 09 06 e8 01 ff 02    07 e8 02 ff d1 07 88 02    63 a0 fe 06
            88 03 e5 a8 04 fe d9 a8    04 ff 1e a8 06 fe f4 a8    04 ff e5 a8
            39 f2 06 88 09 36 a8 0b    fc dc a8 c9 0a 03 88 02    f4 a8 03 03
            27 a8 05 f8 d3 a8 0a 05    12 a8 03 f9 c7 88 07 18    a8 06 07 f2
            a8 fe f8 f8 88 0b 1e a8    04 01 e0 a8 10 ff fd a8    fd fd 03 a8
            05 03 0c a8 09 fb f6 88    06 fc a8 01 02 02 a8 ff    fa df a8 07
            03 09 a8 0a ff 09 88 02    df a8 f9 04 1b a8 04 ff    f4 a8 01 08
            21 a8 fe f8 fd a8 fd 07    03 a8 05 ff fd a8 02 ff    e8 a8 05 ff
            18 a8 fd 01 03 28 01 fd    a8 02 03 15 a8 f9 04 f1    a8 ff fb fa
            a0 02 e2 a8 09 ff 15 a8    f9 01 09 88 fc 1b 88 01    e8 a8 fb 01
            30 28 09 04 a8 f8 f9 06    a8 07 01 f1 a8 fb 02 0c    28 fe fe a8
            ff 01 24 a0 fe f4 a8 f5    03 f4 a8 01 0a f7 a8 fb    f5 d3 a0 ff
            09 a8 05 03 03 a8 fa 02    1b a8 fc fe ee a8 fd 02    eb a0 fe f6
            a8 f8 09 22 a8 ff f9 dc    28 fd fe a8 fe 04 f1 a8    03 ff 06 a8
            f3 03 fd a8 fa 03 f1 a8    f6 ff 03 a8 f9 03 ee a8    fb 02 e5 a8
            f4 05 dc a8 fa 06 03 a8    f1 fc d6 a8 f4 08 df a8    cd 03 c1 e8
            fb 01 d1 08 e8 fd 01 58    06 e8 67 0b 8b 02 fc ff    ff ff ff ff
            ff
        '''
        b = [d.strip() for d in data.split(' ') if d not in ['', '\n']]
        b = [int(x, 16) for x in b]

        p = Protocol(ProtocolVersion.INTUOS_PRO, None, None)
        p.parse_pen_data(b)
