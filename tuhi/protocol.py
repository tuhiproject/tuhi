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
import logging
import errno
from collections import namedtuple
from .util import list2hex

logger = logging.getLogger('tuhi.protocol')


def little_u16(x):
    '''
    Convert to or from a 16-bit integer to a little-endian 2-byte array. If
    passed an integer, the return value is a 2-byte array. If passed a
    2-byte array, the return value is a 16-bit integer.
    '''
    if isinstance(x, int):
        assert(x <= 0xffff and x >= 0x0000)
        return x.to_bytes(2, byteorder='little')
    else:
        assert(len(x) == 2)
        return int.from_bytes(x, byteorder='little')


def little_u32(x):
    '''
    Convert to or from a 16-bit integer to a little-endian 4-byte array. If
    passed an integer, the return value is a 4-byte array. If passed a
    4-byte array, the return value is a 16-bit integer.
    '''
    if isinstance(x, int):
        assert(x <= 0xffffffff and x >= 0x00000000)
        return x.to_bytes(4, byteorder='little')
    else:
        assert(len(x) == 4)
        return int.from_bytes(x, byteorder='little')


def little_u64(x):
    '''
    Convert to or from a 64-bit integer to a little-endian 4-byte array. If
    passed an integer, the return value is a 8-byte array. If passed a
    4-byte array, the return value is a 64-bit integer.
    '''
    if isinstance(x, int):
        assert(x <= 0xffffffffffffffff and x >= 0x0000000000000000)
        return x.to_bytes(8, byteorder='little')
    else:
        assert(len(x) == 8)
        return int.from_bytes(x, byteorder='little')


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
    GET_WIDTH = enum.auto()
    GET_HEIGHT = enum.auto()
    SET_MODE = enum.auto()
    GET_STROKES = enum.auto()
    AVAILABLE_FILES_COUNT = enum.auto()
    DOWNLOAD_OLDEST_FILE = enum.auto()
    DELETE_OLDEST_FILE = enum.auto()
    WAIT_FOR_END_READ = enum.auto()
    REGISTER_PRESS_BUTTON = enum.auto()
    REGISTER_WAIT_FOR_BUTTON = enum.auto()
    REGISTER_COMPLETE = enum.auto()
    SET_FILE_TRANSFER_REPORTING_TYPE = enum.auto()
    GET_POINT_SIZE = enum.auto()

    UNKNOWN_E3 = enum.auto()


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

    raise ValueError('Unsupported data format {data.__class__.__name__} for {data}')


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

    @classmethod
    def from_string(cls, string):
        '''
        Return the Enum value for the given string, allowing for different
        spellings. Specifically: INTUOS_PRO, intuos_pro and intuos-pro are
        all allowed for the ``INTUOS_PRO`` enum value.

        :raise ValueError: if the name cannot be mapped.
        '''
        names = {e.name: e for e in cls}
        if string in names:
            return names[string]

        names = {e.name.lower(): e for e in cls}
        if string in names:
            return names[string]

        names = {e.name.lower().replace('_', '-'): e for e in cls}
        if string in names:
            return names[string]

        raise ValueError(string)


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

    def parse_pen_data(self, data):
        '''
        Parse the given pen data. Returns a list of :class:`StrokeFile` objects.
        '''
        files = []
        while data:
            logger.debug(f'... remaining data ({len(data)}): {list2hex(data)}')
            sf = StrokeFile(data)
            files.append(sf)
            data = data[sf.bytesize:]
        return files


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

    .. attribute:: name

        The name of this message, may be None
    '''
    def __init__(self, bs, name=None):
        data = bs[2:]
        super().__init__(data)
        self.opcode = bs[0]
        self.length = bs[1]
        self.name = name
        if self.length != len(data):
            raise UnexpectedDataError(bs, f'Invalid data: length field {self.length}, data length is {len(data)}')

    def __str__(self):
        return f'{self.name if self.name else "UNKNOWN"} {self.opcode:02x} / {self.length:02x} / {as_hex_string(self)}'


class ProtocolError(Exception):
    '''
    Base class for all Tuhi-protocol related errors.
    '''
    errno = errno.ENOSYS

    def __init__(self, message=None):
        self.message = message


class MissingReplyError(ProtocolError):
    '''
    Thrown when we expected a reply but never got one. Usually caused by a
    timeout.
    '''
    errno = errno.ETIME

    def __init__(self, request, message=None):
        self.request = request

    def __str__(self):
        return f'Missing reply for request {self.request}. {self.message}'


class AuthorizationError(ProtocolError):
    '''
    The device does not recognize our UUID.
    '''
    errno = errno.EACCES


class UnexpectedReply(ProtocolError):
    '''
    Exception thrown when the reply from the device does not match the
    opcodes we expected.

    This is not an error coming from the device, this is an
    implementation bug.

    .. attribute:: msg

        The Message that caused the unexpected reply.
    '''
    errno = errno.EPROTO

    def __init__(self, msg, message=None):
        super().__init__(message)
        self.msg = msg

    def __str__(self):
        return f'{self.__class__.__name__}: {self.msg}: {self.message}'


class UnexpectedDataError(ProtocolError):
    '''
    Exception thrown when the data is invalid. This is either a bug in our
    parsing or a genuine issue with the tablet, but more likely the former.

    This is not an error coming from the device, this is an
    implementation bug.

    .. attribute:: bytes

        The raw bytes that caused the unexpected data.
    '''
    errno = errno.EPROTO

    def __init__(self, bytes, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bytes = bytes

    def __str__(self):
        return f'{self.__class__.__name__}: {self.bytes} - {self.message}'


class DeviceError(ProtocolError):
    '''
    The device replied with an error. Check the error code for which error
    exactly happened.

    .. attribute:: errorcode

        An error code indicating which error occured on the device.

    '''
    errno = errno.EPROTO

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
        AUTHORIZATION_ERROR = 0x7

    def __init__(self, errorcode, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errorcode = DeviceError.ErrorCode(errorcode)

        # All the other errors are something the user can't do
        # anything about.
        if self.errorcode == DeviceError.ErrorCode.INVALID_STATE:
            self.errno = errno.EBADE

    def __str__(self):
        return f'DeviceError.{self.errorcode.name}'


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
        '''
        Override this in the subclass to handle the reply. Note that the
        default 0xb3 message is handled automaticaly, this is only for
        non-default replies.

        No return value, just throw the appropriate exception on failure.

        :param reply: A :class:`NordicData` object
        '''
        raise NotImplementedError(f'{reply} needs customized handling')

    def execute(self):
        '''
        The function to trigger the actual communication. This function
        succeeds or raises a Wacom*Exception on error.
        '''
        if self.opcode == Msg.OPCODE_NOOP:
            return self  # allow chaining

        self.request = NordicData([self.opcode, len(self.args or []), *(self.args or [])],
                                  name=self.interaction.name)
        self.reply = self._callback(request=self.request if self.requires_request else None,
                                    requires_reply=self.requires_reply,
                                    timeout=self.timeout or None,
                                    userdata=self.userdata)
        if self.requires_reply:
            if self.reply is None:
                raise MissingReplyError(self.request)
            try:
                # 0xb3 is always handled by us, anything else requires a
                # custom reply handler
                if self.reply.opcode == 0xb3:
                    if self.reply[0] != 0x00:
                        raise DeviceError(self.reply[0])
                else:
                    self._handle_reply(self.reply)

                # no exception? we can assume success
                self.errorcode = DeviceError.ErrorCode.SUCCESS
            except DeviceError as e:
                self.errorcode = e.errorcode
                raise e
        return self  # allow chaining

    def __str__(self):
        return f'{self.__class__.__name__}: {self.interaction} - {self.request} → {self.reply}'


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

    def _handle_reply(self, reply):
        try:
            super()._handle_reply(reply)
        except DeviceError as e:
            if e.errorcode == DeviceError.ErrorCode.GENERAL_ERROR:
                raise AuthorizationError()
            raise e


class MsgConnectSlate(Msg):
    interaction = Interactions.CONNECT
    opcode = 0xe6
    protocol = ProtocolVersion.SLATE

    def __init__(self, uuid, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uuid = uuid
        self.args = [int(i) for i in binascii.unhexlify(uuid)]
        if len(self.args) != 6:
            raise ValueError('UUID must be 6 bytes long')

    def _handle_reply(self, reply):
        try:
            super()._handle_reply(reply)
        except DeviceError as e:
            # Same as spark but we get 0x7 as error code
            if e.errorcode == DeviceError.ErrorCode.AUTHORIZATION_ERROR:
                raise AuthorizationError()
            raise e


class MsgGetName(Msg):
    '''
    .. attribute:: name

        The device name as reported by the device
    '''
    interaction = Interactions.GET_NAME
    opcode = 0xbb
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = ""

    def _handle_reply(self, reply):
        if reply.opcode != 0xbc:
            raise UnexpectedReply(f'Unknown reply: {reply.opcode}')
        self.name += bytes(reply).decode('utf-8')
        if bytes(reply)[-1] != 0x0a:
            self.requires_request = False
            self.execute()
            self.requires_request = True


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

        self.timestamp = little_u32(reply[0:4])  # bytes[5:6] are ms


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
        self.args = list(little_u32(self.timestamp)) + [0x00, 0x00]

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


class MsgGetWidthSpark(Msg):
    '''
    This is a fake message. The Spark doesn't seem to have a getter for this
    one, it just times out. We just hardcode the value here.

    .. attribute:: width

        The width of the tablet in points (see :class:`MsgGetPointSize`)
    '''
    interaction = Interactions.GET_WIDTH
    opcode = Msg.OPCODE_NOOP
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.width = 21000


class MsgGetWidthSlate(Msg):
    '''
    .. attribute:: width

        The width of the tablet in points (see :class:`MsgGetPointSize`)
    '''
    interaction = Interactions.GET_WIDTH
    opcode = 0xea
    protocol = ProtocolVersion.SLATE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [0x03, 0x00]

    def _handle_reply(self, reply):
        if reply.opcode != 0xeb:
            raise UnexpectedReply(self)

        if little_u16(reply[0:2]) != 0x3 or len(reply) != 6:
            raise UnexpectedDataError(reply)

        self.width = little_u32(reply[2:6])


class MsgGetHeightSpark(Msg):
    '''
    This is a fake message. The Spark doesn't seem to have a getter for this
    one, it just times out. We just hardcode the value here.

    .. attribute:: height

        The height of the tablet in points (see :class:`MsgGetPointSize`)
    '''
    interaction = Interactions.GET_HEIGHT
    opcode = Msg.OPCODE_NOOP
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.height = 14800


class MsgGetHeightSlate(Msg):
    '''
    .. attribute:: height

        The height of the tablet in points (see :class:`MsgGetPointSize`)
    '''
    interaction = Interactions.GET_HEIGHT
    opcode = 0xea
    protocol = ProtocolVersion.SLATE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = little_u16(0x04)

    def _handle_reply(self, reply):
        if reply.opcode != 0xeb:
            raise UnexpectedReply(self)

        if little_u16(reply[0:2]) != 0x4 or len(reply) != 6:
            raise UnexpectedDataError(reply)

        self.height = little_u32(reply[2:6])


class MsgGetPointSizeSpark(Msg):
    '''
    This is a fake message. The Spark and Slate doesn't seem to have a
    getter for this one, it just times out. We just hardcode the value here.

    .. attribute:: point_size

        The point_size of the tablet in µm
    '''
    interaction = Interactions.GET_POINT_SIZE
    opcode = Msg.OPCODE_NOOP
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.point_size = 10


class MsgGetPointSize(Msg):
    '''
    .. attribute:: point_size

        The point size in micrometers
    '''
    interaction = Interactions.GET_POINT_SIZE
    opcode = 0xea
    protocol = ProtocolVersion.INTUOS_PRO

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = little_u16(0x14)

    def _handle_reply(self, reply):
        if reply.opcode != 0xeb:
            raise UnexpectedReply(self)

        if little_u16(reply[0:2]) != 0x14:
            raise UnexpectedDataError(reply)

        # This is strange. The return value is supposed to be the point size
        # but it's off by one. The IntuosPro returns 6 but a point size of 5
        # matches the physical dimensions. So let's assume there's a bug in
        # the firmware or the specs are wrong or something.
        self.point_size = little_u32(reply[2:6]) - 1


class MsgUnknownE3Command(Msg):
    interaction = Interactions.UNKNOWN_E3
    opcode = 0xe3
    protocol = ProtocolVersion.ANY

    # no arguments, uses the default 0xb3 handler


class MsgSetFileTransferReportingType(Msg):
    '''
    Changes where the device needs to send the data to.
    0x00 is on the FFEE0003 GATT.
    '''
    interaction = Interactions.SET_FILE_TRANSFER_REPORTING_TYPE
    opcode = 0xec
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [0x06, 0x00, 0x00, 0x00, 0x00, 0x00]

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
            self.count = int.from_bytes(reply[0:4], byteorder='big')

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

        self.count = little_u32(reply[0:4])
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

        self.count = little_u32(reply[0:4])
        seconds = little_u32(reply[4:8])
        self.timestamp = seconds


class MsgAvailableFilesCount(Msg):
    '''
    .. attribute:: count

        The number of drawings available
    '''
    interaction = Interactions.AVAILABLE_FILES_COUNT
    opcode = 0xc1
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xc2:
            raise UnexpectedReply(self)

        self.count = int.from_bytes(reply[0:2], byteorder='big')


class MsgAvailableFilesCountSlate(Msg):
    '''
    .. attribute:: count

        The number of drawings available
    '''
    interaction = Interactions.AVAILABLE_FILES_COUNT
    opcode = 0xc1
    protocol = ProtocolVersion.SLATE

    def _handle_reply(self, reply):
        if reply.opcode != 0xc2:
            raise UnexpectedReply(self)

        self.count = little_u16(reply[0:2])


class MsgDownloadOldestFile(Msg):
    interaction = Interactions.DOWNLOAD_OLDEST_FILE
    opcode = 0xc3
    protocol = ProtocolVersion.ANY

    def _handle_reply(self, reply):
        if reply.opcode != 0xc8:
            raise UnexpectedReply(self)

        if reply[0] != 0xbe:
            raise UnexpectedDataError(reply)


class MsgWaitForEndRead(Msg):
    '''
    .. attribute:: crc

        The checksum provided for the (out of band) pen data.
    '''
    interaction = Interactions.WAIT_FOR_END_READ
    requires_request = False
    opcode = 0x00  # unused
    protocol = ProtocolVersion.ANY

    def __init__(self, *args, **kwargs):
        super().__init__(timeout=5, *args, **kwargs)

    def _handle_reply(self, reply):
        if reply.opcode == 0xc8:
            if reply[0] != 0xed:
                raise UnexpectedDataError(reply, 'Expected c8 ed')
            pass  # nothing to do here
        elif reply.opcode == 0xc9:
            self.crc = int(binascii.hexlify(bytes(reply)), 16)
        else:
            raise UnexpectedReply(reply)

    def execute(self):
        # This is a double-reply , once c8, then c9
        super().execute()
        super().execute()
        return self


class MsgWaitForEndReadSlate(Msg):
    '''
    .. attribute:: crc

        The checksum provided for the (out of band) pen data.
    '''
    interaction = Interactions.WAIT_FOR_END_READ
    requires_request = False
    opcode = 0x00  # unused
    protocol = ProtocolVersion.SLATE

    def __init__(self, *args, **kwargs):
        super().__init__(timeout=5, *args, **kwargs)

    def _handle_reply(self, reply):
        if reply.opcode == 0xc8:
            if reply[0] != 0xed:
                raise UnexpectedDataError(reply, 'Expected c8 ed')
            crc = reply[1:]
            crc.reverse()
            self.crc = int(binascii.hexlify(bytes(crc)), 16)
        else:
            raise UnexpectedReply(reply)


class MsgDeleteOldestFile(Msg):
    interaction = Interactions.DELETE_OLDEST_FILE
    opcode = 0xca
    protocol = ProtocolVersion.ANY
    requires_reply = False


class MsgDeleteOldestFileSlate(Msg):
    interaction = Interactions.DELETE_OLDEST_FILE
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

    # uuid is unused, just there so it's compatible with the slate message
    def __init__(self, uuid=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.args = [0x01]
        self.uuid = uuid


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
            self.protocol_version = ProtocolVersion.SLATE
        elif reply.opcode == 0x53:
            self.protocol_version = ProtocolVersion.INTUOS_PRO
        else:
            raise UnexpectedReply(reply)


class StrokeParsingError(ProtocolError):
    def __init__(self, message, data=[]):
        self.message = message
        self.data = data

    def __str__(self):
        if self.data:
            datastr = f' data: {list2hex(self.data)}'
        else:
            datastr = ''
        return f'{self.message}{datastr}'


class StrokeDataType(enum.Enum):
    UNKNOWN = enum.auto()
    FILE_HEADER = enum.auto()
    STROKE_HEADER = enum.auto()
    STROKE_END = enum.auto()
    POINT = enum.auto()
    DELTA = enum.auto()
    EOF = enum.auto()
    LOST_POINT = enum.auto()

    @classmethod
    def identify(cls, data):
        '''
        Returns the identified packet type for the next packet.
        '''
        header = data[0]
        nbytes = bin(header).count('1')
        payload = data[1:1 + nbytes]

        # Note: the order of the checks below matters

        # Known file format headers. This is just a version number, I think.
        if data[0:4] == [0x67, 0x82, 0x69, 0x65] or \
           data[0:4] == [0x62, 0x38, 0x62, 0x74]:
            return StrokeDataType.FILE_HEADER

        # End of stroke, but can sometimes mean end of file too
        if data[0:7] == [0xfc, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]:
            return StrokeDataType.STROKE_END

        if payload == [0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]:
            return StrokeDataType.EOF

        # all special headers have the lowest two bits set
        if header & 0x3 == 0:
            return StrokeDataType.DELTA

        if not payload:
            return StrokeDataType.UNKNOWN

        if payload[0] == 0xfa or payload[0:3] == [0xff, 0xee, 0xee]:
            return StrokeDataType.STROKE_HEADER

        if payload[0:2] == [0xff, 0xff]:
            return StrokeDataType.POINT

        if payload[0:2] == [0xdd, 0xdd]:
            return StrokeDataType.LOST_POINT

        return StrokeDataType.UNKNOWN


class StrokeFile(object):
    '''
    Represents a single file as coming from the device. Note that pen data
    received from the device may include more than one file, this object is
    merely the first represented in this file.

    .. attribute:: bytesize

       The length in bytes of the data consumed.

    .. attribute:: timestamp

       Creation time of the drawing (when the button was pressed) or None where
       this is not supported by the device.

    .. attribute:: strokes

       A list of strokes, each a list of Point(x, y, p) namedtuples.
       Coordinates for the points are in absolute device units.

    '''
    def __init__(self, data):
        self.data = data
        self.file_header = StrokeFileHeader(data[:16])

        logger.debug(self.file_header)

        self.bytesize = self.file_header.size

        offset = self.file_header.size
        self.timestamp = self.file_header.timestamp
        self.bytesize += self._parse_data(data[offset:])

    def _parse_data(self, data):
        # the data formats we return
        Stroke = namedtuple('Stroke', ['points'])
        Point = namedtuple('Point', ['x', 'y', 'p'])

        # The Spark can have a delta on the first point in a file. Let's
        # default to 0, 0, 0 because I don't know what else could be
        # sensible here.
        last_point = Point(0, 0, 0)  # abs coords for most recent point
        last_delta = Point(0, 0, 0)  # delta accumulates

        strokes = []  # all strokes
        points = []  # Points of current strokes

        consumed = 0

        # Note about the below: this was largely reverse-engineered because
        # the specs we have access to are either ambiguous or outright wrong.
        #
        # First byte is a bitmask that seems to indicate how many bytes.
        #
        # Where the header byte has the lowest two bits set, it can be
        # one of several packages:
        # - a StrokeHeader [0xfa] to indicate a new stroke
        # - end of stroke - all payload bytes are 0xff
        # - lost point [0xdd, 0xdd] - firmware couldn't record a point
        # - a StrokePoint [0xff, 0xff] a fully specified point. Always
        #   the first after a StrokeHeader but may also appear elsewhere.
        #
        # Where the header byte has the lowest two bits on zero, it is
        # a StrokeDelta, a variable sized payload following the header,
        # values depend on the bits set in the header.
        #
        # In theory all the header packages should have a header of 0xff,
        # but they don't. End of stroke may have 0xfc, a StrokePoint
        # sometimes has 0xbf. It is unknown why.
        #
        # The StrokePoint is strange since if can sometimes contain deltas
        # (bitmask 0xbf). So it's just a delta with an extra two bytes for
        # headers, so what is the point of it? Presumably a firmware bug or
        # something.
        while data:
            packet_type = StrokeDataType.identify(data)
            logger.debug(f'Next data packet {packet_type.name}: {list2hex(data[:16])} …')

            packet = None
            if packet_type == StrokeDataType.UNKNOWN:
                packet = StrokePacketUnknown(data)
            elif packet_type == StrokeDataType.FILE_HEADER:
                # This code shouldn't be triggered, we handle the file
                # header outside this function.
                packet = StrokeFileHeader(data)
                logger.error(f'Unexpected file header at byte {consumed}: {packet}')
                break
            elif packet_type == StrokeDataType.STROKE_END:
                packet = StrokeEndOfStroke(data)
                if points:
                    strokes.append(Stroke(points))
                    points = []
            elif packet_type == StrokeDataType.EOF:
                # EOF means pack
                packet = StrokeEOF(data)
                if points:
                    strokes.append(Stroke(points))
                    points = []
                data = data[packet.size:]
                consumed += packet.size
                break
            elif packet_type == StrokeDataType.STROKE_HEADER:
                # New stroke means resetting delta and storing the last
                # stroke
                packet = StrokeHeader(data)
                last_delta = Point(0, 0, 0)
                if points:
                    strokes.append(Stroke(points))
                    points = []
            elif packet_type == StrokeDataType.LOST_POINT:
                # We don't yet handle lost points
                packet = StrokeLostPoint(data)
            elif (packet_type == StrokeDataType.POINT or
                  packet_type == StrokeDataType.DELTA):
                # POINT and DELTA *should* be two different packages but
                # sometimes a POINT includes a delta for a coordinate. So
                # all a POINT is is a delta with an added [0xff 0xff] after
                # the header byte. The StrokePoint packet hides this so we
                # can process both the same way.
                if packet_type == StrokeDataType.POINT:
                    packet = StrokePoint(data)
                else:
                    packet = StrokeDelta(data)

                # Compression algorithm in the device basically keeps a
                # cumulative delta so that
                # P0 = absolute x, y, z
                # P1 = P0 + d1
                # P2 = P0 + 2*d1 + d2
                # P3 = P0 + 3*d1 + 2*d2 + d3
                # And we use that here by just keeping the last delta
                # around, adding to it where necessary and then adding it to
                # the last point we have.
                #
                # Whenever we get an absolute coordinate, the delta resets
                # to 0. Since this is per axis, our fictional P4 may be:
                # P4(x) = P0 + 4*d1 + 3*d2 + 2*d3 + d4
                # P4(y) = P0 + 4*d1 + 2*d3 ... d2 and d4 are missing (zero)
                # P4(p) = P4(p) .... absolute
                dx, dy, dp = last_delta
                x, y, p = last_point
                if packet.dx is not None:
                    dx += packet.dx
                elif packet.x is not None:
                    x = packet.x
                    dx = 0

                if packet.dy is not None:
                    dy += packet.dy
                elif packet.y is not None:
                    y = packet.y
                    dy = 0

                if packet.dp is not None:
                    dp += packet.dp
                elif packet.p is not None:
                    p = packet.p
                    dp = 0

                # dx,dy,dp ... are cumulative deltas for this packet
                # x,y,p    ... most recent known abs coordinates
                # add those two together and we have the real coordinates
                # and the baseline for the next point
                last_delta = Point(dx, dy, dp)
                current_point = Point(x, y, p)
                last_point = Point(current_point.x + last_delta.x,
                                   current_point.y + last_delta.y,
                                   current_point.p + last_delta.p)
                logger.debug(f'Calculated point: {last_point}')
                points.append(last_point)
            else:
                # should never get here
                raise StrokeParsingError('Failed to parse', data[:16])

            logger.debug(f'Offset {consumed}: {packet}')
            consumed += packet.size
            data = data[packet.size:]

        self.strokes = strokes
        return consumed


class StrokePacket(object):
    '''
    .. attribute: size

        Size of the packet in bytes
    '''
    def __init__(self):
        self.size = 0


class StrokePacketUnknown(StrokePacket):
    def __init__(self, data):
        header = data[0]
        nbytes = bin(header).count('1')
        self.size = 1 + nbytes
        self.data = data[:self.size]

    def __str__(self):
        return f'Unknown packet: {list2hex(self.data)}'


class StrokeFileHeader(StrokePacket):
    '''
    Each data packet has a file header consisting of 4 bytes file version
    number and optionally extra data.

    .. attribute: timestamp

        The timestamp of this drawing or ``None`` where not available.

    .. attribute: nstrokes

        The count of strokes within this drawing or ``None`` where not
        available. This count is inaccurate anyway, so it should only be
        used for basic internal checks.

    '''
    def __init__(self, data):
        key = little_u32(data[:4])
        file_formats = {
            little_u32([0x67, 0x82, 0x69, 0x65]): self._parse_intuos_pro,
            little_u32([0x62, 0x38, 0x62, 0x74]): self._parse_spark,
        }

        self.timestamp = None
        self.nstrokes = None

        try:
            func = file_formats[key]
            func(data)
        except KeyError:
            raise StrokeParsingError('Unknown file format:', data[:4])

    def __str__(self):
        t = time.strftime("%y%m%d%H%M%S", time.gmtime(self.timestamp))
        return f'FileHeader: time: {t}, stroke count: {self.nstrokes}'

    def _parse_intuos_pro(self, data):
        self.timestamp = int.from_bytes(data[4:8], byteorder='little')
        # plus two bytes for ms, always zero
        self.nstrokes = int.from_bytes(data[10:14], byteorder='little')
        # plus two bytes always zero
        self.size = 16

    def _parse_spark(self, data):
        self.size = 4


class StrokeHeader(StrokePacket):
    '''
    .. attribute:: pen_id

        The pen serial number or 0 if none is set

    .. attribute:: pen_type

        The pen type

    .. attribute:: timestamp

        The timestamp of this stroke or None if none was recorded

    .. attribute:: time_offset

        The time offset in ms since powerup or None if this stroke has an
        absolute timestamp.

    .. attribute:: is_new_layer

        True if this stroke is on a new layer
    '''
    def __init__(self, data):
        header = data[0]
        payload = data[1:]
        self.size = bin(header).count('1') + 1
        if payload[0] == 0xfa:
            self._parse_intuos_pro(data, header, payload)
        elif payload[0:3] == [0xff, 0xee, 0xee]:
            self._parse_slate(data, header, payload)
        else:
            raise StrokeParsingError('Invalid StrokeHeader, expected ff fa or ff ee.', data[:8])

    def _parse_slate(self, data, header, payload):
        self.pen_id = 0
        self.pen_type = 0
        self.is_new_layer = False

        self.timestamp = None
        self.time_offset = little_u16(payload[4:6]) * 5  # in 5ms resolution

        # On the first stroke after the file header, this packet is 6 bytes
        # only. Other strokes have 8 bytes but the last two bytes are always
        # zero.

    def _parse_intuos_pro(self, data, header, payload):
        flags = payload[1]
        needs_pen_id = flags & 0x80
        self.pen_type = flags & 0x3f
        self.is_new_layer = (flags & 0x40) != 0
        self.pen_id = 0
        self.timestamp = int.from_bytes(payload[2:6], byteorder='little')
        self.time_offset = None
        # FIXME: plus two bytes for milis
        self.size = bin(header).count('1') + 1

        # if the pen id flag is set, the pen ID comes in the next 8-byte
        # packet (plus 0xff header)
        if needs_pen_id:
            pen_packet = data[self.size + 1:]
            if not pen_packet:
                raise StrokeParsingError('Missing pen ID packet')

            header = data[0]
            if header != 0xff:
                raise StrokeParsingError(f'Unexpected pen id packet header: {header}.', data[:9])

            nbytes = bin(header).count('1')
            self.pen_id = little_u64(pen_packet[:8])
            self.size += 1 + nbytes

    def __str__(self):
        if self.timestamp is not None:
            t = time.strftime('%y%m%d%H%M%S', time.gmtime(self.timestamp))
        else:
            t = time.strftime(f'boot+{self.time_offset/1000}s')
        return f'StrokeHeader: time: {t} new layer: {self.is_new_layer}, pen type: {self.pen_type}, pen id: {self.pen_id:#x}'


class StrokeDelta(object):
    '''
    .. attribute:: x

        The absolute x coordinate or None if this is packet contains a delta

    .. attribute:: y

        The absolute y coordinate or None if this is packet contains a delta

    .. attribute:: p

        The absolute pressure coordinate or None if this is packet contains a delta

    .. attribute:: dx

        The x delta or None if this is packet contains an absolute
        coordinate

    .. attribute:: dy

        The y delta or None if this is packet contains an absolute
        coordinate

    .. attribute:: dp

        The pressure delta or None if this is packet contains an absolute
        coordinate
    '''
    def __init__(self, data):
        def extract(mask, databytes):
            value = None
            delta = None
            size = 0
            if mask == 0:
                # No data for this coordinate
                pass
            elif mask == 1:
                # Supposedly not implemented by any device.
                #
                # If this would exist, it would throw off the byte count
                # anyway, so this cannot ever exist without breaking
                # everything.
                raise NotImplementedError('This device is not supposed to be exist')
            elif mask == 2:
                # 8 bit delta
                delta = int.from_bytes(bytes([databytes[0]]), byteorder='little', signed=True)
                if delta == 0:
                    raise StrokeParsingError('StrokeDelta: invalid delta of zero', data)
                assert delta != 0
                size = 1
            elif mask == 3:
                # full abs coordinate
                value = little_u16(databytes[:2])
                size = 2
            return value, delta, size

        if (data[0] & 0b11) != 0:
            raise NotImplementedError('LSB two bits set in mask - this is not supposed to happen')

        xmask = (data[0] & 0b00001100) >> 2
        ymask = (data[0] & 0b00110000) >> 4
        pmask = (data[0] & 0b11000000) >> 6

        offset = 1
        x, dx, size = extract(xmask, data[offset:])
        offset += size
        y, dy, size = extract(ymask, data[offset:])
        offset += size
        p, dp, size = extract(pmask, data[offset:])
        offset += size

        # Note: any of these will be None depending on the packet
        self.dx = dx
        self.dy = dy
        self.dp = dp
        self.x = x
        self.y = y
        self.p = p

        self.size = offset

    def __str__(self):
        def printstring(delta, abs):
            return f'{delta:+5d}' if delta is not None \
                        else f'{abs:5d}' if abs is not None \
                        else '     '  # noqa
        strx = printstring(self.dx, self.x)
        stry = printstring(self.dy, self.y)
        strp = printstring(self.dp, self.p)

        return f'StrokeDelta: {strx}/{stry} pressure: {strp}'


class StrokePoint(StrokeDelta):
    '''
    A full point identified by three coordinates (x, y, pressure) in
    absolute coordinates.
    '''
    def __init__(self, data):
        header = data[0]
        payload = data[1:]
        if payload[:2] != [0xff, 0xff]:
            raise StrokeParsingError('Invalid StrokePoint, expected ff ff ff', data[:9])

        # This is a wrapper around StrokeDelta which does the mask parsing.
        # In theory the StrokePoint would be a separate packet but it
        # occasionally uses a header other than 0xff. Which means the packet
        # is completely useless and shouldn't exist because now it's just a
        # StrokeDelta in the form of [header, 0xff, 0xff, payload] and the
        # 0xff just keep the room warm.

        # StrokeDelta assumes the bottom two bits are unset
        header &= ~0x3
        super().__init__([header] + payload[2:])
        self.size += 2

        # self.x = little_u16(data[2:4])
        # self.y = little_u16(data[4:6])
        # self.pressure = little_u16(data[6:8])

    def __str__(self):
        return f'StrokePoint: {self.x}/{self.y} pressure: {self.p}'


class StrokeEOF(StrokePacket):
    def __init__(self, data):
        header = data[0]
        payload = data[1:]
        nbytes = bin(header).count('1')
        if payload[:nbytes] != [0xff] * nbytes:
            raise StrokeParsingError('Invalid EOF, expected 0xff only', data[:9])
        self.size = nbytes + 1


class StrokeEndOfStroke(StrokePacket):
    def __init__(self, data):
        header = data[0]
        payload = data[1:]
        nbytes = bin(header).count('1')
        if payload[:nbytes] != [0xff] * nbytes:
            raise StrokeParsingError('Invalid EndOfStroke, expected 0xff only', data[:9])
        self.size = nbytes + 1
        self.data = data[:self.size]

    def __str__(self):
        return f'EndOfStroke: {list2hex(self.data)}'


class StrokeLostPoint(StrokePacket):
    '''
    Marker for lost points that the firmware couldn't record coordinates
    for.

    .. attribute:: nlost

        The number of points not recorded.
    '''
    def __init__(self, data):
        header = data[0]
        payload = data[1:]
        if payload[:2] != [0xdd, 0xdd]:
            raise StrokeParsingError('Invalid StrokeLostPoint, expected ff dd dd', data[:9])
        self.nlost = little_u16(payload[2:4])
        self.size = bin(header).count('1') + 1
