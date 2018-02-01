#!/usr/bin/env python
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

# This Python 2 program allows to translate btsnoop capture files to
# raw data coming from the various endpoints.
#
# You need to retrieve a btsnoop capture file from Android:
# * Set up your device you want to snoop with your Android phone
# * Install some Android file manager
# * Enable developer mode on your Android device
# * In Settings - General - Developer Options, enable "Bluetooth HCI snoop
#   log". This will log all bluetooth traffic to a file
#   `/Android/data/btsnoop_hci.log` (the location may differ, search for it)
# * Use the app to produce some bluetooth data you want to capture
# * disable bluetooth snooping
# * Copy the `btsnoop_hci.log` file into `Downloads`, connect the Android
#   device to a computer and download the file. Or mail it to yourself. Or
#   whatever other way you find to get that file onto your computer.

from __future__ import print_function

import sys
import binascii

# https://github.com/joekickass/python-btsnoop
import btsnoop.btsnoop.btsnoop as btsnoop
import btsnoop.bt.hci_uart as hci_uart
import btsnoop.bt.hci_acl as hci_acl
import btsnoop.bt.l2cap as l2cap
import btsnoop.bt.att as att

NORDIC_UART_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_TX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
NORDIC_UART_CHRC_RX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'

WACOM_LIVE_SERVICE_UUID = '00001523-1212-efde-1523-785feabcd123'
WACOM_CHRC_LIVE_PEN_DATA_UUID = '00001524-1212-efde-1523-785feabcd123'

WACOM_OFFLINE_SERVICE_UUID = 'ffee0001-bbaa-9988-7766-554433221100'
WACOM_OFFLINE_FW_DATA_UUID = 'ffee0002-bbaa-9988-7766-554433221100'
WACOM_OFFLINE_CHRC_PEN_DATA_UUID = 'ffee0003-bbaa-9988-7766-554433221100'

MYSTERIOUS_NOTIFICATION_SERVICE_UUID = '3a340720-c572-11e5-86c5-0002a5d5c51b'
MYSTERIOUS_NOTIFICATION_CHRC_UUID = '3a340721-c572-11e5-86c5-0002a5d5c51b'

# http://developer.nordicsemi.com/nRF51_SDK/nRF51_SDK_v7.x.x/doc/7.2.0/s110/html/a00071.html#ota_spec_sec
NORDIC_DFU_SERVICE_UUID = '00001530-1212-efde-1523-785feabcd123'
NORDIC_DFU_CTL_POINT_CHRC_UUID = '00001531-1212-efde-1523-785feabcd123'
NORDIC_DFU_PACKET_CHRC_UUID = '00001532-1212-efde-1523-785feabcd123'
NORDIC_DFU_UNKNONWN_CHRC_UUID = '00001534-1212-efde-1523-785feabcd123'

desc_uuids = {
    NORDIC_UART_SERVICE_UUID: 'NORDIC_UART_SERVICE_UUID',
    NORDIC_UART_CHRC_TX_UUID: 'Nordic UART TX  -->',
    NORDIC_UART_CHRC_RX_UUID: 'Nordic UART RX  <--',

    NORDIC_DFU_SERVICE_UUID: 'NORDIC_DFU_SERVICE_UUID',
    NORDIC_DFU_CTL_POINT_CHRC_UUID: 'Nordic DFU Ctl Point',
    NORDIC_DFU_PACKET_CHRC_UUID: 'Nordic DFU packet',
    NORDIC_DFU_UNKNONWN_CHRC_UUID: 'Nordic DFU Unknown',

    WACOM_LIVE_SERVICE_UUID: 'WACOM_LIVE_SERVICE_UUID',
    WACOM_CHRC_LIVE_PEN_DATA_UUID: 'Wacom Live <----',

    WACOM_OFFLINE_SERVICE_UUID: 'WACOM_OFFLINE_SERVICE_UUID',
    WACOM_OFFLINE_FW_DATA_UUID: 'Sending FW Data --->',
    WACOM_OFFLINE_CHRC_PEN_DATA_UUID: 'Wacom  RX  <----',

    MYSTERIOUS_NOTIFICATION_SERVICE_UUID: 'MYSTERIOUS_NOTIFICATION_SERVICE_UUID',
    MYSTERIOUS_NOTIFICATION_CHRC_UUID: 'Mysterious Notification',
}

handles = {}


def att_data_to_uuid(data):
    # reverse the string
    data = data[::-1]
    uuid = binascii.hexlify(data[:4]) + '-' + \
        binascii.hexlify(data[4:6]) + '-' + \
        binascii.hexlify(data[6:8]) + '-' + \
        binascii.hexlify(data[8:10]) + '-' + \
        binascii.hexlify(data[10:])
    return uuid


def get_rows(records):

    rows = []
    for record in records:

        seq_nbr = record[0]
        # time = record[3].strftime("%b-%d %H:%M:%S.%f")

        hci_pkt_type, hci_pkt_data = hci_uart.parse(record[4])
        # hci = hci_uart.type_to_str(hci_pkt_type)

        if hci_pkt_type != hci_uart.ACL_DATA:
            continue

        hci_data = hci_acl.parse(hci_pkt_data)
        l2cap_length, l2cap_cid, l2cap_data = l2cap.parse(hci_data[2], hci_data[4])

        if l2cap_cid != l2cap.L2CAP_CID_ATT:
            continue

        att_opcode, att_data = att.parse(l2cap_data)
        # cmd_evt_l2cap = att.opcode_to_str(att_opcode)
        data = att_data

        if att_opcode == 0x11:
            length = ord(data[0])
            if length == 20:
                start = binascii.hexlify(data[1:3])
                end = binascii.hexlify(data[3:5])
                print('{:>6} service handle from {} to {}: {} '.format(seq_nbr, start, end, att_data_to_uuid(data[5:])))
            continue
        elif att_opcode == 0x09:
            length = ord(data[0])
            if length == 21:
                value_handle = binascii.hexlify(data[4:6])
                uuid = att_data_to_uuid(data[6:])
                desc_uuid = uuid
                try:
                    desc_uuid = desc_uuids[uuid]
                except KeyError:
                    pass
                print('{:>6} chrc at handle {}: {}'.format(seq_nbr, value_handle, uuid))
                handles[value_handle] = (uuid, desc_uuid)
            continue

        if att_opcode not in [0x52, 0x1b]:
            continue

        data = binascii.hexlify(data)

        handle = data[:4]
        if handle not in handles:
            continue

        rows.append(['{:>6}'.format(seq_nbr), handles[handle][1], data[4:]])

    return rows


def main(filename):
    records = btsnoop.parse(filename)
    rows = get_rows(records)

    for r in rows:
        print(' '.join(r))


if __name__ == "__main__":
    if len(sys.argv) == 2:
        main(sys.argv[1])
    else:
        sys.exit(-1)
