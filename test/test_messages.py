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

import calendar
import os
import sys
import unittest
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + '/..')  # noqa

from tuhi.protocol import *


SUCCESS = NordicData([0xb3, 0x1, 0x00])


class TestUtils(unittest.TestCase):
    def test_hex_string(self):
        values = [
            ([0x00, 0x12], '00 12'),
            ([0x00], '00'),
            ([0xab], 'ab'),
            ([0x00, 0x12, 0xab, 0xdf], '00 12 ab df'),
            ((16).to_bytes(1, byteorder='little'), '10'),
            ((1024).to_bytes(2, byteorder='little'), '00 04'),
            ([], '')
        ]

        for v in values:
            self.assertEqual(as_hex_string(v[0]), v[1])

        with self.assertRaises(ValueError):
            as_hex_string(1)

        with self.assertRaises(ValueError):
            as_hex_string('0x00')

    def test_protocol_version(self):
        values = [
            ('INTUOS_PRO', ProtocolVersion.INTUOS_PRO),
            ('intuos_pro', ProtocolVersion.INTUOS_PRO),
            ('intuos-pro', ProtocolVersion.INTUOS_PRO),
            ('SLATE', ProtocolVersion.SLATE),
            ('slate', ProtocolVersion.SLATE),
            ('SPARK', ProtocolVersion.SPARK),
            ('spark', ProtocolVersion.SPARK),
        ]

        for v in values:
            self.assertEqual(ProtocolVersion.from_string(v[0]), v[1])

        # No real reason we couldn't support those but right now they
        # aren't, so let's test for it.
        with self.assertRaises(ValueError):
            ProtocolVersion.from_string('Slate')

        with self.assertRaises(ValueError):
            ProtocolVersion.from_string('IntuosPro')


class TestProtocolAny(unittest.TestCase):
    protocol_version = ProtocolVersion.ANY

    def test_get_protocol(self):
        self.assertIsNotNone(Protocol(self.protocol_version, callback=None))

    def test_has_all_messages(self):
        p = Protocol(self.protocol_version, callback=None)
        for m in Interactions:
            # Some messages expect an argument and fail, that's fine for
            # this test. We're looking for KeyErrors here if a message
            # doesn't exist so we try each message with one of the likely
            # arguments that will pass
            args = [None, '101010', [0x12], Mode.LIVE]
            for arg in args:
                try:
                    if arg is None:
                        p.get(m)
                    else:
                        p.get(m, arg)
                except TypeError:
                    pass
                except ValueError:
                    pass
                else:
                    break

    def test_connect(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xe6)
            self.assertEqual(request.length, 6)
            return SUCCESS

        if cb is None:
            cb = _cb

        p = Protocol(self.protocol_version, callback=cb)
        with self.assertRaises(TypeError):
            p.execute(Interactions.CONNECT)  # missing argument

        uuid = 'abcdef123456'
        msg = p.execute(Interactions.CONNECT, uuid)
        self.assertEqual(msg.uuid, uuid)

        with self.assertRaises(ValueError):
            p.execute(Interactions.CONNECT, 'too-long-an-id')

        with self.assertRaises(binascii.Error):
            uuid = 'uvwxyz123456'
            p.execute(Interactions.CONNECT, uuid)

    def test_get_name(self, cb=None, name='test dev name'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xbb)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            return NordicData([0xbc, len(name)] + list(bytes(name, encoding='ascii')))

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_NAME)
        self.assertEqual(msg.name, name)

    def test_set_name(self, cb=None, name='test dev name'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xbb)
            self.assertEqual(request.length, len(name) + 1)
            self.assertEqual(request[-1], 0xa)  # spark needs a trailing linebreak
            self.assertEqual(bytes(request[:-1]).decode('utf-8'), name)
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.SET_NAME, name=name)

    def test_get_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xb6)
            self.assertEqual(request.length, 1)
            t = time.strftime('%y%m%d%H%M%S', time.gmtime(ts))
            t = [int(i) for i in binascii.unhexlify(t)]
            return NordicData([0xbd, len(t)] + t)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_TIME)
        self.assertEqual(msg.timestamp, int(ts))

    def test_set_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xb6)
            self.assertEqual(request.length, 6)
            str_timestamp = ''.join([f'{b:02x}' for b in request])
            t = calendar.timegm(time.strptime(str_timestamp, '%y%m%d%H%M%S'))
            self.assertEqual(int(t), int(ts))
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.SET_TIME, timestamp=ts)

    def test_get_fw(self, cb=None, fw='abcdef-123456'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xb7)
            self.assertEqual(request.length, 1)
            data = [int(c, 16) for c in fw.split('-')[request[0]]]
            return NordicData([0xb8, len(data) + 1, 0x00] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_FIRMWARE)
        self.assertEqual(msg.firmware, fw)


class TestProtocolSpark(TestProtocolAny):
    protocol_version = ProtocolVersion.SPARK


class TestProtocolSlate(TestProtocolAny):
    protocol_version = ProtocolVersion.SLATE


class TestProtocolIntuosPro(TestProtocolAny):
    protocol_version = ProtocolVersion.INTUOS_PRO

    def test_connect(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xe6)
            self.assertEqual(request.length, 6)
            return NordicData([0x50, 0x06] + request)  # replies with the uuid

        super().test_connect(cb or _cb)

    def test_get_name(self, cb=None, name='test dev name'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xdb)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            return NordicData([0xbc, len(name)] + list(bytes(name, encoding='ascii')))

        super().test_get_name(cb or _cb, name=name)

    def test_set_name(self, cb=None, name='test dev name'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xdb)
            self.assertEqual(request.length, len(name))
            self.assertEqual(bytes(request).decode('utf-8'), name)
            return SUCCESS

        super().test_set_name(cb or _cb, name=name)

    def test_get_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xd6)
            self.assertEqual(request.length, 1)
            t = list(int(ts).to_bytes(length=4, byteorder='little')) + [0x00, 0x00]
            return NordicData([0xbd, len(t)] + t)

        super().test_get_time(cb or _cb, ts=ts)

    def test_set_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xb6)
            self.assertEqual(request.length, 6)
            t = int.from_bytes(request[0:4], byteorder='little')
            self.assertEqual(int(t), int(ts))
            return SUCCESS

        super().test_set_time(cb or _cb, ts=ts)

    def test_get_fw(self, cb=None, fw='anything-string'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xb7)
            self.assertEqual(request.length, 1)
            data = bytes(fw.split('-')[request[0]].encode('utf8'))
            return NordicData([0xb8, len(data) + 1, 0x00] + list(data))

        super().test_get_fw(cb or _cb, fw=fw)


if __name__ == "__main__":
    unittest.main(sys.argv[1:])
