#!/usr/bin/env python3

import os
import logging
import time
from gi.repository import Gtk, AppIndicator3
from lib import conf, manager

MainLogger = logging.getLogger('Xpander')
Logger = MainLogger.getChild(__name__)

indicator_icon = os.path.abspath('data/icons/xpander-status.svg')


class Indicator(object):

	def __init__(self):

		indicator = AppIndicator3.Indicator.new(
			'Xpander',
			indicator_icon,
			AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
		indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
		indicator.set_menu(self.build_menu())
		self.manager_ui = ManagerUI()
		Gtk.main()

	def build_menu(self):

		menu = Gtk.Menu()
		conf._menu_toggle_service = Gtk.CheckMenuItem('Pause expansion')
		conf._menu_toggle_service.connect('toggled', self.toggle_service)
		conf._menu_show_manager = Gtk.ImageMenuItem('Show Manager')
		icon_show_manager = Gtk.Image.new_from_icon_name('preferences-system', 22)
		conf._menu_show_manager.set_image(icon_show_manager)
		conf._menu_show_manager.connect('activate', self.show_manager)
		menu_quit = Gtk.ImageMenuItem('Quit')
		icon_quit = Gtk.Image.new_from_icon_name('application-exit', 22)
		menu_quit.set_image(icon_quit)
		menu_quit.connect('activate', self.quit)
		menu.append(conf._menu_toggle_service)
		menu.append(conf._menu_show_manager)
		menu.append(menu_quit)
		menu.show_all()
		return menu

	def toggle_service(self, menu_item):

		conf._service.toggle_service()

	def show_manager(self, menu_item):

		self.manager_ui.show_all()

	def quit(self, menu_item):

		conf._interface.stop()
		conf._service.stop()
		Gtk.main_quit()

class ManagerUI(Gtk.Window):

	def __init__(self):
		Gtk.Window.__init__(self, title="Xpander")
