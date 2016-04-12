#!/usr/bin/env python3
"""Provides namespace for configuration, as well as default values."""

import os
import sys
import logging


# Logging
if len(sys.argv) > 1:
	if sys.argv[1] == '-l' or sys.argv[1] == '--logging':
		logging_level = logging.DEBUG
else:
	logging_level = logging.CRITICAL

# manager
_config_dir = os.path.expanduser('~/.Xpander')
phrases_dir = os.path.expanduser('~/.Xpander/Phrases')

# XInterface
window_title_lazy = True
