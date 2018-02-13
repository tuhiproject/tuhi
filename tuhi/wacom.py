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
import enum
import logging
import threading
import time
import uuid
import errno
from gi.repository import GObject
from .drawing import Drawing
from .uhid import UHIDDevice

logger = logging.getLogger('tuhi.wacom')

NORDIC_UART_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_TX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_RX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'

WACOM_LIVE_SERVICE_UUID = '00001523-1212-efde-1523-785feabcd123'
WACOM_CHRC_LIVE_PEN_DATA_UUID = '00001524-1212-efde-1523-785feabcd123'

WACOM_OFFLINE_SERVICE_UUID = 'ffee0001-bbaa-9988-7766-554433221100'
WACOM_OFFLINE_CHRC_PEN_DATA_UUID = 'ffee0003-bbaa-9988-7766-554433221100'

MYSTERIOUS_NOTIFICATION_SERVICE_UUID = '3a340720-c572-11e5-86c5-0002a5d5c51b'
MYSTERIOUS_NOTIFICATION_CHRC_UUID = '3a340721-c572-11e5-86c5-0002a5d5c51b'


@enum.unique
class Protocol(enum.Enum):
    UNKNOWN = 'unknown'
    SPARK = 'spark'
    SLATE = 'slate'
    INTUOS_PRO = 'intuos-pro'


@enum.unique
class DeviceMode(enum.Enum):
    REGISTER = 1
    LISTEN = 2
    LIVE = 3


wacom_live_rdesc_template = [
    0x05, 0x0d,                    # Usage Page (Digitizers)             0
    0x09, 0x02,                    # Usage (Pen)                         2
    0xa1, 0x01,                    # Collection (Application)            4
    0x85, 0x01,                    # .Report ID (1)                      6
    0x09, 0x20,                    # .Usage (Stylus)                     8
    0xa1, 0x00,                    # .Collection (Physical)              10
    0x09, 0x32,                    # ..Usage (In Range)                  12
    0x15, 0x00,                    # ..Logical Minimum (0)               14
    0x25, 0x01,                    # ..Logical Maximum (1)               16
    0x95, 0x01,                    # ..Report Count (1)                  18
    0x75, 0x01,                    # ..Report Size (1)                   20
    0x81, 0x02,                    # ..Input (Data,Var,Abs)              22
    0x95, 0x07,                    # ..Report Count (7)                  24
    0x81, 0x03,                    # ..Input (Cnst,Var,Abs)              26
    0x05, 0x01,                    # ..Usage Page (Generic Desktop)      43
    0x09, 0x30,                    # ..Usage (X)                         45
    0x75, 0x10,                    # ..Report Size (16)                  47
    0x95, 0x01,                    # ..Report Count (1)                  49
    0x55, 0x0e,                    # ..Unit Exponent (-2)                51
    0x65, 0x11,                    # ..Unit (Centimeter,SILinear)        53
    0x46, 0xec, 0x09,              # ..Physical Maximum (2540)           55
    0x26, 0x80, 0x25,              # ..Logical Maximum (9600)            58
    0x81, 0x02,                    # ..Input (Data,Var,Abs)              61
    0x09, 0x31,                    # ..Usage (Y)                         63
    0x46, 0x9d, 0x06,              # ..Physical Maximum (1693)           65
    0x26, 0x20, 0x1c,              # ..Logical Maximum (7200)            68
    0x81, 0x02,                    # ..Input (Data,Var,Abs)              71
    0x05, 0x0d,                    # ..Usage Page (Digitizers)           73
    0x09, 0x30,                    # ..Usage (Tip Pressure)              75
    0x26, 0x00, 0x01,              # ..Logical Maximum (256)             77
    0x81, 0x02,                    # ..Input (Data,Var,Abs)              80
    0xc0,                          # .End Collection                     82
    0xc0,                          # End Collection                      83
]


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


class WacomProtocolLowLevelComm(GObject.Object):
    '''
    Internal class to handle the communication with the Wacom device.
    No-one should directly instanciate this.


    :param device: the BlueZDevice object that is this wacom device
    '''

    def __init__(self, device):
        GObject.Object.__init__(self)
        self.device = device
        self.nordic_answer = None
        self.fw_logger = logging.getLogger('tuhi.fw')

        device.connect_gatt_value(NORDIC_UART_CHRC_RX_UUID,
                                  self._on_nordic_data_received)

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
            raise WacomTimeoutException(f'{self.device.name}: Timeout while reading data')

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
        if data[0] == 0x05:
            raise WacomCorruptDataException(f'invalid opcode')

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


class WacomRegisterHelper(WacomProtocolLowLevelComm):
    '''
    Class used to register a device. This class is only useful for
    the very first register commands and attempts to detect the type of
    device based on the responses.

    Once register_device has finished, the correct protocol is returned.
    This may later be used for init_protocol() to instantiate the
    right class.
    '''
    __gsignals__ = {
        # Signal sent when the device requires the user to press the
        # physical button
        'button-press-required': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    @classmethod
    def is_spark(cls, device):
        return MYSTERIOUS_NOTIFICATION_CHRC_UUID not in device.characteristics

    def register_device(self, uuid):
        protocol = Protocol.UNKNOWN
        args = [int(i) for i in binascii.unhexlify(uuid)]

        if self.is_spark(self.device):
            # The spark replies with b3 01 01 when in pairing mode
            # Usually that triggers a WacomWrongModeException but here it's
            # expected
            try:
                self.send_nordic_command_sync(command=0xe6,
                                              expected_opcode=0xb3,
                                              arguments=args)
            except WacomWrongModeException:
                # this is expected
                pass

            # The "press button now command" on the spark
            self.send_nordic_command(command=0xe3,
                                     arguments=[0x01])
            protocol = Protocol.SPARK
        else:
            # Slate requires a button press in response to e7 directly
            self.send_nordic_command(command=0xe7, arguments=args)

        logger.info('Press the button now to confirm')
        self.emit('button-press-required')

        # Wait for the button confirmation event, or any error
        data = self.wait_nordic_data([0xe4, 0xb3], 10)

        if protocol == Protocol.UNKNOWN:
            if data.opcode == 0xe4:
                protocol = Protocol.SLATE
            else:
                raise WacomException(f'unexpected opcode to register reply: {data.opcode:02x}')

        return protocol


class WacomProtocolBase(WacomProtocolLowLevelComm):
    '''
    Internal class to handle the basic communications with the Wacom device.
    No-one should directly instanciate this.


    :param device: the BlueZDevice object that is this wacom device
    :param uuid: the UUID {to be} assigned to the device
    '''
    protocol = Protocol.UNKNOWN

    __gsignals__ = {
        # Signal sent for each single drawing that becomes available. The
        # drawing is the signal's argument
        'drawing':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        # battery level in %, boolean for is-charging
        "battery-status":
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_INT, GObject.TYPE_BOOLEAN)),
    }

    def __init__(self, device, uuid):
        super().__init__(device)
        self._uuid = uuid
        self._timestamp = 0
        self.pen_data_buffer = []
        self._uhid_device = None

        device.connect_gatt_value(WACOM_CHRC_LIVE_PEN_DATA_UUID,
                                  self._on_pen_data_changed)
        device.connect_gatt_value(WACOM_OFFLINE_CHRC_PEN_DATA_UUID,
                                  self._on_pen_data_received)

    def _on_pen_data_changed(self, name, value):
        logger.debug(binascii.hexlify(bytes(value)))

        if value[0] == 0x10:
            pressure = int.from_bytes(value[2:4], byteorder='little')
            buttons = int(value[10])
            logger.debug(f'New Pen Data: pressure: {pressure}, button: {buttons}')
        elif value[0] == 0xa2:
            # entering proximity event
            length = value[1]
            # timestamp is now in ms
            timestamp = int.from_bytes(value[4:], byteorder='little') * 5
            self._timestamp = timestamp
            logger.debug(f'Pen entered proximity, timestamp: {timestamp}')
        elif value[0] == 0xa1:
            # data event
            length = value[1]
            if length % 6 != 0:
                logger.error(f'wrong data: {binascii.hexlify(bytes(value))}')
                return
            data = value[2:]
            while data:
                if bytes(data) == b'\xff\xff\xff\xff\xff\xff':
                    logger.debug(f'Pen left proximity')

                    if self._uhid_device is not None:
                        self._uhid_device.call_input_event([1, 0, 0, 0, 0, 0, 0, 0])

                else:
                    x = int.from_bytes(data[0:2], byteorder='little')
                    y = int.from_bytes(data[2:4], byteorder='little')
                    pressure = int.from_bytes(data[4:6], byteorder='little')
                    logger.debug(f'New Pen Data: ({x},{y}), pressure: {pressure}')

                    if self._uhid_device is not None:
                        self._uhid_device.call_input_event([1, 1, *data[:6]])

                data = data[6:]
                self._timestamp += 5

    def _on_pen_data_received(self, name, data):
        self.fw_logger.debug(f'RX Pen    <-- {list2hex(data)}')
        self.pen_data_buffer.extend(data)

    def check_connection(self):
        args = [int(i) for i in binascii.unhexlify(self._uuid)]
        self.send_nordic_command_sync(command=0xe6,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def e3_command(self):
        self.send_nordic_command_sync(command=0xe3,
                                      expected_opcode=0xb3)

    def time_to_bytes(self):
        # Device time is UTC
        current_time = time.strftime('%y%m%d%H%M%S', time.gmtime())
        return [int(i) for i in binascii.unhexlify(current_time)]

    def time_from_bytes(self, data):
        assert len(data) >= 6
        str_timestamp = ''.join([f'{d:02x}' for d in data])
        return time.strptime(str_timestamp, '%y%m%d%H%M%S')

    def set_time(self):
        args = self.time_to_bytes()
        self.send_nordic_command_sync(command=0xb6,
                                      expected_opcode=0xb3,
                                      arguments=args)

    def read_time(self):
        data = self.send_nordic_command_sync(command=0xb6,
                                             expected_opcode=0xbd)
        ts = self.time_from_bytes(data)
        logger.debug(f'b6 returned time: UTC {time.strftime("%y%m%d%H%M%S", ts)}')
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

    def start_live(self, fd):
        self.send_nordic_command_sync(command=0xb1,
                                      expected_opcode=0xb3)
        logger.debug(f'Starting wacom live mode on fd: {fd}')

        rdesc = wacom_live_rdesc_template
        uhid_device = UHIDDevice(fd)
        uhid_device.rdesc = rdesc
        uhid_device.name = self.device.name
        uhid_device.info = (5, 0x056a, 0x0001)
        uhid_device.create_kernel_device()
        self._uhid_device = uhid_device

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
        n = int.from_bytes(data[0:2], byteorder='big')
        logger.debug(f'Drawings available: {n}')
        return n > 0

    def get_stroke_data(self):
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
        data = self.wait_nordic_data(0xc9, 5)
        crc = data
        crc.reverse()
        crc = int(binascii.hexlify(bytes(crc)), 16)
        pen_data = self.pen_data_buffer
        self.pen_data_buffer = []
        if crc != binascii.crc32(bytes(pen_data)):
            logger.error("CRCs don't match")
        return pen_data

    def retrieve_data(self):
        try:
            self.check_connection()
            self.e3_command()
            self.set_time()
            battery, charging = self.get_battery_info()
            if charging:
                logger.debug(f'device is plugged in and charged at {battery}%')
            else:
                logger.debug(f'device is discharging: {battery}%')
            self.emit('battery-status', battery, charging)
            if self.read_offline_data() == 0:
                logger.info('no data to retrieve')
        except WacomEEAGAINException:
            logger.warning('no data, please make sure the LED is blue and the button is pressed to switch it back to green')

    def ack_transaction(self):
        self.send_nordic_command_sync(command=0xca,
                                      expected_opcode=None)

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
                drawing = Drawing(self.device.name, (self.width, self.height), timestamp)
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
            logger.info(f'receiving {count} bytes drawn on UTC {time.strftime("%y%m%d%H%M%S", timestamp)}')
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

    def set_name(self, name):
        # On the Spark, the name needs a trailing linebreak, otherwise the
        # firmware gets confused.
        args = [ord(c) for c in name] + [0x0a]
        data = self.send_nordic_command_sync(command=0xbb,
                                             arguments=args,
                                             expected_opcode=0xb3)
        return bytes(data)

    def register_device_finish(self):
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

    def live_mode(self, mode, uhid):
        try:
            if mode:
                self.check_connection()
                self.start_live(uhid)
            else:
                self.stop_live()
        except WacomEEAGAINException:
            logger.warning("no data, please make sure the LED is blue and the button is pressed to switch it back to green")


class WacomProtocolSpark(WacomProtocolBase):
    '''
    Subclass to handle the communication oddities with the Wacom Spark-like
    devices.

    :param device: the BlueZDevice object that is this wacom device
    :param uuid: the UUID {to be} assigned to the device
    '''
    width = 21600
    height = 14800
    protocol = Protocol.SPARK


class WacomProtocolSlate(WacomProtocolSpark):
    '''
    Subclass to handle the communication oddities with the Wacom Slate-like
    devices.

    :param device: the BlueZDevice object that is this wacom device
    :param uuid: the UUID {to be} assigned to the device
    '''
    width = 21600
    height = 14800
    protocol = Protocol.SLATE

    def __init__(self, device, uuid):
        super().__init__(device, uuid)
        device.connect_gatt_value(MYSTERIOUS_NOTIFICATION_CHRC_UUID,
                                  self._on_mysterious_data_received)

    def _on_mysterious_data_received(self, name, value):
        self.fw_logger.debug(f'mysterious: {binascii.hexlify(bytes(value))}')

    def ack_transaction(self):
        self.send_nordic_command_sync(command=0xca,
                                      expected_opcode=0xb3)

    def is_data_available(self):
        data = self.send_nordic_command_sync(command=0xc1,
                                             expected_opcode=0xc2)
        n = int.from_bytes(data[0:2], byteorder='little')
        logger.debug(f'Drawings available: {n}')
        return n > 0

    def get_stroke_data(self):
        data = self.send_nordic_command_sync(command=0xcc,
                                             expected_opcode=0xcf)
        # logger.debug(f'cc returned {data} ')
        count = int.from_bytes(data[0:4], byteorder='little')
        timestamp = self.time_from_bytes(data[4:])
        return count, timestamp

    def register_device_finish(self):
        self.set_time()
        self.read_time()
        self.ec_command()
        name = self.get_name()
        logger.info(f'device name is {name}')
        w = self.get_dimensions('width')
        h = self.get_dimensions('height')
        if self.width != w or self.height != h:
            logger.error(f'incompatible dimensions: {w}x{h}')
        fw_high = self.get_firmware_version(0)
        fw_low = self.get_firmware_version(1)
        logger.info(f'firmware is {fw_high}-{fw_low}')

    def retrieve_data(self):
        try:
            self.check_connection()
            self.set_time()
            battery, charging = self.get_battery_info()
            if charging:
                logger.debug(f'device is plugged in and charged at {battery}%')
            else:
                logger.debug(f'device is discharging: {battery}%')
            self.emit('battery-status', battery, charging)
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

    def wait_for_end_read(self):
        data = self.wait_nordic_data(0xc8, 5)
        if data[0] != 0xed:
            raise WacomException(f'unexpected answer: {data[0]:02x}')
        crc = data[1:]
        crc.reverse()
        crc = int(binascii.hexlify(bytes(crc)), 16)
        pen_data = self.pen_data_buffer
        self.pen_data_buffer = []
        if crc != binascii.crc32(bytes(pen_data)):
            raise WacomCorruptDataException("CRCs don't match")
        return pen_data


class WacomDevice(GObject.Object):
    '''
    Class to communicate with the Wacom device. Communication is handled in
    a separate thread.

    :param device: the BlueZDevice object that is this wacom device
    '''

    __gsignals__ = {
        # Signal sent for each single drawing that becomes available. The
        # drawing is the signal's argument
        'drawing':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        # Signal sent when a device connection (register or listen) is
        # complete. Carries the exception object or None on success
        'done':
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT, )),
        # Signal sent when the device requires the user to press the
        # physical button'''
        'button-press-required':
            (GObject.SignalFlags.RUN_FIRST, None, ()),
        # battery level in %, boolean for is-charging
        "battery-status":
            (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_INT, GObject.TYPE_BOOLEAN)),
    }

    def __init__(self, device, config=None):
        GObject.Object.__init__(self)
        self._device = device
        self.thread = None
        self._is_running = False
        self._config = None
        self._wacom_protocol = None

        try:
            self._config = config.devices[device.address]
        except KeyError:
            # unregistered device
            self._uuid = None
        else:
            self._uuid = self._config['uuid']

            # retrieve the protocol from the config file
            protocol = Protocol.UNKNOWN
            try:
                protocol = next(p for p in Protocol if p.value == self._config['Protocol'])
            except StopIteration:
                logger.error(f'Unknown protocol in configuration: {self._config["Protocol"]}')
                raise WacomCorruptDataException(f'Unknown Protocol {self._config["Protocol"]}')

            if protocol == Protocol.UNKNOWN:
                raise WacomCorruptDataException(f'Missing Protocol entry from config file. Please delete config file and re-register device')

            self._init_protocol(protocol)

    def _init_protocol(self, protocol):
        if protocol == Protocol.SPARK:
            self._wacom_protocol = WacomProtocolSpark(self._device, self._uuid)
        elif protocol == Protocol.SLATE:
            self._wacom_protocol = WacomProtocolSlate(self._device, self._uuid)
        else:
            # FIXME: change to an assert once intuos-pro is implemented, we
            # never get here
            logger.error(f'Unknown Protocol {protocol}')
            raise WacomCorruptDataException(f'Protocol "{protocol}" not implemented')

        logger.debug(f'{self._device.name} is using protocol {protocol}')

        self._wacom_protocol.connect(
            'drawing',
            lambda protocol, drawing, self: self.emit('drawing', drawing),
            self)
        self._wacom_protocol.connect(
            'battery-status',
            lambda prot, percent, is_charging, self: self.emit('battery-status', percent, is_charging),
            self)

    @GObject.Property
    def uuid(self):
        assert self._uuid is not None
        return self._uuid

    @GObject.Property
    def protocol(self):
        assert self._wacom_protocol is not None
        return self._wacom_protocol.protocol

    def register_device(self):
        self._uuid = uuid.uuid4().hex[:12]
        logger.debug(f'{self._device.address}: registering device, assigned {self.uuid}')

        wp = WacomRegisterHelper(self._device)
        s = wp.connect('button-press-required',
                       lambda protocol, self: self.emit('button-press-required'),
                       self)
        protocol = wp.register_device(self._uuid)
        wp.disconnect(s)
        del wp

        self._init_protocol(protocol)
        self._wacom_protocol.register_device_finish()

        logger.info('registration completed')
        self.notify('uuid')

    def _run(self, *args, **kwargs):
        if self._is_running:
            logger.error(f'{self._device.address}: already synching, ignoring this request')
            return

        mode = args[0]

        logger.debug(f'{self._device.address}: starting')
        self._is_running = True
        exception = None
        try:
            if mode == DeviceMode.LIVE:
                assert self._wacom_protocol is not None
                self._wacom_protocol.live_mode(args[1], args[2])
            elif mode == DeviceMode.REGISTER:
                self.register_device()
            else:
                assert self._wacom_protocol is not None
                self._wacom_protocol.retrieve_data()
        except WacomException as e:
            logger.error(f'**** Exception: {e} ****')
            exception = e
        finally:
            self._is_running = False
            self.emit('done', exception)

    def start_listen(self):
        self.thread = threading.Thread(target=self._run, args=(DeviceMode.LISTEN,))
        self.thread.start()

    def start_live(self, uhid_fd):
        self.thread = threading.Thread(target=self._run, args=(DeviceMode.LIVE, True, uhid_fd))
        self.thread.start()

    def stop_live(self):
        self.thread = threading.Thread(target=self._run, args=(DeviceMode.LIVE, False, -1))
        self.thread.start()

    def start_register(self):
        self.thread = threading.Thread(target=self._run, args=(DeviceMode.REGISTER,))
        self.thread.start()
