TuhiGui
=======

Tuhi is a GUI to the Tuhi DBus daemon that connects to and fetches the data
from the Wacom ink range (Spark, Slate, Folio, Intuos Paper, ...). The data
is converted to SVG and users can save it on disk.

For more info about Tuhi see: https://github.com/tuhiproject/tuhi


Building TuhiGUI
----------------

```
 $> git clone http://github.com/tuhiproject/tuhigui
 $> cd tuhigui
 $> meson builddir
 $> ninja -C builddir
 $> ./builddir/tuhigui.devel
```

TuhiGui requires Python v3.6 or above.

Install TuhiGUI
---------------

```
 $> git clone http://github.com/tuhiproject/tuhigui
 $> cd tuhigui
 $> meson builddir
 $> ninja -C builddir install
 $> tuhigui
```

TuhiGui requires Python v3.6 or above.

License
-------

TuhiGui is licensed under the GPLv2 or later.
