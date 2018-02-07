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
import calendar
import logging
import threading
import time
import uuid
import errno
from gi.repository import GObject
from .drawing import Drawing

logger = logging.getLogger('tuhi.wacom')

WACOM_COMPANY_ID = 0x4755
NORDIC_UART_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_TX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_RX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'

WACOM_LIVE_SERVICE_UUID = '00001523-1212-efde-1523-785feabcd123'
WACOM_CHRC_LIVE_PEN_DATA_UUID = '00001524-1212-efde-1523-785feabcd123'

WACOM_OFFLINE_SERVICE_UUID = 'ffee0001-bbaa-9988-7766-554433221100'
WACOM_OFFLINE_CHRC_PEN_DATA_UUID = 'ffee0003-bbaa-9988-7766-554433221100'

MYSTERIOUS_NOTIFICATION_SERVICE_UUID = '3a340720-c572-11e5-86c5-0002a5d5c51b'
MYSTERIOUS_NOTIFICATION_CHRC_UUID = '3a340721-c572-11e5-86c5-0002a5d5c51b'

WACOM_SLATE_WIDTH = 21600
WACOM_SLATE_HEIGHT = 14800


def signed_char_to_int(v):
    return int.from_bytes([v], byteorder='little', signed=True)


def b2hex(bs):
    '''Convert bytes() to a two-letter hex string in the form "1a 2b c3"'''
    hx = binascii.hexlify(bs).decode('ascii')
    return ' '.join([''.join(s) for s in zip(hx[::2], hx[1::2])])


def list2hex(l):
    '''Converts a list of integers to a two-letter hex string in the form
    "1a 2b c3"'''
    return ' '.join([f'{x:02x}' for x in l])


class NordicData(list):
    def __init__(self, bs):
        super().__init__(bs[2:])
        self.opcode = bs[0]
        self.length = bs[1]


class WacomException(Exception):
    errno = errno.ENOSYS


class WacomEEAGAINException(WacomException):
    errno = errno.EAGAIN


class WacomWrongModeException(WacomException):
    errno = errno.EBADE


class WacomNotRegisteredException(WacomException):
    errno = errno.EACCES


class WacomTimeoutException(WacomException):
    errno = errno.ETIME


class WacomCorruptDataException(WacomException):
    errno = errno.EPROTO


class WacomDevice(GObject.Object):
    '''
    Class to communicate with the Wacom device. Communication is handled in
    a separate thread.

    :param device: the BlueZDevice object that is this wacom device
    '''

    __gsignals__ = {
        'drawing':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        'done':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT, )),
        'button-press-required':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        # battery level in %, boolean for is-charging
        "battery-status":
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_INT, GObject.TYPE_BOOLEAN)),
    }

    def __init__(self, device, uuid=None):
        GObject.Object.__init__(self)
        self.device = device
        self.nordic_answer = None
        self.pen_data_buffer = []
        self.thread = None
        self.width = WACOM_SLATE_WIDTH
        self.height = WACOM_SLATE_HEIGHT
        self.name = device.name
        self._uuid = uuid
        self.fw_logger = logging.getLogger('tuhi.fw')
        self._is_running = False

        device.connect_gatt_value(WACOM_CHRC_LIVE_PEN_DATA_UUID,
                                  self._on_pen_data_changed)
        device.connect_gatt_value(WACOM_OFFLINE_CHRC_PEN_DATA_UUID,
                                  self._on_pen_data_received)
        device.connect_gatt_value(NORDIC_UART_CHRC_RX_UUID,
                                  self._on_nordic_data_received)
        device.connect_gatt_value(MYSTERIOUS_NOTIFICATION_CHRC_UUID,
                                  self._on_mysterious_data_received)

    @GObject.Property
    def uuid(self):
        assert self._uuid is not None
        return self._uuid

    def is_spark(self):
        return MYSTERIOUS_NOTIFICATION_CHRC_UUID not in self.device.characteristics

    def _on_mysterious_data_received(self, name, value):
        self.fw_logger.debug(f'mysterious: {binascii.hexlify(bytes(value))}')

    def _on_pen_data_changed(self, name, value):
        logger.debug(binascii.hexlify(bytes(value)))

        if value[0] == 0x10:
            pressure = int.from_bytes(value[2:4], byteorder='little')
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
                    x = int.from_bytes(data[0:2], byteorder='little')
                    y = int.from_bytes(data[2:4], byteorder='little')
                    pressure = int.from_bytes(data[4:6], byteorder='little')
                    self.logger.info(f'New Pen Data: ({x},{y}), pressure: {pressure}')
                data = data[6:]

    def _on_pen_data_received(self, name, data):
        self.fw_logger.debug(f'RX Pen    <-- {list2hex(data)}')
        self.pen_data_buffer.extend(data)

    def _on_nordic_data_received(self, name, value):
        self.fw_logger.debug(f'RX Nordic <-- {list2hex(value)}')
        self.nordic_answer = value

    def send_nordic_command(self, command, arguments):
        chrc = self.device.characteristics[NORDIC_UART_CHRC_TX_UUID]
        data = [command, len(arguments), *arguments]
        self.fw_logger.debug(f'TX Nordic --> {command:02x} / {len(arguments):02x} / {list2hex(arguments)}')
        chrc.write_value(data)

    def check_nordic_incoming(self):
        if self.nordic_answer is None:
            raise WacomTimeoutException(f'{self.name}: Timeout while reading data')

        answer = self.nordic_answer
        self.nordic_answer = None
        length = answer[1]
        args = answer[2:]
        if length != len(args):
            raise WacomException(f'error while processing answer, should get an answer of size {length} instead of {len(args)}')
        return NordicData(answer)

    def wait_nordic_data(self, expected_opcode, timeout):
        t = time.time()
        while self.nordic_answer is None and time.time() - t < timeout:
            time.sleep(0.1)

        data = self.check_nordic_incoming()

        logger.debug(f'received {data.opcode:02x} / {data.length:02x} / {b2hex(bytes(data))}')

        if isinstance(expected_opcode, list):
            if data.opcode not in expected_opcode:
                raise WacomException(f'unexpected opcode: {data.opcode:02x}')
        else:
            if data.opcode != expected_opcode:
                raise WacomException(f'unexpected opcode: {data.opcode:02x}')

        return data

    def check_ack(self, data):
        if len(data) != 1:
            str_b = binascii.hexlify(bytes(data))
            raise WacomException(f'unexpected data: {str_b}')
        if data[0] == 0x07:
            raise WacomNotRegisteredException(f'wrong device, please re-register')
        if data[0] == 0x02:
            raise WacomEEAGAINException(f'unexpected answer: {data[0]:02x}')
        if data[0] == 0x01:
            raise WacomWrongModeException(f'wrong device mode')

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
        args = [int(i) for i in binascii.unhexlify(self.uuid)]
        self.send_nordic_command_sync(command=0xe6,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def register_connection(self):
        args = [int(i) for i in binascii.unhexlify(self.uuid)]
        self.send_nordic_command(command=0xe7,
                                 arguments=args)

    def e3_command(self):
        self.send_nordic_command_sync(command=0xe3,
                                      expected_opcode=0xb3)

    def set_time(self):
        # Device time is UTC
        self.current_time = time.strftime('%y%m%d%H%M%S', time.gmtime())
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
        fw = ''.join([hex(d)[2:] for d in data[1:]])
        return fw.upper()

    def get_name(self):
        data = self.send_nordic_command_sync(command=0xbb,
                                             expected_opcode=0xbc)
        return bytes(data)

    def get_dimensions(self, arg):
        possible_args = {
            'width': 3,
            'height': 4,
        }
        args = [possible_args[arg], 0x00]
        data = self.send_nordic_command_sync(command=0xea,
                                             expected_opcode=0xeb,
                                             arguments=args)
        if len(data) != 6:
            str_data = binascii.hexlify(bytes(data))
            raise WacomCorruptDataException(f'unexpected answer for get_dimensions: {str_data}')
        return int.from_bytes(data[2:4], byteorder='little')

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
        if self.is_spark():
            n = int.from_bytes(data[0:2], byteorder='big')
        else:
            n = int.from_bytes(data[0:2], byteorder='little')
        logger.debug(f'Drawings available: {n}')
        return n > 0

    def get_stroke_data_slate(self):
        data = self.send_nordic_command_sync(command=0xcc,
                                             expected_opcode=0xcf)
        # logger.debug(f'cc returned {data} ')
        count = int.from_bytes(data[0:4], byteorder='little')
        str_timestamp = ''.join([f'{d:02x}' for d in data[4:]])
        timestamp = time.strptime(str_timestamp, '%y%m%d%H%M%S')
        return count, timestamp

    def get_stroke_data_spark(self):
        data = self.send_nordic_command_sync(command=0xc5,
                                             expected_opcode=[0xc7, 0xcd])
        # FIXME: Sometimes the 0xc7 is missing on the spark? Not in any of
        # the btsnoop logs but I only rarely get a c7 response here
        count = 0
        if data.opcode == 0xc7:
            count = int.from_bytes(data[0:4], byteorder='little')
            data = self.wait_nordic_data(0xcd, 5)
            # logger.debug(f'cc returned {data} ')

        str_timestamp = ''.join([f'{d:02x}' for d in data])
        timestamp = time.strptime(str_timestamp, '%y%m%d%H%M%S')
        return count, timestamp

    def get_stroke_data(self):
        if not self.is_spark():
            return self.get_stroke_data_slate()
        return self.get_stroke_data_spark()

    def start_reading(self):
        data = self.send_nordic_command_sync(command=0xc3,
                                             expected_opcode=0xc8)
        if data[0] != 0xbe:
            raise WacomException(f'unexpected answer: {data[0]:02x}')

    def wait_for_end_read(self):
        data = self.wait_nordic_data(0xc8, 5)
        if data[0] != 0xed:
            raise WacomException(f'unexpected answer: {data[0]:02x}')
        crc = data[1:]
        if self.is_spark():
            data = self.wait_nordic_data(0xc9, 5)
            crc = data
        crc.reverse()
        crc = int(binascii.hexlify(bytes(crc)), 16)
        pen_data = self.pen_data_buffer
        self.pen_data_buffer = []
        if crc != binascii.crc32(bytes(pen_data)):
            if not self.is_spark():
                raise WacomCorruptDataException("CRCs don't match")
            else:
                logger.error("CRCs don't match")
        return pen_data

    def ack_transaction(self):
        if self.is_spark():
            opcode = None
        else:
            opcode = 0xb3
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
            v = int.from_bytes(data[2 * n:2 * n + 2], byteorder='little')
            dv = 0
        elif bitmask & delta_coord_bitmask:
            dv += signed_char_to_int(data[2 * n + 1])
            is_rel = True
        return v, dv, is_rel

    def parse_pen_data(self, data, timestamp):
        '''
        :param timestamp: a tuple with 9 entries, corresponding to the
        local time
        '''
        offset = 0
        x, y, p = 0, 0, 0
        dx, dy, dp = 0, 0, 0

        timestamp = int(calendar.timegm(timestamp))
        drawings = []
        drawing = None
        stroke = None
        while offset < len(data):
            bitmask, opcode, raw_args, args, offset = self.next_pen_data(data, offset)
            if opcode == 0x3800:
                logger.info(f'beginning of sequence')
                drawing = Drawing(self.name, (self.width, self.height), timestamp)
                drawings.append(drawing)
                continue
            elif opcode == 0xeeff:
                # some sort of headers
                time_offset = int.from_bytes(raw_args[4:], byteorder='little')
                logger.info(f'time offset since boot: {time_offset * 0.005} secs')
                stroke = drawing.new_stroke()
                continue
            if bytes(args) == b'\xff\xff\xff\xff\xff\xff\xff\xff':
                logger.info(f'end of sequence')
                continue
            if bytes(args) == b'\x00\x00\xff\xff\xff\xff\xff\xff':
                logger.info(f'end of stroke')
                stroke = None
                continue

            if stroke is None:
                stroke = drawing.new_stroke()

            x, dx, xrel = self.get_coordinate(bitmask, 0, args, x, dx)
            y, dy, yrel = self.get_coordinate(bitmask, 1, args, y, dy)
            p, dp, prel = self.get_coordinate(bitmask, 2, args, p, dp)

            x += dx
            y += dy
            p += dp

            logger.info(f'point at {x},{y} ({dx:+}, {dy:+}) with pressure {p} ({dp:+})')

            if bitmask & 0b00111100 == 0:
                continue
            if xrel or yrel or prel:
                stroke.new_rel((dx, dy), dp)
            else:
                stroke.new_abs((x, y), p)

        return drawings

    def read_offline_data(self):
        self.b1_command()
        transaction_count = 0
        while self.is_data_available():
            count, timestamp = self.get_stroke_data()
            logger.info(f'receiving {count} bytes drawn on {time.asctime(timestamp)}')
            self.start_reading()
            pen_data = self.wait_for_end_read()
            str_pen = binascii.hexlify(bytes(pen_data))
            logger.info(f'received {str_pen}')
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
            if self.is_spark():
                self.e3_command()
            self.set_time()
            battery, charging = self.get_battery_info()
            if charging:
                logger.debug(f'device is plugged in and charged at {battery}%')
            else:
                logger.debug(f'device is discharging: {battery}%')
            self.emit('battery-status', battery, charging)
            if not self.is_spark():
                self.width = w = self.get_dimensions('width')
                self.height = h = self.get_dimensions('height')
                logger.debug(f'dimensions: {w}x{h}')

                fw_high = self.get_firmware_version(0)
                fw_low = self.get_firmware_version(1)
                logger.debug(f'firmware is {fw_high}-{fw_low}')
                self.ec_command()
            if self.read_offline_data() == 0:
                logger.info('no data to retrieve')
        except WacomEEAGAINException:
            logger.warning('no data, please make sure the LED is blue and the button is pressed to switch it back to green')

    def register_device_slate(self):
        self.register_connection()
        logger.info('Press the button now to confirm')
        self.emit('button-press-required')
        data = self.wait_nordic_data([0xe4, 0xb3], 10)
        if data.opcode == 0xb3:
            # generic ACK
            self.check_ack(data)
        self.set_time()
        self.read_time()
        self.ec_command()
        name = self.get_name()
        logger.info(f'device name is {name}')
        w = self.get_dimensions('width')
        h = self.get_dimensions('height')
        if self.width != w or self.height != h:
            logger.error(f'Uncompatible dimensions: {w}x{h}')
        fw_high = self.get_firmware_version(0)
        fw_low = self.get_firmware_version(1)
        logger.info(f'firmware is {fw_high}-{fw_low}')

    def register_device_spark(self):
        try:
            self.check_connection()
        except WacomWrongModeException:
            # this is expected
            pass
        self.send_nordic_command(command=0xe3,
                                 arguments=[0x01])
        logger.info('Press the button now to confirm')
        self.emit('button-press-required')
        # Wait for the button confirmation event, or any error
        data = self.wait_nordic_data([0xe4, 0xb3], 10)
        if data.opcode == 0xb3:
            # generic ACK
            self.check_ack(data)
        self.send_nordic_command_sync(command=0xe5,
                                      arguments=None,
                                      expected_opcode=0xb3)
        self.set_time()
        self.read_time()
        name = self.get_name()
        logger.info(f'device name is {name}')
        fw_high = self.get_firmware_version(0)
        fw_low = self.get_firmware_version(1)
        logger.info(f'firmware is {fw_high}-{fw_low}')

    def register_device(self):
        self._uuid = uuid.uuid4().hex[:12]
        logger.debug(f'{self.device.address}: registering device, assigned {self.uuid}')
        if self.is_spark():
            self.register_device_spark()
        else:
            self.register_device_slate()
        logger.info('registration completed')
        self.notify('uuid')

    def run(self):
        if self._is_running:
            logger.error(f'{self.device.address}: already synching, ignoring this request')
            return

        logger.debug(f'{self.device.address}: starting')
        self._is_running = True
        exception = None
        try:
            if self._register_mode:
                self.register_device()
            else:
                self.retrieve_data()
        except WacomException as e:
            logger.error(f'**** Exception: {e} ****')
            exception = e
        finally:
            self._register_mode = False
            self._is_running = False
            self.emit('done', exception)

    def start(self, register_mode):
        self._register_mode = register_mode
        self.thread = threading.Thread(target=self.run)
        self.thread.start()
