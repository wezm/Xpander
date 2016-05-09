# Xpander

## About

Xpander is a lightweight text expander for Linux written in python.

You type an abbreviation and it's automatically expanded to a predefined block
of text called a phrase. This is useful when filling out forms, coding
and whenever else you need to write the same block of text over and over.
Each phrase is stored as JSON file in a user configurable directory, default
is ~/.phrases.

Xpander features full support for multiple keyboard layouts,
filtering by window and hotkeys.

Xpander also supports token expansion, e.g.:

* $| marks where cursor will be placed after expansion;
	* you can define multiple cursor insertion points and switch through them
		with the <Tab\> key;
* $C is replaced by clipboard contents;
* %x is replaced by current date formatted to your locale;
	* custom date formatting is also available;
* you can see the full list of tokens by clicking on Insert dropdown in the
	manager window.

You can also mark a phrase as a command. In this case phrase contents are
interpreted as command line and it's output pasted instead.

## Installation and Dependencies

For multiple keyboard layout support Xpander relies on
[xkb-switch](https://github.com/ierton/xkb-switch), you can find binary
packages (debs) [here](https://github.com/OzymandiasTheGreat/xkb-switch/releases).

Other dependencies should be in the repositories for your distro:

`sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-glib-2.0 python3-xlib`

(You probably have most of these installed already if you're on a gnome based
distro.)

Recommended way to install Xpander is from [deb](https://github.com/OzymandiasTheGreat/Xpander/releases).

You can also install development version with pip:

`sudo pip3 install https://github.com/OzymandiasTheGreat/Xpander/archive/master.zip`

Note that editable and user installs don't quite work, because icons can't be
written to proper locations and it's mostly untested.
