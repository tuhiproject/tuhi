TUHI
=====

Tuhi is a DBus session daemon that connects to and fetches the data from the
Wacom ink range (Spark, Slate, Folio, Intuos Paper, ...). The data is
provided to clients in the form of JSON, any conversion to other formats
like SVG must be done by the clients.

Tuhi is the Maori word for "to draw".

Supported Devices
-----------------

Devices tested and known to be supported:

* Bamboo Spark
* Bamboo Slate

Installation
------------

```
 $> git clone http://github.com/tuhiproject/tuhi
 $> cd tuhi
 $> python3 setup.py install
 $> tuhi
```

Note
----

TUHI requires Python v3.6 or above.

Units used by this interface
----------------------------

* Physical distances for x/y axes are in µm from the sensor's top-left
  position. (Note that on the Spark and on the Slate at least, the sensor
  is turned 90 degrees clockwise, so (0,0) is at the 'natural' top-right
  corner)
* Stylus pressure is normalized to a range of [0, 0xffff], inclusive.
* Timestamps are in seconds in unix epoch, time offsets are in ms after the
  most recent timestamp.

DBus Interface
--------------

The following interfaces are provided:

```
org.freedesktop.tuhi1.Manager

  Property: Devices (ao)
      Array of object paths to known (previously paired, but not necessarily
      connected) devices. Note that a "paired" device is one that has been
      initialized via the Wacom SmartPad custom protocol. This
      initialization is independent of the Bluetooth pairing process. A Tuhi
      paired device may or may not be paired over Bluetooth.

  Property: Searching (b)
      Indicates whether the daemon is currently searching for pairable devices.

      This property is set to True when a StartSearching() request initiates
      the search for device connections. When the StartSearching() request
      completes upon timeout, or when StopSearching() is called, the property
      is set to False.

      When a pariable device is found, the PairableDevice signal is sent to
      the caller that initiated the search process.

      Read-only

  Method: StartSearch() -> ()
      Start searching for available devices in pairing mode for an
      unspecified timeout. When the timeout expires or an error occurs, a
      SearchStopped signal is sent indicating success or error.

      If a client that successfully initated a listening process calls
      StartSearching() again, that call is ignored and no signal is
      generated for that call.

  Method: StopSearch() -> ()
      Stop listening to available devices in pairing mode. If called after
      StartSearch() and before a SearchStopped signal has been received,
      this method triggers the SearchStopped signal. That signal indicates
      success or an error.

      If this method is called before StartSearch() or after the
      SearchStopped signal, it is ignored and no signal is generated.

      Note that between calling StopSearch() and the SearchStopped signal
      arriving, PairableDevice signals may still arrive.

  Signal: PairableDevice(o)
      Indicates that a device is available for pairing. This signal may be
      sent after a StartSearch() call and before SearchStopped(). This
      signal is sent once per available device and only to the client that
      initiated the search process with StartSearch.

      When this signal is sent, a org.freedesktop.tuhi1.Device object was
      created, the object path is the argument to this signal.

      A client must immediately call Pair() on that object if pairing with
      that object is desired. See the documentation for that interface
      for details.

      When the search timeout expires, the device may be removed by the
      daemon again. Note that until the device is paired, the device is not
      listed in the managers Devices property.

  Signal: SearchStopped(i)
      Sent when the search has stopped. An argument of 0 indicates a
      successful termination of the search process, either when a device
      has been paired or the timeout expired.

      If the errno is -EAGAIN, the daemon is already searching for devices
      on behalf of another client. In this case, this client should wait for
      the Searching property to change and StartSearching() once the
      property is set to False.

      Once this signal has been sent, all devices announced through
      PairableDevice signals should be considered invalidated. Attempting to
      Pair() one of the devices after the SearchStopped() signal may result
      in an error.

      In case of error, the argument is a negative errno.

org.freedesktop.tuhi1.Device

  Interface to a device known by tuhi. Each object in Manager.Devices
  implements this interface.

  Property: Name (s)
      Human-readable name of the device.
      Read-only

  Property: Address (s)
      Bluetooth address of the device.
      Read-only

  Property: Dimensions (uu)
      The physical dimensions (width, height) in µm
      Read-only

  Property: BatteryPercent (u)
      The last known battery charge level in percent. This charge level is
      only valid when the BatteryState is other than Unknown.
      Read-only

  Property: BatteryState (u)
      An enum describing the battery state. Permitted enum values are

        0: Unknown
        1: Charging
        2: Discharging

      'Unknown' may refer to a state that could not be read, a state
      that has not yet been updated, or a state that has not updated within
      a daemon-internal time period. Thus, a device that is connected but
      does not regularly send battery updates may eventually switch to
      'Unknown'.

      Read-only

  Property: DrawingsAvailable (at)
      An array of timestamps of the available drawings. The timestamp of
      each drawing can be used as argument to GetJSONData(). Timestamps are
      in seconds since the Epoch and may be used to display information to
      the user or sort data.
      Read-only

  Property: Listening (b)
      Indicates whether the daemon is currently listening for the device.

      This property is set to True when a StartListening() request initiates
      the search for device connections. When the StartListening() request
      completes upon timeout, or when StopListening() is called, the property
      is set to False.

      When the user press the button on the device, the daemon connects
      to the device, downloads all drawings from the device and disconnects 
      from the device.

      If successfull, the drawings are deleted from the device. The data is
      held by the daemon in non-persistent storage until the daemon is stopped
      or we run out of memory, whichever happens earlier.
      Use GetJSONData() to retrieve the data from the daemon.

      DO NOT RELY ON THE DAEMON FOR PERMANENT STORAGE

      When drawings become available from the device, the DrawingsAvailable
      property updates to the number of available drawings.
      When the button is pressed multiple times, any new data is appended
      to the existing list of drawings as long as this property is True.

      Read-only

  Method: Pair() -> (i)
      Pair the device. If the device is already paired, calls to this method
      immediately return success.

      Otherwise, the device is paired and this function returns success (0)
      or a negative errno on failure.

  Method: StartListening() -> ()
      Listen for data from this device and connect to the device when it
      becomes available. The daemon listens to the device until the client
      calls StopListening() or the client disconnects, whichever happens
      earlier.

      The ListeningStopped signal is sent when the listening terminates,
      either on success or with an error. A client should handle this signal
      to be notified of any errors.

      When the daemon starts listening, the Listening property is updated
      accordingly.

      If a client that successfully initated a listening process calls
      StartListening() again, that call is ignored and no signal is
      generated for that call.

  Method: StopListening() -> ()
      Stop listening for data on this device. If called after
      StartListening(), this method triggers the ListenStopped signal.
      That signal indicates success or an error.

      If this method is called before StartListening() or after the
      ListeningStopped signal, it is ignored and no signal is generated.

      Note that between calling StopListening() and the ListeningStopped
      signal arriving, the property DrawingsAvailable may still be updated
      and it's the responsibility of the client to fetch the JSON data.

  Method: GetJSONData(timestamp: t) -> (s)
      Returns a JSON file with the drawings specified by the timestamp
      argument.  Drawings are zero-indexed and the requested index must be
      less than the DrawingsAvailable property value. See section JSON FILE
      FORMAT for the format of the returned data.

      Returns a string representing the JSON data from the last drawings or
      the empty string if no data is available or the timestamp is invalid.

  Signal: ButtonPressRequired()
      Sent when the user is expected to press the physical button on the
      device. A client should display a notification in response, if the
      user does not press the button during the (firmware-specific) timeout
      the current operation will fail.

  Signal: ListeningStopped(i)
      Sent when the listen process has stopped. An argument of 0 indicates a
      successful termination, i.e. in response to the client calling
      StopListening(). Otherwise, the argument is a negative errno
      indicating the type of error.

      If the errno is -EAGAIN, the daemon is already listening to the device
      on behalf of another client. In this case, this client should wait for
      the Listening property to change and StartListening() once the
      property is set to False.

      If the error is -EBADE, the device is not in pairing/listening mode
      and pairing/listening was requested. In this case, the client should
      indicate to the user that the device needs to be paired first or
      switched to listening mode.

      If the error is -EACCES, the device is not paired with the daemon or
      incorrectly paired. This may happen when the device was paired with
      another host since the last connection.

      The following other errnos may be sent by the daemon:
      -EPROTO: the daemon has encountered a protocol error with the device.
      -ETIME: timeout while communicating with the device.

      These errnos indicate a bug in the daemon, and the client should
      display a message to that effect.
```

JSON File Format
----------------

Below is the example file format (with comments, not present in the real
files). The JSON objects are "drawing" (the root object), "strokes",
"points".  Pseudo-code is used to illustrate the objects in the file.

```
class Drawing {
        version: uint32
        devicename: string
        dimensions: [uint32, uint32] // x/y physical dimensions in µm
        timestamp: uint64
        strokes: [ Stroke, Stroke, ...]
}
```

The **strokes** list contains all strokes of a single drawing, each stroke
consisting of a number of **points**.

```
class Stroke {
        points: [Point, Point, ...]
}
```

The **points** list contains the actual pen data.

```
class Point {
        toffset: uint32
        position: [uint32, uint32]
        pressure: uint32
}
```

An expanded file looks like this:

```
{
   "version" : 1,                       // JSON file format version number
   "devicename":  "Wacom Bamboo Spark", 
   "dimensions": [ 100000, 200000],      // width/height in µm
   "timestamp" : 12345,
   "strokes" : [
        {
            "points":  [
               // all items in a point are optional. Unknown dictionary
               // entries must be ignored as future devices may add
               // new axes.
               { "toffset" : 12366, "position" : [ 100, 200 ], "pressure" : 1000 },
               { "toffset" : 12368, "pressure" : 800 },
               { "toffset" : 12366, "position" : [ 120, 202 ] },
             ]
        },
        {  "points" : ... }
    ]
}
```

Device notes
============

When following any device notes below, replace the example bluetooth
addresses with your device's bluetooth address.

Bamboo Spark
------------

The Bluetooth connection on the Bamboo Spark behaves differently depending
on whether there are drawings pending or not. Generally, if no drawings are
pending, it is harder to connect to the device. Save yourself the pain and
make sure you have drawings pending while debugging.

### If the device has no drawings available:

* start `bluetoothctl`, commands below are to be issued in its interactive shell
* enable discovery mode (`scan on`)
* hold the Bamboo Spark button until the blue light is flashing
* You should see the device itself show up, but none of its services
  ```
  [NEW] Device E2:43:03:67:0E:01 Bamboo Spark
  ```
* While the LED is still flashing, `connect E2:43:03:67:0E:01`
  ```
  Attempting to connect to E2:43:03:67:0E:01
  [CHG] Device E2:43:03:67:0E:01 Connected: yes
  ... lots of services being resolved
  [CHG] Device E2:43:03:67:0E:01 ServicesResolved: yes
  [CHG] Device E2:43:03:67:0E:01 ServicesResolved: no
  [CHG] Device E2:43:03:67:0E:01 Connected: no
  ```
  Note how the device disconnects again at the end. Doesn't matter, now you
  have the services cached.
* Don't forget to eventually turn disable discovery mode off (`scan off`)

Now you have the device cached in bluez and you can work with that data.
However, you **cannot connect to the device while it has no drawings
pending**. Running `connect` and pressing the Bamboo Spark button shortly
does nothing.

### If the device has drawings available:

* start `bluetoothctl`, commands below are to be issued in its interactive shell
* enable discovery mode (`scan on`)
* press the Bamboo Spark button shortly
* You should see the device itself show up, but none of its services
  ```
  [NEW] Device E2:43:03:67:0E:01 Bamboo Spark
  ```
* `connect E2:43:03:67:0E:01`, then press the Bamboo Spark button
  ```
  Attempting to connect to E2:43:03:67:0E:01
  [CHG] Device E2:43:03:67:0E:01 Connected: yes
  ... lots of services being resolved
  [CHG] Device E2:43:03:67:0E:01 ServicesResolved: yes
  [CHG] Device E2:43:03:67:0E:01 ServicesResolved: no
  [CHG] Device E2:43:03:67:0E:01 Connected: no
  ```
  Note how the device disconnects again at the end. Doesn't matter, now you
  have the services cached.
* `connect E2:43:03:67:0E:01`, then press the Bamboo Spark button re-connects to the device
  The device will disconnect after approximately 10s. You need to start
  issuing the commands to talk to the controller before that happens.
* Don't forget to eventually turn disable discovery mode off (`scan off`)

You **must** run `connect` before pressing the button. Just pressing the
button does nothing unless bluez is trying to connect to the device.

**Warning**: A successful communication with the controller deletes the
drawings from the controller, so you may not be able to re-connect.
