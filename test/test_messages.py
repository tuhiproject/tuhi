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
import pytest
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + '/..')  # noqa

from tuhi.protocol import *  # noqa


SUCCESS = NordicData([0xb3, 0x1, 0x00])


class TestUtils(object):
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
            assert as_hex_string(v[0]) == v[1]

        with pytest.raises(ValueError):
            as_hex_string(1)

        with pytest.raises(ValueError):
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
            assert ProtocolVersion.from_string(v[0]) == v[1]

        # No real reason we couldn't support those but right now they
        # aren't, so let's test for it.
        with pytest.raises(ValueError):
            ProtocolVersion.from_string('Slate')

        with pytest.raises(ValueError):
            ProtocolVersion.from_string('IntuosPro')

    def test_little_u16(self):
        values = [
            (1, [0x01, 0x00]),
            (256, [0x00, 0x01]),
        ]

        for v in values:
            assert little_u16(v[0]) == bytes(v[1])
            assert little_u16(v[1]) == v[0]

        invalid = [0x10000, -1, [0x00, 0x00, 0x00]]
        for v in invalid:
            with pytest.raises(AssertionError):
                little_u16(v)

    def test_little_u32(self):
        values = [
            (1, [0x01, 0x00, 0x00, 0x00]),
            (256, [0x00, 0x01, 0x00, 0x00]),
            (0x10000, [0x00, 0x00, 0x01, 0x00]),
            (0x1000000, [0x00, 0x00, 0x00, 0x01]),
        ]

        for v in values:
            assert little_u32(v[0]) == bytes(v[1])
            assert little_u32(v[1]) == v[0]

        invalid = [0x100000000, -1, [0x00, 0x00, 0x00, 0x00, 0x00]]
        for v in invalid:
            with pytest.raises(AssertionError):
                little_u32(v)


class TestProtocolAny(object):
    protocol_version = ProtocolVersion.ANY

    def test_get_protocol(self):
        assert Protocol(self.protocol_version, callback=None) is not None

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
            assert request.opcode == 0xe6
            assert request.length == 6
            return SUCCESS

        if cb is None:
            cb = _cb

        p = Protocol(self.protocol_version, callback=cb)
        with pytest.raises(TypeError):
            p.execute(Interactions.CONNECT)  # missing argument

        uuid = 'abcdef123456'
        msg = p.execute(Interactions.CONNECT, uuid)
        assert msg.uuid == uuid

        with pytest.raises(ValueError):
            p.execute(Interactions.CONNECT, 'too-long-an-id')

        with pytest.raises(binascii.Error):
            uuid = 'uvwxyz123456'
            p.execute(Interactions.CONNECT, uuid)

    def test_get_name(self, cb=None, name='test dev name\x0a'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xbb
            assert request.length == 1
            assert request[0] == 0x00
            return NordicData([0xbc, len(name)] + list(bytes(name, encoding='ascii')))

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_NAME)
        assert msg.name == name

    def test_set_name(self, cb=None, name='test dev name'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xbb
            assert request.length == len(name) + 1
            assert request[-1] == 0xa  # spark needs a trailing linebreak
            assert bytes(request[:-1]).decode('utf-8') == name
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.SET_NAME, name=name)

    def test_get_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xb6
            assert request.length == 1
            t = time.strftime('%y%m%d%H%M%S', time.gmtime(ts))
            t = [int(i) for i in binascii.unhexlify(t)]
            return NordicData([0xbd, len(t)] + t)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_TIME)
        assert msg.timestamp == int(ts)

    def test_set_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xb6
            assert request.length == 6
            str_timestamp = ''.join([f'{b:02x}' for b in request])
            t = calendar.timegm(time.strptime(str_timestamp, '%y%m%d%H%M%S'))
            assert int(t) == int(ts)
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.SET_TIME, timestamp=ts)

    def test_get_fw(self, cb=None, fw='abcdef-123456'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xb7
            assert request.length == 1
            data = [int(c, 16) for c in fw.split('-')[request[0]]]
            return NordicData([0xb8, len(data) + 1, 0x00] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_FIRMWARE)
        assert msg.firmware == fw

    def test_get_battery(self, cb=None, battery=(1, 78)):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xb9
            assert request.length == 1
            return NordicData([0xba, 2, battery[1], battery[0]])

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_BATTERY)
        assert msg.battery_is_charging == battery[0]
        assert msg.battery_percent == battery[1]

    def test_get_width(self, cb=None):
        # this is hardcoded for the spark
        p = Protocol(self.protocol_version, callback=None)
        msg = p.execute(Interactions.GET_WIDTH)
        assert msg.width == 21000

    def test_get_height(self, cb=None):
        # this is hardcoded for the spark
        p = Protocol(self.protocol_version, callback=None)
        msg = p.execute(Interactions.GET_HEIGHT)
        assert msg.height == 14800

    def test_get_point_size(self, cb=None):
        # this is hardcoded for the spark
        p = Protocol(self.protocol_version, callback=None)
        msg = p.execute(Interactions.GET_POINT_SIZE)
        assert msg.point_size == 10

    def test_unknown_e3(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xe3
            assert request.length == 1
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.UNKNOWN_E3)

    def test_filetransfer_reporting_type(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xec
            assert request.length == 6
            assert request, [0x06, 0x00, 0x00, 0x00, 0x00 == 0x00]
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.SET_FILE_TRANSFER_REPORTING_TYPE)

    def test_set_mode(self, cb=None):
        for mode in Mode:
            mode = Mode.LIVE

            def _cb(request, requires_reply=True, userdata=None, timeout=5):
                assert request.opcode == 0xb1
                assert request.length == 1
                assert request[0] == mode
                return SUCCESS

            cb = cb or _cb

            p = Protocol(self.protocol_version, callback=cb)
            p.execute(Interactions.SET_MODE, mode)

    def test_get_strokes(self, cb=None, count=1024, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            # this is a weird double call, see the protocol
            # We reply 0xc7 first, and then 0xcd
            if request is not None:
                assert request.opcode == 0xc5
                assert request.length == 1
                assert request[0] == 0x00
                data = list(count.to_bytes(4, byteorder='big'))
                return NordicData([0xc7, len(data)] + data)
            else:
                t = time.strftime('%y%m%d%H%M%S', time.gmtime(ts))
                data = [int(i) for i in binascii.unhexlify(t)]
                return NordicData([0xcd, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_STROKES)
        assert msg.count == count
        assert msg.timestamp == int(ts)

    def test_available_files_count(self, cb=None, ndata=1234):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xc1
            assert request.length == 1
            assert request[0] == 0x00
            data = list(ndata.to_bytes(2, byteorder='big'))
            return NordicData([0xc2, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.AVAILABLE_FILES_COUNT)
        assert msg.count == ndata

    def test_download_oldest_file(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xc3
            assert request.length == 1
            assert request[0] == 0x00
            return NordicData([0xc8, 1, 0xbe])

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.DOWNLOAD_OLDEST_FILE)

    def test_delete_oldest_file(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xca
            assert request.length == 1
            assert request[0] == 0x00
            # no reply

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.DELETE_OLDEST_FILE)

    def test_register_complete(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xe5
            assert request.length == 1
            assert request[0] == 0x00
            return SUCCESS

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        p.execute(Interactions.REGISTER_COMPLETE)

    def test_register_press_button(self, cb=None, uuid=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xe3
            assert request.length == 1
            assert request[0] == 0x01
            # no reply

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.REGISTER_PRESS_BUTTON, uuid=uuid)
        assert msg.uuid == uuid

    def test_error_invalid_state(self):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            return NordicData([0xb3, 0x1, 0x1])

        p = Protocol(self.protocol_version, callback=_cb)

        # a "random" collection of requests that we want to check for
        with pytest.raises(DeviceError) as cm:
            p.execute(Interactions.CONNECT, uuid='abcdef123456')
        assert cm.value.errorcode == DeviceError.ErrorCode.GENERAL_ERROR

        with pytest.raises(DeviceError) as cm:
            p.execute(Interactions.GET_STROKES)
        assert cm.value.errorcode == DeviceError.ErrorCode.GENERAL_ERROR

        with pytest.raises(DeviceError) as cm:
            p.execute(Interactions.SET_MODE, Mode.PAPER)
        assert cm.value.errorcode == DeviceError.ErrorCode.GENERAL_ERROR


class TestProtocolSpark(TestProtocolAny):
    protocol_version = ProtocolVersion.SPARK

    def test_register_wait_for_button(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request is None
            return NordicData([0xe4, 0x00])

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.REGISTER_WAIT_FOR_BUTTON)
        assert msg.protocol_version == self.protocol_version


class TestProtocolSlate(TestProtocolSpark):
    protocol_version = ProtocolVersion.SLATE

    def test_get_width(self, cb=None, width=1234):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xea
            assert request.length == 2
            assert request[0] == 3

            data = [0x03, 0x00] + list(width.to_bytes(4, byteorder='little'))
            return NordicData([0xeb, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_WIDTH)
        assert msg.width == width

    def test_get_height(self, cb=None, height=4321):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xea
            assert request.length == 2
            assert request[0] == 4

            data = [0x04, 0x00] + list(height.to_bytes(4, byteorder='little'))
            return NordicData([0xeb, len(data)] + data)

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_HEIGHT)
        assert msg.height == height

    def test_get_strokes(self, cb=None, count=1024, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xcc
            assert request.length == 1
            assert request[0] == 0x00
            c = list(count.to_bytes(4, byteorder='little'))
            t = time.strftime('%y%m%d%H%M%S', time.gmtime(ts))
            t = [int(i) for i in binascii.unhexlify(t)]
            data = c + t
            return NordicData([0xcf, len(data)] + data)

        super().test_get_strokes(cb or _cb, count=count, ts=ts)

    def test_available_files_count(self, cb=None, ndata=1234):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xc1
            assert request.length == 1
            assert request[0] == 0x00
            data = list(ndata.to_bytes(2, byteorder='little'))
            return NordicData([0xc2, len(data)] + data)

        super().test_available_files_count(cb or _cb, ndata=ndata)

    def test_delete_oldest_file(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xca
            assert request.length == 1
            assert request[0] == 0x00
            return SUCCESS

        super().test_delete_oldest_file(cb or _cb)

    def test_register_press_button(self, cb=None, uuid='abcdef123456'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xe7
            assert request.length == 6
            # no reply

        super().test_register_press_button(cb or _cb, uuid)

    def test_register_wait_for_button(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request is None
            return NordicData([0xe4, 0x00])

        super().test_register_wait_for_button(cb or _cb)


class TestProtocolIntuosPro(TestProtocolSlate):
    protocol_version = ProtocolVersion.INTUOS_PRO

    def test_connect(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xe6
            assert request.length == 6
            return NordicData([0x50, 0x06] + request)  # replies with the uuid

        super().test_connect(cb or _cb)

    def test_get_name(self, cb=None, name='test dev name'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xdb
            assert request.length == 1
            assert request[0] == 0x00
            return NordicData([0xbc, len(name)] + list(bytes(name, encoding='ascii')))

        super().test_get_name(cb or _cb, name=name)

    def test_set_name(self, cb=None, name='test dev name'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xdb
            assert request.length == len(name)
            assert bytes(request).decode('utf-8') == name
            return SUCCESS

        super().test_set_name(cb or _cb, name=name)

    def test_get_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xd6
            assert request.length == 1
            t = list(int(ts).to_bytes(length=4, byteorder='little')) + [0x00, 0x00]
            return NordicData([0xbd, len(t)] + t)

        super().test_get_time(cb or _cb, ts=ts)

    def test_set_time(self, cb=None, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xb6
            assert request.length == 6
            t = int.from_bytes(request[0:4], byteorder='little')
            assert int(t) == int(ts)
            return SUCCESS

        super().test_set_time(cb or _cb, ts=ts)

    def test_get_fw(self, cb=None, fw='anything-string'):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xb7
            assert request.length == 1
            data = bytes(fw.split('-')[request[0]].encode('utf8'))
            return NordicData([0xb8, len(data) + 1, 0x00] + list(data))

        super().test_get_fw(cb or _cb, fw=fw)

    def test_get_strokes(self, cb=None, count=1024, ts=time.time()):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xcc
            assert request.length == 1
            assert request[0] == 0x00
            c = list(count.to_bytes(4, byteorder='little'))
            t = list(int(ts).to_bytes(4, byteorder='little'))
            data = c + t
            return NordicData([0xcf, len(data)] + data)

        super().test_get_strokes(cb or _cb, count=count, ts=ts)

    def test_register_wait_for_button(self, cb=None):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request is None
            return NordicData([0x53, 0x00])

        super().test_register_wait_for_button(cb or _cb)

    def test_get_point_size(self, cb=None, pointsize=12):
        def _cb(request, requires_reply=True, userdata=None, timeout=5):
            assert request.opcode == 0xea
            assert request.length == 2
            assert request[0] == 0x14
            ps = little_u32(pointsize)
            return NordicData([0xeb, 6, 0x14, 0x00] + list(ps))

        cb = cb or _cb

        p = Protocol(self.protocol_version, callback=cb)
        msg = p.execute(Interactions.GET_POINT_SIZE)
        assert msg.point_size == pointsize - 1
