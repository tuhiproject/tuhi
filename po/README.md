i18n
====

This directory contains the translations of Tuhi

For errors in translations, please [file an
issue](https://github.com/tuhiproject/tuhi/issues/new).

New or updated translations are always welcome. To start a new translation, run:

        $ meson translation-build
        $ ninja -C translation-build tuhi-pot
        # Now you can optionally remove the build directory
        $ rm -rf translation-build
        $ cp po/tuhi.pot po/$lang.po

where `$lang` is the language code of your target language, e.g. `nl` for Dutch
or `en_GB` for British English. Edit the
[LINGUAS](https://github.com/tuhiproject/tuhi/blob/master/tuhigui/po/LINGUAS) file and
add your language code, keeping the list sorted alphabetically.  Finally, open
the `.po` file you just created and translate all the strings. Don't forget to
fill in the information in the header!

To update an existing translation, run:

        $ meson translation-build
        $ ninja -C translation-build tuhi-update-po
        # Now you can optionally remove the build directory
        $ rm -rf translation-build

and update the `po/$lang.po` file of your target language.

When you are done translating, file a pull request on
[GitHub](https://github.com/tuhiproject/tuhi) or, if you don't know how to, [open
an issue](https://github.com/tuhiproject/tuhi/issues/new) and attach the `.po`
file there.

