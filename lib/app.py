#!/usr/bin/env python3
"""Provides shared namespace, as well as default configuration values."""

import os
import sys
import logging


# Logging
if len(sys.argv) > 1:
	if sys.argv[1] == '-l' or sys.argv[1] == '--logging':
		logging.basicConfig(level=logging.DEBUG)
else:
	logging.basicConfig(level=logging.CRITICAL)

# service
backspace_undo = True

# manager
_config_dir = os.path.expanduser('~/.config')
phrases_dir = os.path.expanduser('~/.phrases')
#   Global hotkeys
_hotkeys = [('\t', ['NoModifier'])]
pause_service = ('p', ('<Shift>', '<Super>'))
show_manager = ('m', ('<Shift>', '<Super>'))

# GUI
indicator_theme_light = True
warn_folder_delete = True

# XInterface
window_title_lazy = True
