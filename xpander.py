#!/usr/bin/env python3

import os
import logging
from gi.repository import Gtk, AppIndicator3
from lib import conf, manager, service, XInterface, gtkui

Logger = logging.getLogger('Xpander')

conf._conf_manager = manager.Conf()
phrases_manager = manager.Phrases()
conf._service = service.Service()
conf._interface = XInterface.Interface()
manager.grab_hotkeys()
conf._service.start()
conf._interface.start()
gtkui.Indicator()
