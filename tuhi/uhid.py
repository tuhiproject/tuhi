#!/bin/env python3
# -*- coding: utf-8 -*-
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

from gi.repository import GObject
import os
import struct
import uuid


class UHIDUncompleteException(Exception):
    pass


class UHIDDevice(GObject.Object):
    __UHID_LEGACY_CREATE = 0
    UHID_DESTROY = 1
    UHID_START = 2
    UHID_STOP = 3
    UHID_OPEN = 4
    UHID_CLOSE = 5
    UHID_OUTPUT = 6
    __UHID_LEGACY_OUTPUT_EV = 7
    __UHID_LEGACY_INPUT = 8
    UHID_GET_REPORT = 9
    UHID_GET_REPORT_REPLY = 10
    UHID_CREATE2 = 11
    UHID_INPUT2 = 12
    UHID_SET_REPORT = 13
    UHID_SET_REPORT_REPLY = 14

    UHID_FEATURE_REPORT = 0
    UHID_OUTPUT_REPORT = 1
    UHID_INPUT_REPORT = 2

    def __init__(self, fd=None):
        GObject.Object.__init__(self)
        self._name = None
        self._phys = ''
        self._rdesc = None
        self.parsed_rdesc = None
        self._info = None
        if fd is None:
            self._fd = os.open('/dev/uhid', os.O_RDWR)
        else:
            self._fd = fd
        self.uniq = f'uhid_{str(uuid.uuid4())}'

    def __enter__(self):
        return self

    def __exit__(self, *exc_details):
        os.close(self._fd)

    @GObject.Property
    def fd(self):
        return self._fd

    @GObject.Property
    def rdesc(self):
        return self._rdesc

    @rdesc.setter
    def rdesc(self, rdesc):
        self._rdesc = rdesc

    @GObject.Property
    def phys(self):
        return self._phys

    @phys.setter
    def phys(self, phys):
        self._phys = phys

    @GObject.Property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self._name = name

    @GObject.Property
    def info(self):
        return self._info

    @info.setter
    def info(self, info):
        self._info = info

    @GObject.Property
    def bus(self):
        return self._info[0]

    @GObject.Property
    def vid(self):
        return self._info[1]

    @GObject.Property
    def pid(self):
        return self._info[2]

    def call_set_report(self, req, err):
        buf = struct.pack('< L L H',
                          UHIDDevice.UHID_SET_REPORT_REPLY,
                          req,
                          err)
        os.write(self._fd, buf)

    def call_get_report(self, req, data, err):
        data = bytes(data)
        buf = struct.pack('< L L H H 4096s',
                          UHIDDevice.UHID_GET_REPORT_REPLY,
                          req,
                          err,
                          len(data),
                          data)
        os.write(self._fd, buf)

    def call_input_event(self, data):
        data = bytes(data)
        buf = struct.pack('< L H 4096s',
                          UHIDDevice.UHID_INPUT2,
                          len(data),
                          data)
        os.write(self._fd, buf)

    def create_kernel_device(self):
        if (self._name is None or
           self._rdesc is None or
           self._info is None):
            raise UHIDUncompleteException("missing uhid initialization")

        buf = struct.pack('< L 128s 64s 64s H H L L L L 4096s',
                          UHIDDevice.UHID_CREATE2,
                          bytes(self._name, 'utf-8'),  # name
                          bytes(self._phys, 'utf-8'),  # phys
                          bytes(self.uniq, 'utf-8'),  # uniq
                          len(self._rdesc),  # rd_size
                          self.bus,  # bus
                          self.vid,  # vendor
                          self.pid,  # product
                          0,  # version
                          0,  # country
                          bytes(self._rdesc))  # rd_data[HID_MAX_DESCRIPTOR_SIZE]

        n = os.write(self._fd, buf)
        assert n == len(buf)
        self.ready = True

    def destroy(self):
        self.ready = False
        buf = struct.pack('< L',
                          UHIDDevice.UHID_DESTROY)
        os.write(self._fd, buf)

    def start(self, flags):
        print('start')

    def stop(self):
        print('stop')

    def open(self):
        print('open', self.sys_path)

    def close(self):
        print('close')

    def set_report(self, req, rnum, rtype, size, data):
        print('set report', req, rtype, size, [f'{d:02x}' for d in data[:size]])
        self.call_set_report(req, 1)

    def get_report(self, req, rnum, rtype):
        print('get report', req, rnum, rtype)
        self.call_get_report(req, [], 1)

    def output_report(self, data, size, rtype):
        print('output', rtype, size, [f'{d:02x}' for d in data[:size]])

    def process_one_event(self):
        buf = os.read(self._fd, 4380)
        assert len(buf) == 4380
        evtype = struct.unpack_from('< L', buf)[0]
        if evtype == UHIDDevice.UHID_START:
            ev, flags = struct.unpack_from('< L Q', buf)
            self.start(flags)
        elif evtype == UHIDDevice.UHID_OPEN:
            self.open()
        elif evtype == UHIDDevice.UHID_STOP:
            self.stop()
        elif evtype == UHIDDevice.UHID_CLOSE:
            self.close()
        elif evtype == UHIDDevice.UHID_SET_REPORT:
            ev, req, rnum, rtype, size, data = struct.unpack_from('< L L B B H 4096s', buf)
            self.set_report(req, rnum, rtype, size, data)
        elif evtype == UHIDDevice.UHID_GET_REPORT:
            ev, req, rnum, rtype = struct.unpack_from('< L L B B', buf)
            self.get_report(req, rnum, rtype)
        elif evtype == UHIDDevice.UHID_OUTPUT:
            ev, data, size, rtype = struct.unpack_from('< L 4096s H B', buf)
            self.output_report(data, size, rtype)
