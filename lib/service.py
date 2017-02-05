#!/usr/bin/env python3

import os
import collections
import threading
import queue
import subprocess
import shlex
import time
import logging
from gi.repository import GLib
from . import app, CONSTANTS, gtkui

MainLogger = logging.getLogger('Xpander')
Logger = MainLogger.getChild(__name__)


class Service(threading.Thread):

	def __init__(self):

		threading.Thread.__init__(self)
		self.daemon = True
		self.name = 'Listener service'
		self.phrases = app._phrases
		app._run_service = True
		self.__queue = queue.Queue()
		self.input_stack = collections.deque(maxlen=128)
		self.input_stack_index = 0
		self.CLEAR_STACK = {'XK_Left',
							'XK_Right',
							'XK_Up',
							'XK_Down',
							'XK_Home',
							'XK_End',
							'XK_Page_Up',
							'XK_Page_Down'}
		self.TRIGGER = {0: lambda char: not char.isalnum(),
						1: lambda char: char in {' ', '\n'},
						2: lambda char: char == '\t'}
		self.__caret_pos = None
		self.__last_expanded = None

	def __enqueue(self, method, *args):

		self.__queue.put_nowait((method, args))

	def run(self):

		while True:
			method, args = self.__queue.get()

			if method is None:
				Logger.info('Disabling main loop.')
				break

			try:
				method(*args)
			except Exception:
				Logger.exception("Error in the main loop.")

			self.__queue.task_done()

	def stop(self):

		self.__enqueue(None)

	def __del__(self):

		self.stop()

	def __call__(self, *args):

		self.__enqueue(self.handle_event, *args)

	def handle_event(self, keysym, keypress, modifiers):

		if keypress:
			modifier_state = (
				modifiers['<Super>'] or
				modifiers['<Control>'] or
				modifiers['<Alt>'])
			char = app._interface.lookup_string(keysym)
			if not modifier_state:
				if len(char) == 1:
					self.input_stack.append(char)
					self.__last_expanded = None
					if not char.isalnum():
						phrase = self.match_hotstring(char)
						if char == '\t' and not phrase:
							if self.__caret_pos:
								try:
									app._interface.caret_right(
										next(self.__caret_pos))
								except StopIteration:
									self.__caret_pos = None
									app._interface.send_string('\t')
							else:
								app._interface.send_string('\t')
						elif phrase:
							if char == '\t':
								self.trigger_phrase(phrase)
							else:
								self.trigger_phrase(phrase, include_char=char)
				elif char == 'XK_BackSpace':
					if app.backspace_undo:
						if self.__last_expanded:
							if self.__caret_pos:
								for caret_pos in self.__caret_pos:
									app._interface.caret_right(caret_pos)
								self.__caret_pos = None
							app._interface.send_backspace(
								len(self.__last_expanded) - 1)
							self.__last_expanded = None
					try:
						self.input_stack.pop()
					except IndexError:
						pass
				elif char == 'XK_Left':
					self.input_stack.rotate(1)
					self.input_stack_index += -1
					self.__last_expanded = None
					self.__caret_pos = None
				elif char == 'XK_Right':
					self.input_stack.rotate(-1)
					self.input_stack_index += 1
					self.__last_expanded = None
					self.__caret_pos = None
				elif char == 'XK_End':
					self.input_stack.rotate(self.input_stack_index)
					self.input_stack_index = 0
					self.__last_expanded = None
					self.__caret_pos = None
				elif char in self.CLEAR_STACK:
					self.input_stack.clear()
					self.input_stack_index = 0
					self.__last_expanded = None
					self.__caret_pos = None
			else:
				if char in self.CLEAR_STACK:
					self.input_stack.clear()
					self.input_stack_index = 0
					self.__last_expanded = None
					self.__caret_pos = None
				phrase = self.match_hotkey(char, modifiers)
				# Special handling for app's global hotkeys
				if phrase == '__pause_service':
					try:
						GLib.idle_add(
							app._menu_toggle_service.set_active,
							app._run_service)
					except:
						Logger.exception('Gtk error.')
						self.toggle_service()
				elif phrase == '__show_manager':
					try:
						GLib.idle_add(app._menu_show_manager.activate)
					except:
						Logger.exception('Gtk error.')
				elif phrase:
					self.trigger_phrase(phrase, remove=False)
					#~ self.__last_expanded = None

	def match_window_filter(self, phrase):

		filter_match = True
		if phrase['window_class']:
			if not app._interface.active_window_class in phrase['window_class']:
				filter_match = False
		if phrase['window_title']:
			if phrase['window_title'][1]:
				if not (phrase['window_title'][0] in
					app._interface.active_window_title):
					filter_match = False
			else:
				if not (phrase['window_title'][0].casefold() in
					app._interface.active_window_title.casefold()):
					filter_match = False
		return filter_match

	def match_hotstring(self, char):

		if app._run_service:
			for p_uuid in app._phrases:
				phrase = app._phrases[p_uuid]
				if phrase['hotstring'] is not None:
					if self.match_window_filter(phrase):
						if self.TRIGGER[phrase['trigger']](char):
							if ''.join(self.input_stack)[:-1].endswith(
								phrase['hotstring']):
								return phrase
			else:
				return None

	def match_hotkey(self, char, modifiers):

		if app._run_service:
			for p_uuid in self.phrases:
				phrase = self.phrases[p_uuid]
				if phrase['hotkey'] is not None:
					if self.match_window_filter(phrase):
						modifier_match = 0
						if (phrase['hotkey'][0] == char or
							phrase['hotkey'][0] == char.casefold()):
							for modifier in phrase['hotkey'][1]:
								if modifiers[modifier]:
									modifier_match += 1
							if len(phrase['hotkey'][1]) == modifier_match:
								return phrase
		# Special handling for app's global hotkeys
		if app.pause_service:
			if (char == app.pause_service[0] or
				char.casefold() == app.pause_service[0]):
				modifier_match = 0
				for modifier in app.pause_service[1]:
					if modifiers[modifier]:
						modifier_match += 1
				if len(app.pause_service[1]) == modifier_match:
					return '__pause_service'
		if app.show_manager:
			if (char == app.show_manager[0] or
				char.casefold() == app.show_manager[0]):
				modifier_match = 0
				for modifier in app.show_manager[1]:
					if modifiers[modifier]:
						modifier_match += 1
				if len(app.show_manager[1]) == modifier_match:
					return '__show_manager'

	def trigger_phrase(self, phrase, include_char='', remove=True):

		if phrase['script']:
			args = shlex.split(self.expand(phrase['body']))
			try:
				output = subprocess.check_output(
					args, universal_newlines=True, timeout=1)
			except subprocess.TimeoutExpired:
				Logger.exception('Script {} took too long to complete.'.format(
					os.path.join(phrase['path'], phrase['name'])))
				output = ''
			except FileNotFoundError:
				Logger.exception('Script {} contains invalid executable.'.format(
					os.path.join(phrase['path'], phrase['name'])))
				output = ''
			if remove:
				app._interface.send_backspace(
					len(phrase['hotstring']) + len(include_char))
			self.__last_expanded = output.strip() + include_char
			self.send_string(output.strip() + include_char, phrase['send'])
		else:
			if remove:
				app._interface.send_backspace(
					len(phrase['hotstring']) + (len(include_char)))
			string = self.expand(phrase['body'])
			self.__last_expanded = string +include_char
			self.send_string(string + include_char, phrase['send'])
			if self.__caret_pos:
				time.sleep(0.05)  # Events may get lost without a pause.
				app._interface.caret_left(next(self.__caret_pos))

	def expand(self, string):

		string = time.strftime(string)
		if '$C' in string:
			app._interface.store_clipboard()
			string = string.replace('$C', app._interface.clipboard_contents)
		if '$S' in string:
			app._interface.store_selection()
			string = string.replace('$S', app._interface.selection_contents)
		if '$|' in string:
			self.__caret_pos = self.get_caret_pos(string)
			string = string.replace('$|', '')
		return string

	def get_caret_pos(self, string):

		iteration = 0
		caret_count = string.count('$|')
		for carret_pos in range(caret_count):
			if not iteration:
				init_index = string.find('$|')
				index = len(string) - init_index - (caret_count * 2)
			else:
				index = string.find('$|') - init_index
				init_index += index
			string = string.replace('$|', '', 1)
			iteration += 1
			yield index

	def send_string(self, string, method):

		if method[0] == 0:
			app._interface.send_string(string)
		elif method[0] == 1:
			app._interface.send_string_clipboard(string, method[1])

	def toggle_service(self):

		Logger.info('Toggling service.')
		app._run_service = not app._run_service
