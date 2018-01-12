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


import binascii
import logging
import threading
import sys
import time
from gi.repository import GObject

from tuhi.dbusserver import TuhiDBusServer
from tuhi.ble import BlueZDeviceManager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('wacom')

WACOM_COMPANY_ID = 0x4755
NORDIC_UART_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_TX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_RX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'

WACOM_LIVE_SERVICE_UUID = '00001523-1212-efde-1523-785feabcd123'
WACOM_CHRC_LIVE_PEN_DATA_UUID = '00001524-1212-efde-1523-785feabcd123'

WACOM_OFFLINE_SERVICE_UUID = 'ffee0001-bbaa-9988-7766-554433221100'
WACOM_OFFLINE_CHRC_PEN_DATA_UUID = 'ffee0003-bbaa-9988-7766-554433221100'

WACOM_SLATE_WIDTH = 14800
WACOM_SLATE_HEIGHT = 21600

# FIXME: this should be generated once and stored for future use (dconf?)
SMARTPAD_UUID = 'dead00beef00'
SMARTPAD_UUID = '1d6adc5fac76'
SMARTPAD_UUID = '4810d75d5d4d'

def signed_char_to_int(v):
    if v & 0x80:
        return v - (1 << 8)
    return v


def b2hex(bs):
    '''Convert bytes() to a two-letter hex string in the form "1a 2b c3"'''
    hx = binascii.hexlify(bs).decode("ascii")
    return ' '.join([''.join(s) for s in zip(hx[::2], hx[1::2])])


def list2hex(l):
    '''Converts a list of integers to a two-letter hex string in the form
    "1a 2b c3"'''
    return ' '.join(['{:02x}'.format(x) for x in l])


def list2le(l):
    r = 0
    for i in range(len(l)):
        r |= l[i] << (i * 8)
    return r


def list2be(l):
    rl = l[:]
    rl.reverse()
    return list2le(l)


class NordicData(list):
    def __init__(self, bs):
        super().__init__(bs[2:])
        self.opcode = bs[0]
        self.length = bs[1]


class Stroke(object):
    RELATIVE = 1
    ABSOLUTE = 2

    def __init__(self):
        self.points = []

    def add_pos(self, x, y):
        self.points.append((Stroke.ABSOLUTE, x, y))

    def add_rel(self, x, y, p=None):
        self.points.append((Stroke.RELATIVE, x, y, p))


class Drawing(list):
    def __init__(self, size, timestamp):
        super().__init__()
        self.timestamp = timestamp
        self.size = size


class WacomException(Exception):
    pass


class WacomEEAGAINException(WacomException):
    pass


class WacomNotPairedException(WacomException):
    pass


class WacomTimeoutException(WacomException):
    pass


class WacomCorruptDataException(WacomException):
    pass


class WacomDevice(GObject.Object):
    """
    Class to communicate with the Wacom device. Communication is handled in
    a separate thread.

    :param device: the BlueZDevice object that is this wacom device
    """

    __gsignals__ = {
            "drawing":
                (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self, device):
        GObject.Object.__init__(self)
        self.device = device
        self.nordic_answer = None
        self.pen_data_buffer = []
        self.thread = None
        self.width = WACOM_SLATE_WIDTH
        self.height = WACOM_SLATE_HEIGHT
        self.name = device.name

        device.connect_gatt_value(WACOM_CHRC_LIVE_PEN_DATA_UUID,
                                  self._on_pen_data_changed)
        device.connect_gatt_value(WACOM_OFFLINE_CHRC_PEN_DATA_UUID,
                                  self._on_pen_data_received)
        device.connect_gatt_value(NORDIC_UART_CHRC_RX_UUID,
                                  self._on_nordic_data_received)

    def is_slate(self):
        return self.name == "Bamboo Slate"

    def _on_pen_data_changed(self, name, value):
        logger.debug(binascii.hexlify(bytes(value)))

        if value[0] == 0x10:
            pressure = list2le(value[2:4])
            buttons = int(value[10])
            logger.info(f'New Pen Data: pressure: {pressure}, button: {buttons}')
        elif value[0] == 0xa2:
            # entering proximity event
            length = value[1]
            pen_id = binascii.hexlify(bytes(value[2:]))
            logger.info(f'Pen {pen_id} entered proximity')
        elif value[0] == 0xa1:
            # data event
            length = value[1]
            if length % 6 != 0:
                logger.error(f'wrong data: {binascii.hexlify(bytes(value))}')
                return
            data = value[2:]
            while data:
                if bytes(data) == b'\xff\xff\xff\xff\xff\xff':
                    logger.info(f'Pen left proximity')
                else:
                    y = list2le(data[0:2])
                    x = list2le(data[2:4])
                    pressure = list2le(data[4:6])
                    logger.info(f'New Pen Data: ({x},{y}), pressure: {pressure}')
                data = data[6:]

    def _on_pen_data_received(self, name, data):
        logger.debug(f"received pen data: {data}")
        self.pen_data_buffer.extend(data)

    def _on_nordic_data_received(self, name, value):
        logger.debug(f"received nordic data: {value}")
        self.nordic_answer = value

    def send_nordic_command(self, command, arguments):
        chrc = self.device.characteristics[NORDIC_UART_CHRC_TX_UUID]
        data = [command, len(arguments), *arguments]
        logger.debug(f'sending  {command:02x} / {len(arguments):02x} / {list2hex(arguments)}')
        chrc.write_value(data)

    def check_nordic_incoming(self):
        if self.nordic_answer is None:
            raise WacomTimeoutException(f"{self.name}: Timeout while reading data")

        answer = self.nordic_answer
        self.nordic_answer = None
        length = answer[1]
        args = answer[2:]
        if length != len(args):
            raise WacomException(f"error while processing answer, should get an answer of size {length} instead of {len(args)}")
        return NordicData(answer)

    def wait_nordic_data(self, expected_opcode, timeout):
        t = time.time()
        while self.nordic_answer is None and time.time() - t < timeout:
            time.sleep(0.1)

        data = self.check_nordic_incoming()

        logger.debug(f'received {data.opcode:02x} / {data.length:02x} / {b2hex(bytes(data))}')

        if isinstance(expected_opcode, list):
            if data.opcode not in expected_opcode:
                raise WacomException(f"unexpected opcode: {data.opcode:02x}")
        else:
            if data.opcode != expected_opcode:
                raise WacomException(f"unexpected opcode: {data.opcode:02x}")

        return data

    def check_ack(self, data):
        if len(data) != 1:
            str_b = binascii.hexlify(bytes(data))
            raise WacomException(f"unexpected data: {str_b}")
        if data[0] == 0x07:
            raise WacomNotPairedException(f"wrong device, please redo pairing")
        if data[0] == 0x02:
            raise WacomEEAGAINException(f"unexpected answer: {data[0]:02x}")

    def send_nordic_command_sync(self,
                                 command,
                                 expected_opcode,
                                 arguments=None):
        if arguments is None:
            arguments = [0x00]

        self.send_nordic_command(command, arguments)

        if expected_opcode is None:
            return None

        args = self.wait_nordic_data(expected_opcode, 5)

        if expected_opcode == 0xb3:  # generic ACK
            self.check_ack(args)

        return args

    def check_connection(self):
        args = [int(i) for i in binascii.unhexlify(SMARTPAD_UUID)]
        self.send_nordic_command_sync(command=0xe6,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def register_connection(self):
        args = [int(i) for i in binascii.unhexlify(SMARTPAD_UUID)]
        self.send_nordic_command(command=0xe7,
                                 arguments=args)

    def e3_command(self):
        self.send_nordic_command_sync(command=0xe3,
                                      expected_opcode=0xb3)

    def set_time(self):
        self.current_time = time.strftime("%y%m%d%H%M%S")
        args = [int(i) for i in binascii.unhexlify(self.current_time)]
        self.send_nordic_command_sync(command=0xb6,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def read_time(self):
        data = self.send_nordic_command_sync(command=0xb6,
                                             expected_opcode=0xbd)
        logger.debug(f'b6 returned {data}')
        # FIXME: check if data matches self.current_time

    def get_battery_info(self):
        data = self.send_nordic_command_sync(command=0xb9,
                                             expected_opcode=0xba)
        return int(data[0]), data[1] == 1

    def get_firmware_version(self, arg):
        data = self.send_nordic_command_sync(command=0xb7,
                                             expected_opcode=0xb8,
                                             arguments=(arg,))
        fw = ''.join([hex(d)[2:] for d in data])
        return fw.upper()

    def bb_command(self):
        data = self.send_nordic_command_sync(command=0xbb,
                                             expected_opcode=0xbc)
        logger.debug(f'bb returned {data}')

    def get_dimensions(self, arg):
        possible_args = {
            'height': 3,
            'width': 4,
        }
        args = [possible_args[arg], 0x00]
        data = self.send_nordic_command_sync(command=0xea,
                                             expected_opcode=0xeb,
                                             arguments=args)
        if len(data) != 6:
            str_data = binascii.hexlify(bytes(data))
            raise WacomCorruptDataException(f'unexpected answer for get_dimensions: {str_data}')
        return list2le(data[2:4])

    def ec_command(self):
        args = [0x06, 0x00, 0x00, 0x00, 0x00, 0x00]
        self.send_nordic_command_sync(command=0xec,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def start_live(self):
        self.send_nordic_command_sync(command=0xb1,
                                      expected_opcode=0xb3)

    def stop_live(self):
        args = [0x02]
        self.send_nordic_command_sync(command=0xb1,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def b1_command(self):
        args = [0x01]
        self.send_nordic_command_sync(command=0xb1,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def is_data_available(self):
        data = self.send_nordic_command_sync(command=0xc1,
                                             expected_opcode=0xc2)
        n = 0
        if self.is_slate():
            n = list2le(data[0:2])
        else:
            n = list2be(data[0:2])
        logger.debug(f'Drawings available: {n}')
        return n > 0

    def get_stroke_data_slate(self):
        data = self.send_nordic_command_sync(command=0xcc,
                                             expected_opcode=0xcf)
        # logger.debug(f'cc returned {data} ')
        count = list2le(data[0:4])
        str_timestamp = ''.join([hex(d)[2:] for d in data[4:]])
        timestamp = time.strptime(str_timestamp, "%y%m%d%H%M%S")
        return count, timestamp

    def get_stroke_data_spark(self):
        data = self.send_nordic_command_sync(command=0xc5,
                                             expected_opcode=[0xc7, 0xcd])
        # FIXME: Sometimes the 0xc7 is missing on the spark? Not in any of
        # the btsnoop logs but I only rarely get a c7 response here
        count = 0
        if data.opcode == 0xc7:
            count = list2le(data[0:4])
            data = self.wait_nordic_data(0xcd, 5)
            # logger.debug(f'cc returned {data} ')

        str_timestamp = ''.join([hex(d)[2:] for d in data])
        timestamp = time.strptime(str_timestamp, "%y%m%d%H%M%S")
        return count, timestamp

    def get_stroke_data(self):
        if self.is_slate():
            return self.get_stroke_data_slate()
        return self.get_stroke_data_spark()

    def start_reading(self):
        data = self.send_nordic_command_sync(command=0xc3,
                                             expected_opcode=0xc8)
        if data[0] != 0xbe:
            raise WacomException(f"unexpected answer: {data[0]:02x}")

    def wait_for_end_read(self):
        data = self.wait_nordic_data(0xc8, 5)
        if data[0] != 0xed:
            raise WacomException(f"unexpected answer: {data[0]:02x}")
        crc = data[1:]
        if not self.is_slate():
            data = self.wait_nordic_data(0xc9, 5)
            crc = data
        crc.reverse()
        crc = int(binascii.hexlify(bytes(crc)), 16)
        pen_data = self.pen_data_buffer
        self.pen_data_buffer = []
        if crc != binascii.crc32(bytes(pen_data)):
            if self.is_slate():
                raise WacomCorruptDataException("CRCs don't match")
            else:
                logger.error("CRCs don't match")
        return pen_data

    def ack_transaction(self):
        if self.is_slate():
            opcode = 0xb3
        else:
            opcode = None
        self.send_nordic_command_sync(command=0xca,
                                      expected_opcode=opcode)

    def next_pen_data(self, data, offset):
        debug_data = []
        bitmask = data[offset]
        opcode = 0
        offset += 1
        debug_data.append(f'{bitmask:02x} ({bitmask:08b})')
        debug_data.append('|')
        args_length = bin(bitmask).count('1')
        args = data[offset:offset + args_length]
        formatted_args = []
        n = 0
        for i in range(2):
            if (1 << i) & bitmask:
                debug_data.append(f'{args[n]:02x}')
                opcode |= args[n] << (i * 8)
                formatted_args.append(args[n])
                n += 1
            else:
                formatted_args.append(0)
                debug_data.append('  ')
        debug_data.append(f'|')
        for i in range(2, 8):
            if (1 << i) & bitmask:
                debug_data.append(f'{args[n]:02x}')
                formatted_args.append(args[n])
                n += 1
            else:
                formatted_args.append(0)
                debug_data.append('  ')
        logger.debug(f'{" ".join(debug_data)}')
        return bitmask, opcode, args, formatted_args, offset + args_length

    def get_coordinate(self, bitmask, n, data, v, dv):
        # drop the first 2 bytes as they are not valuable here
        bitmask >>= 2
        data = data[2:]
        is_rel = False

        full_coord_bitmask = 0b11 << (2 * n)
        delta_coord_bitmask = 0b10 << (2 * n)
        if (bitmask & full_coord_bitmask) == full_coord_bitmask:
            v = list2le(data[2 * n:2 * n + 2])
            dv = 0
        elif bitmask & delta_coord_bitmask:
            dv += signed_char_to_int(data[2 * n + 1])
            is_rel = True
        return v, dv, is_rel

    def parse_pen_data(self, data, timestamp):
        offset = 0
        x, y, p = 0, 0, 0
        dx, dy, dp = 0, 0, 0

        drawings = []
        drawing = None
        stroke = None
        while offset < len(data):
            bitmask, opcode, raw_args, args, offset = self.next_pen_data(data, offset)
            if opcode == 0x3800:
                logger.info(f'beginning of sequence')
                drawing = Drawing((self.width, self.height), timestamp)
                drawings.append(drawing)
                continue
            elif opcode == 0xeeff:
                # some sort of headers
                time_offset = list2be(raw_args[4:])
                logger.info(f'time offset since boot: {time_offset * 0.005} secs')
                stroke = Stroke()
                drawing.append(stroke)
                continue
            if bytes(args) == b'\xff\xff\xff\xff\xff\xff\xff\xff':
                logger.info(f'end of sequence')
                continue
            if bytes(args) == b'\x00\x00\xff\xff\xff\xff\xff\xff':
                logger.info(f'end of stroke')
                stroke = None
                continue

            if stroke is None:
                stroke = Stroke()
                drawing.append(stroke)

            y, dy, yrel = self.get_coordinate(bitmask, 0, args, y, dy)
            x, dx, xrel = self.get_coordinate(bitmask, 1, args, x, dx)
            p, dp, prel = self.get_coordinate(bitmask, 2, args, p, dp)

            x += dx
            y += dy
            p += dp

            logger.info(f'point at {x},{y} ({dx:+}, {dy:+}) with pressure {p} ({dp:+})')

            if bitmask & 0b00111100 == 0:
                continue
            if xrel or yrel or prel:
                stroke.add_rel(dx, dy, dp)
            else:
                stroke.add_pos(x, y)

        return drawings

    def read_offline_data(self):
        self.b1_command()
        transaction_count = 0
        while self.is_data_available():
            count, timestamp = self.get_stroke_data()
            logger.info(f"receiving {count} bytes drawn on {time.asctime(timestamp)}")
            self.start_reading()
            pen_data = self.wait_for_end_read()
            str_pen = binascii.hexlify(bytes(pen_data))
            logger.info(f"received {str_pen}")
            prefix = pen_data[:4]
            # not sure if we really need this check
            # note: \x38\x62\x74 translates to '8bt'
            if bytes(prefix) == b'\x62\x38\x62\x74':
                drawings = self.parse_pen_data(pen_data, timestamp)
                for drawing in drawings:
                    self.emit('drawing', drawing)
            self.ack_transaction()
            transaction_count += 1
        return transaction_count

    def retrieve_data(self):
        try:
            self.check_connection()
            if not self.is_slate():
                self.e3_command()
            self.set_time()
            battery, charging = self.get_battery_info()
            if charging:
                logger.debug(f'device is plugged in and charged at {battery}%')
            else:
                logger.debug(f'device is discharging: {battery}%')
            if self.is_slate():
                self.width = self.get_dimensions('width')
                self.height = self.get_dimensions('height')
                logger.debug(f'dimensions: {self.width}x{self.height}')

                fw_high = self.get_firmware_version(0)
                fw_low = self.get_firmware_version(1)
                logger.debug(f'firmware is {fw_high}-{fw_low}')
                self.ec_command()
            if self.read_offline_data() == 0:
                logger.info("no data to retrieve")
        except WacomEEAGAINException:
            logger.warning("no data, please make sure the LED is blue and the button is pressed to switch it back to green")

    def run(self):
        time.sleep(2)
        logger.debug('{}: starting'.format(self.device.address))
        self.retrieve_data()

    def start(self):
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

