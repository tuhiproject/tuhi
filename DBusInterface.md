DBus Interface
--------------

Tuhi has two main components. A DBus session daemon that handles
communication with the device and a GTK application that provides the
graphical user interface.


The DBus session daemon uses the following interface:

```
org.freedesktop.tuhi1.Manager

  Property: Devices (ao)
      Array of object paths to known (previously registered, but not necessarily
      connected) devices. Note that a "registered" device is one that has been
      initialized via the Wacom SmartPad custom protocol. A device does not
      need to be paired over Bluetooth to register.

  Property: Searching (b)
      Indicates whether the daemon is currently searching for devices.

      This property is set to True when a StartSearching() request initiates
      the search for device connections. When the StartSearching() request
      completes upon timeout, or when StopSearching() is called, the property
      is set to False.

      When a pariable device is found, the UnregisteredDevice signal is sent to
      the caller that initiated the search process.

      Read-only

  Property: JSONDataVersions (au)
      Specifies the JSON file format versions the server supports. The
      client must request one of these versions in Device.GetJSONData().

      Read-only, constant

  Method: StartSearch() -> ()
      Start searching for available devices ready for registering
      for an unspecified timeout. When the timeout expires or an error
      occurs, a SearchStopped signal is sent indicating success or error.

      If a client that successfully initated a listening process calls
      StartSearching() again, that call is ignored and no signal is
      generated for that call.

  Method: StopSearch() -> ()
      Stop listening to available devices ready for registering. If called after
      StartSearch() and before a SearchStopped signal has been received,
      this method triggers the SearchStopped signal. That signal indicates
      success or an error.

      If this method is called before StartSearch() or after the
      SearchStopped signal, it is ignored and no signal is generated.

      Note that between calling StopSearch() and the SearchStopped signal
      arriving, UnregisteredDevice signals may still arrive.

  Signal: UnregisteredDevice(o)
      Indicates that a device can be registered. This signal may be
      sent after a StartSearch() call and before SearchStopped(). This
      signal is sent once per available device and only to the client that
      initiated the search process with StartSearch.

      When this signal is sent, a org.freedesktop.tuhi1.Device object was
      created, the object path is the argument to this signal.

      A client must immediately call Register() on that object if
      registering with that object is desired. See the documentation for
      that interface for details.

      When the search timeout expires, the device may be removed by the
      daemon again. Note that until the device is registered, the device is not
      listed in the managers Devices property.

  Signal: SearchStopped(i)
      Sent when the search has stopped. An argument of 0 indicates a
      successful termination of the search process, either when a device
      has been registered or the timeout expired.

      If the errno is -EAGAIN, the daemon is already searching for devices
      on behalf of another client. In this case, this client should wait for
      the Searching property to change and StartSearching() once the
      property is set to False.

      Once this signal has been sent, all devices announced through
      UnregisteredDevice signals should be considered invalidated. Attempting to
      Register() one of the devices after the SearchStopped() signal may result
      in an error.

      In case of error, the argument is a negative errno.

org.freedesktop.tuhi1.Device

  Interface to a device known by tuhi. Each object in Manager.Devices
  implements this interface.

  Property: BlueZDevice (o)
      Object path to the org.bluez.Device1 device that is this device.
      Read-only

  Property: Dimensions (uu)
      The physical dimensions (width, height) in µm
      Read-only

  Property: BatteryPercent (u)
      The last known battery charge level in percent. This charge level is
      only accurate when the BatteryState is other than Unknown.

      When the BatteryState is Unknown and BatteryPercent is nonzero, the
      value is the last known percentage value.

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

  Property: Live(b)
      Indicates whether the device is currently in Live mode. When in live
      mode, the device does not store drawings internally for a later sync
      but instead fowards the events immediately, similar to a traditional
      graphics tablet. See StartLive() for more details.

      Read-only

  Method: Register() -> (i)
      Register the device. If the device is already registered, calls to
      this method immediately return success.

      Otherwise, the device is registered and this function returns success (0)
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

  Method: StartLive(fd: h) -> (i)
      Starts live mode on this device. This disables offline storage of
      drawing data on the device and instead switches the device to a mode
      where it immediately reports the pen data, similar to a traditional
      graphics tablet.

      The LiveStopped signal is sent when live mode terminates, either on
      success or with an error. A client should handle this signal to be
      notified of any errors.

      When live mode enables, the Live property is updated accordingly.

      If a client that successfully initated a listening process calls
      StartListening() again, that call is ignored and no signal is
      generated for that call.

      The fd argument is a file descriptor that will be used to forward
      events to. The format is the one used by the Linux kernel's UHID
      device, see linux/uhid.h for details.

  Method: StopLive() - >()
      Stop live mode on this device. If called after StartLive(), this
      method triggers the LiveStopped signal.  That signal indicates
      success or an error.

      If this method is called before StartLive() or after the LiveStopped
      signal, it is ignored and no signal is generated.

      Note that between calling StopLive() and the LiveStopped signal
      arriving, the device may still send events. It's the responsibility of
      the client to handle events until the LiveStopped signal arrives.

  Method: GetJSONData(file-version: u, timestamp: t) -> (s)
      Returns a JSON file with the drawings specified by the timestamp
      argument. The requested timestamp must be one of the entries in the
      DrawingsAvailable property value. The file-version argument specifies
      the file format version the client requests. See section JSON FILE
      FORMAT for the format of the returned data.

      Returns a string representing the JSON data from the last drawings or
      the empty string if the timestamp is not available or the file format
      version is outside the server-supported range advertised in
      Manager.JSONDataVersions.

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

      If the error is -EBADE, the device is not ready for registering/in
      listening mode and registration/listening was requested. In
      this case, the client should indicate to the user that the device
      needs to be registered first or switched to listening mode.

      If the error is -EACCES, the device is not registered with the daemon
      or incorrectly registered. This may happen when the device was
      registered with another host since the last connection.

      The following other errnos may be sent by the daemon:
      -EPROTO: the daemon has encountered a protocol error with the device.
      -ETIME: timeout while communicating with the device.

      These errnos indicate a bug in the daemon, and the client should
      display a message to that effect.

  Signal: LiveStopped(i)
      Sent when live mode is stopped. An argument of 0 indicates a
      successful termination, i.e. in response to the client calling
      StopLive(). Otherwise, the argument is a negative errno
      indicating the type of error.

      If the errno is -EAGAIN, the daemon has already enabled live mode on
      device on behalf of another client. In this case, this client should
      wait for the Live property to change and StartLive() once the property
      is set to False.

      If the error is -EBADE, the device is not ready for live mode, most
      likely because it is in registration mode. In this case, the client
      should indicate to the user that the device needs to be registered
      first.

      If the error is -EACCES, the device is not registered with the daemon
      or incorrectly registered. This may happen when the device was
      registered with another host since the last connection.

      The following other errnos may be sent by the daemon:
      -EPROTO: the daemon has encountered a protocol error with the device.
      -ETIME: timeout while communicating with the device.

      These errnos indicate a bug in the daemon, and the client should
      display a message to that effect.

  Signal: SyncState(i)
      An enum to represent the current synchronization state of the device.
      When on (1), Tuhi is currently trying to download data from the
      device. When off (0), Tuhi is not currently connecting to the device.

      This signal should be used for UI feedback.

      This signal is only send when the device is **not** in Live mode.
```

JSON File Format
----------------

The current file format version is 1. A server may only support a subset of
historical file formats, this subset is advertized as list of versions in
the **org.freedesktop.tuhi1.Manager.JSONDataVersions** property. Likewise, a
client may only support a subset of the possible formats. A client should
always pick the highest format supported by both the client and the server.

Below is the example file format (with comments, not present in the real
files). The JSON objects are "drawing" (the root object), "strokes",
"points".  Pseudo-code is used to illustrate the objects in the file.

```
class Drawing {
        version: uint32
        devicename: string
        sessionid: string            // used for debugging
        dimensions: [uint32, uint32] // x/y physical dimensions in µm
        timestamp: uint64
        strokes: [ Stroke, Stroke, ...]
}
```

A session id is a random string that identifies a Tuhi session. This is
debugging information only, it makes it possible to associate a JSON file
with the corresponding sequence in the log. Do not use in clients.

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
   "sessionid": "somerandomstring-1",
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

Units used by this interface
----------------------------

* Physical distances for x/y axes are in µm from the sensor's top-left
  position. (Note that on the Spark and on the Slate at least, the sensor
  is turned 90 degrees clockwise, so (0,0) is at the 'natural' top-right
  corner)
* Stylus pressure is normalized to a range of [0, 0xffff], inclusive.
* Timestamps are in seconds in unix epoch, time offsets are in ms after the
  most recent timestamp.

