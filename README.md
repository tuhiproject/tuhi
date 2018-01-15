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

Units used by this interface
----------------------------

* Physical distances for x/y axes are in µm from the sensor's top-right
  position.
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
   connected) devices.

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

  Property: DrawingsAvailable (u)
      An integer indicating the number of drawings available. Drawings are
      zero-indexed, see GetJSONData().
      Read-only

  Property: Listening (b)
      Indicates whether the daemon is currently listening for the device.

      This property is set to True when a Listen() request initiates the
      search for device connections. When the Listen() request completes
      upon timeout, the property is set to False.
      Read-only

  Method: Listen() -> ()
      Listen for data from this device. This method starts listening for
      events on the device for an unspecified timeout. When the timeout
      expires, a ListenComplete signal is sent indicating success or error.

      This function requires the device to be connected and may require some
      interactivity (e.g. the user may need to press the sync button).

      When the device connects, the daemon downloads all drawings from the
      device and disconnects from the device. If successfull, the drawings
      are deleted from the device. The data is held by the daemon in
      non-persistent storage until the daemon is stopped or we run out of
      memory, whichever happens earlier.  Use GetJSONData() to retrieve the
      data from the daemon.

      When drawings become available from the device, the DrawingsAvailable
      property updates to the number of available drawings.

      When this function is called multiple times, any new data is appended
      to the existing list of drawings. Calling Listen() before a previous
      call has completed is silently ignored and does not reset the timeout.

      Returns: 0 on success or a negative errno on failure

  Method: GetJSONData(index: u) -> (s)
      Returns a JSON file with the drawings specified by the index argument.
      Drawings are zero-indexed and the requested index must be less than
      the DrawingsAvailable property value. See section JSON FILE FORMAT for
      the format of the returned data.

      Returns a string representing the JSON data from the last drawings or
      the empty string if no data is available or the index is invalid.
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
