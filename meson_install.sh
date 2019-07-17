#!/usr/bin/env sh

if [ -z $DESTDIR ]; then
	PREFIX=${MESON_INSTALL_PREFIX:-/usr}

    # Update icon cache
    gtk-update-icon-cache -f -t $PREFIX/share/icons/hicolor

    # Install new schemas
    #glib-compile-schemas $PREFIX/share/glib-2.0/schemas/
fi
