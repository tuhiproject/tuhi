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
from gi.repository import GObject, Gtk

import gi
gi.require_version("Gtk", "3.0")


@Gtk.Template(resource_path="/org/freedesktop/TuhiGui/ui/ErrorPerspective.ui")
class ErrorPerspective(Gtk.Box):
    __gtype_name__ = "ErrorPerspective"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @GObject.Property
    def name(self):
        return "error_perspective"
