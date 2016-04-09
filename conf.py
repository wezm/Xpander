#!/usr/bin/env python3

import sys
import logging


if len(sys.argv) > 1:
	if sys.argv[1] == '-l' or sys.argv[1] == '--logging':
		logging_level = logging.DEBUG
else:
	logging_level = logging.CRITICAL


window_title_lazy = True
