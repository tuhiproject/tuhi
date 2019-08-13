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

    def test_get_battery(self, cb=None, battery=(1, 78)):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xb9)
            self.assertEqual(request.length, 1)
            return NordicData([0xba, 2, battery[1], battery[0]])

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_BATTERY)
        self.assertEqual(msg.battery_is_charging, battery[0])
        self.assertEqual(msg.battery_percent, battery[1])

    def test_get_width(self, cb=None, width=1234):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xea)
            self.assertEqual(request.length, 2)
            self.assertEqual(request[0], 3)

            data = [0x03, 0x00] + list(width.to_bytes(4, byteorder='little'))
            return NordicData([0xeb, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_WIDTH)
        self.assertEqual(msg.width, width)

    def test_get_height(self, cb=None, width=4321):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xea)
            self.assertEqual(request.length, 2)
            self.assertEqual(request[0], 4)

            data = [0x04, 0x00] + list(width.to_bytes(4, byteorder='little'))
            return NordicData([0xeb, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_HEIGHT)
        self.assertEqual(msg.height, width)

    def test_unknown_e3(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xe3)
            self.assertEqual(request.length, 1)
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.UNKNOWN_E3)

    def test_filetransfer_reporting_type(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xec)
            self.assertEqual(request.length, 6)
            self.assertEqual(request, [0x06, 0x00, 0x00, 0x00, 0x00, 0x00])
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.SET_FILE_TRANSFER_REPORTING_TYPE)

    def test_set_mode(self, cb=None):
        for mode in Mode:
            mode = Mode.LIVE

            def _cb(request, requires_reply=True, userdata=None, timeout=5):
                self.assertEqual(request.opcode, 0xb1)
                self.assertEqual(request.length, 1)
                self.assertEqual(request[0], mode)
                return SUCCESS

            cb = cb or _cb

            p = Protocol(self.protocol_version, callback=cb)
            p.execute(Interactions.SET_MODE, mode)

    def test_get_strokes(self, cb=None, count=1024, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            # this is a weird double call, see the protocol
            # We reply 0xc7 first, and then 0xcd
            if request is not None:
                self.assertEqual(request.opcode, 0xc5)
                self.assertEqual(request.length, 1)
                self.assertEqual(request[0], 0x00)
                data = list(count.to_bytes(4, byteorder='little'))
                return NordicData([0xc7, len(data)] + data)
            else:
                t = time.strftime('%y%m%d%H%M%S', time.gmtime(ts))
                data = [int(i) for i in binascii.unhexlify(t)]
                return NordicData([0xcd, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_STROKES)
        self.assertEqual(msg.count, count)
        self.assertEqual(msg.timestamp, int(ts))

    def test_get_data_available(self, cb=None, ndata=1234):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xc1)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            data = list(ndata.to_bytes(2, byteorder='big'))
            return NordicData([0xc2, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_DATA_AVAILABLE)
        self.assertEqual(msg.count, ndata)

    def test_start_reading(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xc3)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            return NordicData([0xc8, 1, 0xbe])

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.START_READING)

    def test_ack_transaction(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xca)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            # no reply

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.ACK_TRANSACTION)

    def test_register_complete(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xe5)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.REGISTER_COMPLETE)

    def test_register_press_button(self, cb=None, uuid=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xe3)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x01)
            # no reply

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.REGISTER_PRESS_BUTTON, uuid=uuid)
        self.assertEqual(msg.uuid, uuid)


class TestProtocolSpark(TestProtocolAny):
    protocol_version = ProtocolVersion.SPARK

    def test_register_wait_for_button(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertIsNone(request)
            return NordicData([0xe4, 0x00])

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.REGISTER_WAIT_FOR_BUTTON)
        self.assertEqual(msg.protocol_version, self.protocol_version)


class TestProtocolSlate(TestProtocolSpark):
    protocol_version = ProtocolVersion.SLATE

    def test_get_strokes(self, cb=None, count=1024, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xcc)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            c = list(count.to_bytes(4, byteorder='little'))
            t = time.strftime('%y%m%d%H%M%S', time.gmtime(ts))
            t = [int(i) for i in binascii.unhexlify(t)]
            data = c + t
            return NordicData([0xcf, len(data)] + data)

        super().test_get_strokes(cb or _cb, count=count, ts=ts)

    def test_get_data_available(self, cb=None, ndata=1234):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xc1)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            data = list(ndata.to_bytes(2, byteorder='little'))
            return NordicData([0xc2, len(data)] + data)

        super().test_get_data_available(cb or _cb, ndata=ndata)

    def test_ack_transaction(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xca)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            return SUCCESS

        super().test_ack_transaction(cb or _cb)

    def test_register_press_button(self, cb=None, uuid='abcdef123456'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xe7)
            self.assertEqual(request.length, 6)
            # no reply

        super().test_register_press_button(cb or _cb, uuid)

    def test_register_wait_for_button(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertIsNone(request)
            return NordicData([0xe4, 0x00])

        super().test_register_wait_for_button(cb or _cb)


class TestProtocolIntuosPro(TestProtocolSlate):
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

    def test_get_strokes(self, cb=None, count=1024, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertEqual(request.opcode, 0xcc)
            self.assertEqual(request.length, 1)
            self.assertEqual(request[0], 0x00)
            c = list(count.to_bytes(4, byteorder='little'))
            t = list(int(ts).to_bytes(4, byteorder='little'))
            data = c + t
            return NordicData([0xcf, len(data)] + data)

        super().test_get_strokes(cb or _cb, count=count, ts=ts)

    def test_register_wait_for_button(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            self.assertIsNone(request)
            return NordicData([0x53, 0x00])

        super().test_register_wait_for_button(cb or _cb)


if __name__ == "__main__":
    unittest.main(sys.argv[1:])
