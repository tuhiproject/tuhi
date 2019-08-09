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

# Implementation of the BLE protocol of the Wacom SmartPad devices.
#
# Each device has a different set of functionalities and uses different
# opcodes and message formats. So the entry point is the Protocol class, and
# the messages can be accessed by key.
#
#     def my_callback(request, requires_reply=True, userdata=None, timeout=5):
#        if request is not None:
#            send_to_device(request)
#        if requires_reply:
#            return read_from device() or eventually_timeout()
#
#     p = Protocol(ProtocolVersion.INTUOS_PRO, my_callback, userdata)
#     m1 = P.get(Interactions.GET_NAME)
#     m2 = P.get(Interactions.SET_NAME, 'SomeName')
#
# Each message is defined by a string (see INTERACTIONS) and takes the obvious
# parameters where applicable.
# The message itself is the protocol-specific Msg, a single logical interaction
# with the device.
#
# The data exchange is prompted by the execute() function, which sets the
# attributes on the message and can be chained where appropriate, e.g.
#
#    name = m1.execute().name
#    if name != 'SomeName':
#       m2.execute()
#
# Because we generally expect everything to work fine and where it doesn't
# it affects a few things anyway, so error handling is via exceptions.
#
#    sequence = [m1, m2, m3, ...]
#    try:
#         for msg in sequence:
#             m.execute()
#    except AuthorizationError:
#       print("oops, we have the wrong uuid")
#

import binascii
import enum
import time


class Interactions(enum.Enum):
    '''All possible interactions with a device. Not all of these
    interactions may be available on any specific device.'''
    CONNECT = enum.auto()
    GET_NAME = enum.auto()
    SET_NAME = enum.auto()
    GET_TIME = enum.auto()
    SET_TIME = enum.auto()
    GET_FIRMWARE = enum.auto()
    GET_BATTERY = enum.auto()
    GET_DIMENSIONS = enum.auto()
    SET_MODE = enum.auto()
    GET_STROKES = enum.auto()
    GET_DATA_AVAILABLE = enum.auto()
    START_READING = enum.auto()
    ACK_TRANSACTION = enum.auto()
    REGISTER_PRESS_BUTTON = enum.auto()
    REGISTER_WAIT_FOR_BUTTON = enum.auto()
    REGISTER_COMPLETE = enum.auto()

    UNKNOWN_B1 = enum.auto()
    UNKNOWN_E3 = enum.auto()
    UNKNOWN_EC = enum.auto()


def as_hex_string(data):
    '''
    Returns the given byte-like to a debugging hex string in the form::

        12 ab 34 cd 05 ..

    Supports bytes and lists of integers.
    '''
    if isinstance(data, bytes):
        hx = binascii.hexlify(data).decode('ascii')
        return ' '.join([''.join(x) for x in zip(hx[::2], hx[1::2])])
    elif isinstance(data, list):
        return ' '.join([f'{x:02x}' for x in data])

    raise ValueError('Unsupported data format {data.__class__} for {data}')


def _get_protocol_dictionary(protocol):
    '''
    Returns a dict with the messages available for devices speaking that
    particular protocol. These are classes, not objects, instantiate as
    required. Usage::

        pdict = get_protocol_dictionary(ProtocolVersion.ANY)
        m = pdict[Interactions.GET_NAME]
        print(m().execute().name)
        m = pdict[Interactions.SET_NAME]
        m('mynewname').execute()

    The list of functions (``GET_NAME`` in the above example) depends on the
    implementation state and may vary between devices.
    '''
    # Load all classes from this module
    import sys
    import inspect
    classes = inspect.getmembers(sys.modules[__name__],
                                 lambda member: inspect.isclass(member) and
                                     member.__module__ == __name__) # NOQA
    # Filter to the ones with Msg as base class
    msgs = []
    for name, cls in classes:
        if cls == Msg:
            continue
        base_classes = inspect.getmro(cls)
        if Msg not in base_classes:
            continue
        msgs.append(cls)

    # Now compile the protocol-specific LUT for all functions that we
    # suppport
    pdict = {}
    for cls in msgs:
        assert cls.opcode is not None
        assert cls.interaction
        assert cls.protocol >= ProtocolVersion.ANY

        if cls.protocol > protocol:
            continue

        # Only take the latest version of a message
        if cls.interaction in pdict and cls.protocol < pdict[cls.interaction].protocol:
            continue
        pdict[cls.interaction] = cls
    return pdict


@enum.unique
class ProtocolVersion(enum.IntEnum):
    '''
    Protocol version numbers, named after the devices first encountered
    on. These version numbers are purely for sorting between devices, i.e.
    do not use the numeric values of this enum. That value may change
    if we discover more devices that have states in between.

    The exact behavior of each protocol is varied, but

    * opcodes may differ between protocol versions,
    * the data inside a message may differ between versions, nd
    * some functionality may only be available in some versions but not
      others.
    '''
    ANY = 0
    SPARK = 1
    SLATE = 2
    INTUOS_PRO = 3


class Mode(enum.IntEnum):
    '''
    The mode the tablet is in. ``LIVE`` mode is when the tablet reports pen
    strokes immediately. ``IDLE`` is the live mode but without reporting.
    ``PAPER`` is the normal mode, i.e. where we download drawings.
    '''
    LIVE = 0x00
    PAPER = 0x01
    IDLE = 0x02


class Protocol(object):
    '''
    The main communication class.

    :param protocol_version: a :class:`ProtocolVersion`
    :param callback: the callback to invoke for any messages
    :param userdata: optional data argument provided to the callback function
    '''
    def __init__(self, protocol_version, callback, userdata=None):
        self.protocol_version = protocol_version
        self.callback = callback
        self.userdata = userdata
        self.lut = _get_protocol_dictionary(protocol_version)

    def get(self, key, *args, **kwargs):
        '''
        Return the message with the given :class:`Interactions` key. This
        only returns the message but does not execute it. In most cases,
        you want to use :func:`execute` instead.
        '''
        kwargs['callback'] = self.callback
        kwargs['userdata'] = self.userdata
        msg = self.lut[key]
        return msg(*args, **kwargs)

    def execute(self, key, *args, **kwargs):
        '''
        Execute the message with the given :class:`Interactions` key and (where
        applicable) the arguments. This returns the already executed message
        that has the attributes you'd expect.
        '''
        return self.get(key, *args, **kwargs).execute()


class NordicData(list):
    '''
    A set of bytes as expected by the Nordic controller on the device.
    First byte is the opcode, second byte is the data length, rest is data.

    This is an abstraction of a list. Instantiate with the full raw data,
    the list contents will just be the data bytes:

    >>> data = NordicData([0xab, 4, 0x1, 0x2, 0x3, 0x4])
    >>> data
    [1, 2, 3, 4]
    >>> data.opcode
    0xab
    >>> data.length
    4
    >>> len(data)
    4

    .. attribute:: opcode

        The opcode for this message

    .. attribute:: length

        The data length of this message. This field is guaranteed to be
        equivalent to len(data) or an exception is raised.

    '''
    def __init__(self, bs):
        data = bs[2:]
        super().__init__(data)
        self.opcode = bs[0]
        self.length = bs[1]
        if self.length != len(data):
            raise UnexpectedDataError(bs, f'Invalid data: length field {self.length}, data length is {len(data)}')

    def __repr__(self):
        return f'{self.opcode:02x} / {self.length:02x} / {as_hex_string(self)}'


class ProtocolError(Exception):
    '''
    Base class for all Tuhi-protocol related errors.
    '''
    def __init__(self, message=None):
        self.message = message


class AuthorizationError(Exception):
    '''
    The device does not recognize our UUID.
    '''
    pass


class UnexpectedReply(ProtocolError):
    '''
    Exception thrown when the reply from the device does not match the
    opcodes we expected.

    This is not an error coming from the device, this is an
    implementation bug.

    .. attribute:: msg

        The Message that caused the unexpected reply.
    '''
    def __init__(self, msg, message=None):
        super().__init__(message)
        self.msg = msg

    def __repr__(self):
        return f'{self.__class__}: {self.msg}: {self.message}'


class UnexpectedDataError(ProtocolError):
    '''
    Exception thrown when the data is invalid. This is either a bug in our
    parsing or a genuine issue with the tablet, but more likely the former.

    This is not an error coming from the device, this is an
    implementation bug.

    .. attribute:: bytes

        The raw bytes that caused the unexpected data.
    '''
    def __init__(self, bytes, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bytes = bytes

    def __repr__(self):
        return f'{self.__class__}: {self.bytes} - {self.message}'


class DeviceError(ProtocolError):
    '''
    The device replied with an error. Check the error code for which error
    exactly happened.

    .. attribute:: errorcode

        An error code indicating which error occured on the device.

    '''
    class ErrorCode(enum.IntEnum):
        '''
        List of protocol errors as used by the Device.

        The error code ``SUCCESS`` is provided for convenience only, it is
        filtered by the implementation and not used in an actual exception.
        '''
        SUCCESS = 0x0
        GENERAL_ERROR = 0x1
        INVALID_STATE = 0x2
        READ_ONLY_PARAM = 0x3
        COMMAND_NOT_SUPPORTED = 0x4

    def __init__(self, errorcode, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errorcode = DeviceError.ErrorCode(errorcode)


class Msg(object):
    '''
    A single logical interaction (request + reply) with the Wacom device.
    In some cases a :class:`Msg` may issue multiple requests and replies as
    one logical unit, but that should be considered an implementation
    detail.

    :param callback: The callback to invoke to talk to the device. This
                     function must take one :class:`NordicData` and an
                     optional userdata argument and return one
                     :class:`NordicData` with the reply.
    :param userdata: The data passed to the callback.

    .. attribute:: request

        The :class:`NordicData` sent to the device

    .. attribute:: reply

        The :class:`NordicData` returned to the device

    .. attribute:: errorcode

        The :class:`DeviceError.ErrorCodeNordicData` from this message.

    '''
    opcode = None
    ''' The message-specific opcode. Must be defined in the subclass '''
    protocol = ProtocolVersion.ANY
    '''Minimum supported protocol version'''
    interaction = None
    '''The dictionary name for this interaction (e.g. ``GET_TIME``). Must be
       defined in the subclass'''
    requires_reply = True
    '''True if this message requires the caller to wait for a reply from the
       device.'''
    requires_request = True
    '''True if this message sends something to the device.'''

    OPCODE_NOOP = 'noop'
    '''A custom opcode for a noop function. Used where functionality was
       removed in later versions but to keep the caller stack simpler, we
       just provide a noop Msg.'''

    def __init__(self, callback, userdata=None, timeout=None):
        super().__init__()
        assert self.opcode is not None
        assert self.protocol is not None
        assert self.interaction is not None
        self._callback = callback
        self.errorcode = None
        self.userdata = userdata
        self.timeout = timeout
        self.args = [0x00]  # Empty messages don't exist

    @property
    def args(self):
        '''
        The arguments sent to the device as list of integers. Default is
        [0x00], i.e. a message of length 1 with a constant 0 as argument.
        '''
        return self._args

    @args.setter
    def args(self, args):
        self._args = args

    def _handle_reply(self, reply):
        '''Override this in the subclass to handle the reply.

        This is the default reply handler that deals with the 0xb3 ACK/Error
        messages and throws the respective exceptions.

        :param reply: A :class:`NordicData` object
        '''
        if reply.opcode != 0xb3:
            raise UnexpectedReply(self)

        if reply[0] != 0x00:
            raise DeviceError(reply[0])

    def execute(self):
        '''
        The function to trigger the actual communication. This function
        succeeds or raises a Wacom*Exception on error.
        '''
        if self.opcode == Msg.OPCODE_NOOP:
            return self  # allow chaining

        self.request = NordicData([self.opcode, len(self.args or []), *(self.args or [])])
        self.reply = self._callback(request=self.request if self.requires_request else None,
                                    requires_reply=self.requires_reply,
                                    timeout=self.timeout or None,
                                    userdata=self.userdata)
        if self.requires_reply:
            try:
                self._handle_reply(self.reply)
                # no exception? we can assume success
                self.errorcode = DeviceError.ErrorCode.SUCCESS
            except DeviceError as e:
                self.errorcode = e.errorcode
                raise e
        return self  # allow chaining

    def __repr__(self):
        return f'{self.__class__}: {self.interaction} - {self.request} → {self.reply}'


class MsgConnectIntuosPro(Msg):
    interaction = Interactions.CONNECT
    opcode = 0xe6
    protocol = ProtocolVersion.INTUOS_PRO

    def __init__(self, uuid, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uuid = uuid
        self.args = [int(i) for i in binascii.unhexlify(uuid)]
        if len(self.args) != 6:
            raise ValueError('UUID must be 6 bytes long')

    def _handle_reply(self, reply):
        if reply.opcode == 0x50:
            # maybe check reply.data == the uuid we sent
            pass  # success
        elif reply.opcode == 0x51:
            # first 6 bytes are the uuuid we just sent
            reason = reply[6]
            if reason in [0x00, 0x03]:  # invalid state
                raise DeviceError(DeviceError.ErrorCode.INVALID_STATE)
            elif reason in [0x01, 0x02]:  # incorrect uuuid
                raise AuthorizationError()
            raise UnexpectedReply(reply, message=f'Unknown error code: {reason}')
        else:
            raise UnexpectedReply(reply)


class MsgConnectSpark(Msg):
    interaction = Interactions.CONNECT
    opcode = 0xe6

    def __init__(self, uuid, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uuid = uuid
        self.args = [int(i) for i in binascii.unhexlify(uuid)]
        if len(self.args) != 6:
            raise ValueError('UUID must be 6 bytes long')

        # uses the default 0xb3 handler


class MsgGetName(Msg):
    '''
    .. attribute:: name

        The device name as reported by the device
    '''
    interaction = Interactions.GET_NAME
    opcode = 0xbb
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xbc:
            raise UnexpectedReply(f'Unknown reply: {reply.opcode}')
        self.name = bytes(reply).decode('utf-8')


class MsgGetNameIntuosPro(Msg):
    '''
    .. attribute:: name

        The device name as reported by the device
    '''
    interaction = Interactions.GET_NAME
    opcode = 0xdb
    protocol = ProtocolVersion.INTUOS_PRO

    def _handle_reply(self, reply):
        if reply.opcode != 0xbc:
            raise UnexpectedReply(self)
        self.name = bytes(reply).decode('utf-8')


class MsgSetName(Msg):
    '''
    :param name: The device name to set on the device

    .. attribute:: name

        The device name as set with this request
    '''
    interaction = Interactions.SET_NAME
    opcode = 0xbb
    protocol = ProtocolVersion.ANY

    def __init__(self, name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On the Spark, the name needs a trailing linebreak, otherwise the
        # firmware gets confused.
        self.args = [ord(c) for c in name] + [0x0a]

    # uses the default 0xb3 handler


class MsgSetNameIntuosPro(Msg):
    '''
    :param name: The device name to set on the device

    .. attribute:: name

        The device name as set with this request
    '''
    interaction = Interactions.SET_NAME
    opcode = 0xdb
    protocol = ProtocolVersion.INTUOS_PRO

    def __init__(self, name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [ord(c) for c in name]

    # uses the default 0xb3 handler


class MsgGetTime(Msg):
    '''
    .. attribute:: timestamp

        The time in seconds since UNIX epoch
    '''
    interaction = Interactions.GET_TIME
    opcode = 0xb6
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        import calendar

        if reply.opcode != 0xbd:
            raise UnexpectedReply(self)

        if reply.length != 6:
            raise UnexpectedDataError(f'Invalid reply length: expected 6, have {reply.length}')

        # Assumption: device is in UTC
        str_timestamp = ''.join([f'{b:02x}' for b in reply])
        t = time.strptime(str_timestamp, '%y%m%d%H%M%S')
        self.timestamp = calendar.timegm(t)


class MsgGetTimeIntuosPro(Msg):
    '''
    .. attribute:: timestamp

        The time in seconds since UNIX epoch
    '''
    interaction = Interactions.GET_TIME
    opcode = 0xd6
    protocol = ProtocolVersion.INTUOS_PRO

    def _handle_reply(self, reply):
        if reply.opcode != 0xbd:
            raise UnexpectedReply(self)

        if reply.length != 6:
            raise UnexpectedDataError(f'Invalid reply length: expected 6, have {reply.length}')

        self.timestamp = int.from_bytes(reply[0:4], byteorder='little')  # bytes[5:6] are ms


class MsgSetTime(Msg):
    '''
    :param timestamp: The current time in seconds since UNIX epoch

    .. attribute:: timestamp

        The time in seconds since UNIX epoch
    '''
    interaction = Interactions.SET_TIME
    opcode = 0xb6
    protocol = ProtocolVersion.ANY

    def __init__(self, timestamp, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamp = int(timestamp)
        # IntuosPro and later use the same request but a different time format
        current_time = time.strftime('%y%m%d%H%M%S', time.gmtime(self.timestamp))
        self.args = [int(i) for i in binascii.unhexlify(current_time)]

        # uses the default 0xb3 handler


class MsgSetTimeIntuosPro(Msg):
    '''
    :param timestamp: The current time in seconds since UNIX epoch

    .. attribute:: timestamp

        The time in seconds since UNIX epoch
    '''
    interaction = Interactions.SET_TIME
    opcode = 0xb6
    protocol = ProtocolVersion.INTUOS_PRO

    def __init__(self, timestamp, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamp = int(timestamp)
        self.args = list(self.timestamp.to_bytes(length=4, byteorder='little')) + [0x00, 0x00]

        # uses the default 0xb3 handler


class MsgGetFirmwareVersion(Msg):
    '''
    .. attribute:: firmware

        The firmware version as a string
    '''
    interaction = Interactions.GET_FIRMWARE
    opcode = 0xb7
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [0]
        self._lo = None
        self._hi = None

    def _handle_reply(self, reply):
        if reply.opcode != 0xb8:
            raise UnexpectedReply(self)

        if self.args[0] == 0:
            self._hi = ''.join([hex(d)[2:] for d in reply[1:]])
        elif self.args[0] == 1:
            self._lo = ''.join([hex(d)[2:] for d in reply[1:]])

        if self._hi is not None and self._lo is not None:
            self.firmware = f'{self._hi}-{self._lo}'

    def execute(self):
        # We need two requests with different args to get the full
        # firmware information
        self.args = [0]
        super().execute()
        self.args = [1]
        super().execute()
        return self


class MsgGetFirmwareVersionIntuosPro(Msg):
    '''
    .. attribute:: firmware

        The firmware version as a string
    '''
    interaction = Interactions.GET_FIRMWARE
    opcode = 0xb7
    protocol = ProtocolVersion.INTUOS_PRO

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lo = None
        self._hi = None

    def _handle_reply(self, reply):
        if reply.opcode != 0xb8:
            raise UnexpectedReply(self)

        if self.args[0] == 0:
            self._hi = ''.join([chr(d) for d in reply[1:]])
        elif self.args[0] == 1:
            self._lo = ''.join([chr(d) for d in reply[1:]])

        if self._hi is not None and self._lo is not None:
            self.firmware = f'{self._hi}-{self._lo}'

    def execute(self):
        # We need two requests with different args to get the full
        # firmware information
        self.args = [0]
        super().execute()
        self.args = [1]
        super().execute()
        return self


class MsgGetBattery(Msg):
    '''
    .. attribute:: battery_percent

        The battery charge in percent

    .. attribute:: battery_is_charging

        ``True`` if charging, ``False`` if discharging
    '''
    interaction = Interactions.GET_BATTERY
    opcode = 0xb9
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xba:
            raise UnexpectedReply(self)

        self.battery_percent = int(reply[0])
        self.battery_is_charging = reply[1] == 1


class MsgGetDimensions(Msg):
    '''
    .. attribute:: width

        The width of the tablet in points (mm/100)

    .. attribute:: height

        The height of the tablet in points (mm/100)
    '''
    interaction = Interactions.GET_DIMENSIONS
    opcode = 0xea
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xeb:
            raise UnexpectedReply(self)

        if self.args[0] not in [0x3, 0x4] or len(reply) != 6:
            raise UnexpectedDataError(reply)

        if self.args[0] == 0x3:
            self.width = int.from_bytes(reply[2:4], byteorder='little')
        if self.args[0] == 0x4:
            self.height = int.from_bytes(reply[2:4], byteorder='little')

    def execute(self):
        # We need two requests with different args to get both w and h
        self.args = [0x3, 0x00]
        super().execute()
        self.args = [0x4, 0x00]
        super().execute()
        return self


class MsgUnknownE3Command(Msg):
    interaction = Interactions.UNKNOWN_E3
    opcode = 0xe3
    protocol = ProtocolVersion.ANY

    # no arguments, uses the default 0xb3 handler


class MsgUnknownECCommand(Msg):
    interaction = Interactions.UNKNOWN_EC
    opcode = 0xec
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [0x06, 0x00, 0x00, 0x00, 0x00, 0x00]

    # uses the default 0xb3 handler


class MsgUnknownB1Command(Msg):
    interaction = Interactions.UNKNOWN_B1
    opcode = 0xb1
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [0x01]

    # uses the default 0xb3 handler


class MsgSetMode(Msg):
    '''
    :param mode: one of :class:`Mode`

    .. attribute:: mode

        The :class:`Mode` of the tablet
    '''
    interaction = Interactions.SET_MODE
    opcode = 0xb1
    protocol = ProtocolVersion.ANY

    def __init__(self, mode, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = Mode(mode)
        self.args = [int(mode)]

    # uses the default 0xb3 handler


class MsgGetStrokesSpark(Msg):
    '''
    .. attribute:: count

        The number of drawings available

    .. attribute:: timestamp

        The timestamp of the strokes sequence
    '''
    interaction = Interactions.GET_STROKES
    opcode = 0xc5
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.count = 0

    def _handle_reply(self, reply):
        # This is an odd message, we have one request but one or two
        # replies. The 0xc7 reply is sometimes missing, unclear though when.
        if reply.opcode == 0xc7:
            self.count = int.from_bytes(reply[0:4], byteorder='little')

            # Re-execute the message but this time without a new request
            self.requires_request = False
            self.execute()
            self.requires_request = True
        elif reply.opcode == 0xcd:
            import calendar

            str_timestamp = ''.join([f'{d:02x}' for d in reply])
            t = time.strptime(str_timestamp, '%y%m%d%H%M%S')
            self.timestamp = calendar.timegm(t)
        else:
            raise UnexpectedReply(reply)


class MsgGetStrokesSlate(Msg):
    '''
    .. attribute:: count

        The number of drawings available

    .. attribute:: timestamp

        The timestamp of the strokes sequence in seconds since UNIX epoch
    '''
    interaction = Interactions.GET_STROKES
    opcode = 0xcc
    protocol = ProtocolVersion.SLATE

    def _handle_reply(self, reply):
        import calendar

        if reply.opcode != 0xcf:
            raise UnexpectedReply(reply)

        self.count = int.from_bytes(reply[0:4], byteorder='little')
        str_timestamp = ''.join([f'{d:02x}' for d in reply[4:]])
        t = time.strptime(str_timestamp, '%y%m%d%H%M%S')
        self.timestamp = calendar.timegm(t)


class MsgGetStrokesIntuosPro(Msg):
    '''
    .. attribute:: count

        The number of drawings available

    .. attribute:: timestamp

        The timestamp of the strokes sequence
    '''
    interaction = Interactions.GET_STROKES
    opcode = 0xcc
    protocol = ProtocolVersion.INTUOS_PRO

    # same as the slate version, but the timestamp handling differs

    def _handle_reply(self, reply):
        if reply.opcode != 0xcf:
            raise UnexpectedReply(reply)

        self.count = int.from_bytes(reply[0:4], byteorder='little')
        seconds = int.from_bytes(reply[4:], byteorder='little')
        self.timestamp = seconds


class MsgGetDataAvailable(Msg):
    '''
    .. attribute:: count

        The number of drawings available
    '''
    interaction = Interactions.GET_DATA_AVAILABLE
    opcode = 0xc1
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xc2:
            raise UnexpectedReply(self)

        self.count = int.from_bytes(reply[0:2], byteorder='big')


class MsgGetDataAvailalbleSlate(Msg):
    '''
    .. attribute:: count

        The number of drawings available
    '''
    interaction = Interactions.GET_DATA_AVAILABLE
    opcode = 0xc1
    protocol = ProtocolVersion.SLATE

    def _handle_reply(self, reply):
        if reply.opcode != 0xc2:
            raise UnexpectedReply(self)

        self.count = int.from_bytes(reply[0:2], byteorder='little')


class MsgStartReading(Msg):
    interaction = Interactions.START_READING
    opcode = 0xc3
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xc8:
            raise UnexpectedReply(self)

        if reply[0] != 0xbe:
            raise UnexpectedDataError(reply)


class MsgAckTransaction(Msg):
    interaction = Interactions.ACK_TRANSACTION
    opcode = 0xca
    protocol = ProtocolVersion.ANY
    requires_reply = False


class MsgAckTransactionSlate(Msg):
    interaction = Interactions.ACK_TRANSACTION
    opcode = 0xca
    protocol = ProtocolVersion.SLATE

    # uses the default 0xb3 handler


class MsgRegisterComplete(Msg):
    interaction = Interactions.REGISTER_COMPLETE
    opcode = 0xe5
    protocol = ProtocolVersion.ANY

    # uses the default 0xb3 handler


class MsgRegisterCompleteSlate(Msg):
    '''A noop Msg. This message only exists for the Spark'''
    interaction = Interactions.REGISTER_COMPLETE
    opcode = Msg.OPCODE_NOOP
    protocol = ProtocolVersion.SLATE


class MsgRegisterPressButtonSpark(Msg):
    interaction = Interactions.REGISTER_PRESS_BUTTON
    opcode = 0xe3
    protocol = ProtocolVersion.ANY
    # Does not require a reply, the reply is sent in response to the
    # physical button press.
    requires_reply = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [0x01]


class MsgRegisterPressButtonSlateOrIntuosPro(Msg):
    interaction = Interactions.REGISTER_PRESS_BUTTON
    opcode = 0xe7
    protocol = ProtocolVersion.SLATE
    # Does not require a reply, the reply is sent in response to the
    # physical button press.
    requires_reply = False

    def __init__(self, uuid, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uuid = uuid
        self.args = [int(i) for i in binascii.unhexlify(uuid)]


class MsgRegisterWaitForButtonSpark(Msg):
    '''
    .. attribute:: protocol_version

    The protocol version used by this device, according to this message.

    '''
    interaction = Interactions.REGISTER_WAIT_FOR_BUTTON
    requires_request = False
    opcode = 0x00  # unused
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        kwargs['timeout'] = 10
        super().__init__(*args, **kwargs)
        self.protocol_version = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xe4:
            raise UnexpectedReply(reply)
        self.protocol_version = ProtocolVersion.SPARK


class MsgRegisterWaitForButtonSlateOrIntuosPro(Msg):
    '''
    .. attribute:: protocol_version

    The protocol version used by this device, according to this message.

    '''
    interaction = Interactions.REGISTER_WAIT_FOR_BUTTON
    requires_request = False
    opcode = 0x00  # unused
    protocol = ProtocolVersion.SLATE

    def __init__(self, *args, **kwargs):
        kwargs['timeout'] = 10
        super().__init__(*args, **kwargs)
        self.protocol_version = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode == 0xe4:
            self.protocol_version =  ProtocolVersion.SLATE
        elif reply.opcode == 0x53:
            self.protocol_version =  ProtocolVersion.INTUOS_PRO
        else:
            raise UnexpectedReply(reply)
