#!/usr/bin/env python3
"""Provides namespace for configuration, as well as default values."""

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
_config_dir = os.path.expanduser('~/.Xpander')
phrases_dir = os.path.expanduser('~/.Xpander/Phrases')
#   Global hotkeys
_hotkeys = [('\t', ['NoModifier'])]
pause_service = ('p', ('<Shift>', '<Super>'))
show_manager = ('m', ('<Shift>', '<Super>'))

# GUI
warn_folder_delete = True

# XInterface
window_title_lazy = True
