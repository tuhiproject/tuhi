![tuhi-logo](data/org.freedesktop.Tuhi.svg)

Tuhi
=====

Tuhi is a GTK application that connects to and fetches the data from the
Wacom ink range (Spark, Slate, Folio, Intuos Paper, ...). Users can save the
data as SVGs.

Tuhi is the Māori word for "to draw".

Supported Devices
-----------------

Devices tested and known to be supported:

* Bamboo Spark
* Bamboo Slate
* Intuos Pro Paper

Install Dependencies on Debian/Ubuntu
-------------------------------------

```
 $> sudo apt install meson python-gi-dev python3-svgwrite python3-xdg python3-gi-cairo gettext
```

Building Tuhi
-------------

To build and run Tuhi from the repository directly:

```
 $> git clone http://github.com/tuhiproject/tuhi
 $> cd tuhi
 $> meson builddir
 $> ninja -C builddir
 $> ./builddir/tuhi.devel
```

Tuhi requires Python v3.6 or above.

Installing Tuhi
---------------

To install and run Tuhi:

```
 $> git clone http://github.com/tuhiproject/tuhi
 $> cd tuhi
 $> meson builddir
 $> ninja -C builddir install
```

Run Tuhi with:

```
 $> tuhi
```

Tuhi requires Python v3.6 or above.

Flatpak
-------

```
 $> git clone http://github.com/tuhiproject/tuhi
 $> cd tuhi
 $> flatpak-builder flatpak_builddir org.freedesktop.Tuhi.json --install --user --force-clean
 $> flatpak run org.freedesktop.Tuhi
```

Note that Flatpak's containers use different XDG directories. This affects
Tuhi being able to remember devices and the data storage. Switching between
the Flatpak and a normal installation requires re-registering the device and
previously downloaded drawings may become inaccessible.

License
-------

Tuhi is licensed under the GPLv2 or later.

Registering devices
-------------------

For a device to work with Tuhi, it must be registered first. This is
achieved by holiding the device button for 6 or more seconds until the blue
LED starts blinking. Only in that mode can Tuhi detect it during
`Searching` and register it.

Registration sends a randomly generated UUID to the device. Subsequent
connections must use that UUID as identifier for the tablet device to
respond. Without knowing that UUID, other applications cannot connect.

A device can only be registered with one application at a time. Thus, when a
device is registered with Tuhi, other applications (e.g. Wacom Inkspace)
cannot not connect to the device anymore. Likewise, when registered with
another application, Tuhi cannot connect.

To make the tablet connect again, simply re-register with the respective
application or Tuhi, whichever desired.

This is not registering the device with some cloud service, vendor, or
other networked service. It is a communication between Tuhi and the firmware
on the device only. It is merely a process of "your ID is now $foo" followed
by "hi $foo, I want to connect".

The word "register" was chosen because "pairing" is already in use by
Bluetooth.

Packages
--------

Arch Linux: [tuhi-git](https://aur.archlinux.org/packages/tuhi-git/)

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
