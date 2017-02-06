#!/usr/bin/env python3

import os
import shutil
import threading
import json
import uuid
import time
import logging
from . import conf

MainLogger = logging.getLogger('Xpander')
Logger = MainLogger.getChild(__name__)


class Hotkeys:

	def grab_hotkey(self, hotkey):

		keycode = conf._interface.lookup_keycode(
			conf._interface.lookup_keysym(hotkey[0]))
		mask = 0
		for modifier in hotkey[1]:
			mask |= conf._interface.MODIFIER_MASK[modifier]
		conf._interface.grab_key(keycode, mask)


	def ungrab_hotkey(self, hotkey):

		keycode = conf._interface.lookup_keycode(
			conf._interface.lookup_keysym(hotkey[0]))
		mask = 0
		for modifier in hotkey[1]:
			mask |= conf._interface.MODIFIER_MASK[modifier]
		conf._interface.ungrab_key(keycode, mask)

	def grab_hotkeys(self):

		for hotkey in conf._hotkeys:
			self.grab_hotkey(hotkey)


	# NOTE: Appears unused
	def ungrab_hotkeys():

		for hotkey in conf._hotkeys:
			self.ungrab_hotkey(hotkey)


class Conf(object):

	def __init__(self, hotkeys):
		"""Load initial configuration and grab/ungrab global hotkeys.

			If user configuration exists, load it. Else load defaults.
		"""

		# TODO: Remove dependency on hotkeys
		self.hotkeys = hotkeys

		# Initialize config with defaults
		self.config = {
			# service
			"backspace_undo": True,

			# manager
			"_config_dir": os.path.expanduser('~/.config'),
			"phrases_dir": os.path.expanduser('~/.phrases'),

			#   Global hotkeys
			"_hotkeys": [('\t', ['NoModifier'])],
			"pause_service": ('p', ('<Shift>', '<Super>')),
			"show_manager": ('m', ('<Shift>', '<Super>')),

			# GUI
			"indicator_theme_light": True,
			"warn_folder_delete": True,

			# XInterface
			"window_title_lazy": True
		}
		self.__user_config_path = os.path.join(self._config_dir, 'Xpander.json')
		self.__json_types = (
			str, bool, int, float, list, tuple, dict, type(None))

		try:
			self.read_user()
			self.load()
		except:
			Logger.exception('Cannot read user configuration.')
			#  self.read_defaults()
			self.load()
			try:
				self.create_user_config()
			except:
				Logger.exception('Cannot create user configuration directory tree.')

		if not os.path.isdir(conf.phrases_dir):
			self.create_user_phrases()

		if self.pause_service:
			conf._hotkeys.append(conf.pause_service)
		if self.show_manager:
			conf._hotkeys.append(conf.show_manager)

	def __getattr__(self, attr):
		return self.config[attr]

	# TODO: Remove
	def read_defaults(self):
		"""Read default configuration into config."""

		Logger.debug('Reading default configuration.')
		for name in dir(conf):
			if (not name.startswith('_') and
				type(getattr(conf, name)) in self.__json_types):
				self.config[name] = getattr(conf, name)

	def read_user(self):
		"""Read user configuration into config."""

		Logger.debug('Reading user configuration.')
		with open(self.__user_config_path) as user_config:
			self.config.update(json.loads(user_config.read()))

	# TODO: Remove
	def load(self):
		"""Load config values into conf namespace."""

		for key, value in self.config.items():
			setattr(conf, key, value)



	def create_user_config(self):
		"""Create user configuration directory tree with default values."""

		if not os.path.isfile(self.__user_config_path):
			if not os.path.isdir(conf._config_dir):
				Logger.info('Creating configuration directory.')
				os.makedirs(conf._config_dir, exist_ok=True)
			Logger.info('Writing initial configuration.')
			self.write()
		return

	def create_user_phrases(self):
		"""Create user phrase directory and populate it with Phrases/Examples"""

		Logger.info("Creating phrase directory.")
		init_phrase_dir = os.path.join(
			os.path.abspath(os.path.dirname(__file__)), 'data')
		shutil.copytree(init_phrase_dir, conf.phrases_dir)
		return

	def write(self):
		"""Write configuration stored in config to conf._config_dir/config.json.
		"""

		Logger.debug('Writing configuration.')
		try:
			with open(self.__user_config_path, 'w') as user_config:
				user_config.write(json.dumps(
					self.config, ensure_ascii=False, indent='\t', sort_keys=True))
		except:
			Logger.exception('Cannot save user configuration.')

	def edit(self, key, value):
		"""Replace value of given key, load it to conf and save to config.json"""

		if key == 'pause_service':
			if conf.pause_service:
				self.hotkeys.ungrab_hotkey(conf.pause_service)
			if value:
				self.hotkeys.grab_hotkey(value)
		if key == 'show_manager':
			if conf.show_manager:
				self.hotkeys.ungrab_hotkey(conf.show_manager)
			if value:
				self.hotkeys.grab_hotkey(value)

		self.config[key] = value
		self.load()
		self.write()


class Phrases(object):

	def __init__(self, hotkeys):

		self.hotkeys = hotkeys
		self._phrases = {}
		self.load()
		for p_uuid, phrase in self._phrases.items():
			if phrase['hotkey']:
				conf._hotkeys.append(phrase['hotkey'])

	def __getitem__(self, key):
		"""Lookup an item in the phrases dict"""
		return self._phrases[key]

	def uuids(self):
		return self._phrases.keys()

	def load(self, folder=conf.phrases_dir):
		"""Recursively load phrases from conf.phrases_dir into phrases dict."""

		for file_ in os.listdir(folder):
			Logger.info('Loading phrase {}'.format(file_))
			update = False
			try:
				with open(os.path.join(folder, file_)) as p_file:
					try:
						phrase = json.loads(p_file.read())
						if not phrase['name'] == file_:
							phrase['name'] = file_
							update = True
						if not phrase['path'] == os.path.relpath(
							folder, start=conf.phrases_dir):
							phrase['path'] = os.path.relpath(
								folder, start=conf.phrases_dir)
							update = True
						self._phrases[phrase['uuid']] = phrase
					except ValueError:
						Logger.exception('Invalid phrase file.')
			except IsADirectoryError:
				self.load(os.path.join(folder, file_))

			if update:
				Logger.debug('Updating phrase file {}.'.format(file_))
				with open(os.path.join(folder, file_), 'w') as p_file:
					p_file.write(json.dumps(phrase, indent='\t', sort_keys=True))

	def new(
		self, name, body='', path='.', script=False, send=(1, 0), hotstring=None,
		trigger=0, hotkey=None, window_class=None, window_title=None):
		"""Construct new phrase, add it to phrase dict and save to file.

			name is a string file name;
			path is a string path relative to conf.phrases_dir;
			body is a string body of the phrase or command to execute,
				depending on script value;
			script is a boolean, if true body is treated as command to execute,
				else body is pasted directly;
			send is a tuple, first member determines wether to send via
				keyboard (0) or clipboard (1), second member currently only
				applies to clipboard, determines which keys to use:
					<Control>v (0), <Control><Shift>v (1), <Shift>Insert (2);
			hotstring is a string abbreviation to trigger expansion;
			trigger is an integer, determines which keys trigger expansion:
				all non-word chars (0), Space and Enter (1), Tab (2);
			hotkey is a tuple, first member is string name of the key,
				second member is a tuple of string names of modifiers;
			window_class is a tuple of string window classes to match;
			window_title is a tuple, first member is string to match,
				second member is boolean wether match is case-sensitive.
		"""

		if hotkey is not None:
			self.hotkeys.grab_hotkey(hotkey)

		file_path = os.path.join(conf.phrases_dir, path, name)
		p_uuid = str(uuid.uuid1())
		phrase = {
			'uuid': p_uuid,
			'name': name,
			'body': body,
			'path': path,
			'script': script,
			'send': send,
			'hotstring': hotstring,
			'trigger': trigger,
			'hotkey': hotkey,
			'window_class': window_class,
			'window_title': window_title,
			'timestamp': int(time.time())}
		self._phrases[p_uuid] = phrase
		if not os.path.isdir(os.path.dirname(file_path)):
			os.makedirs(os.path.dirname(file_path), exist_ok=True)
		with open(file_path, 'w') as p_file:
			p_file.write(json.dumps(phrase, indent='\t', sort_keys=True))

		return p_uuid

	def edit(
		self, p_uuid, name='KEEP', body='KEEP', path='KEEP', script='KEEP',
		send='KEEP', hotstring='KEEP', trigger='KEEP', hotkey='KEEP',
		window_class='KEEP', window_title='KEEP'):
		"""Edit phrase, update phrase dict and replace phrase file."""

		if hotkey != 'KEEP' and hotkey is not None:
			if self._phrases[p_uuid]['hotkey'] is not None:
				self.hotkeys.ungrab_hotkey(self._phrases[p_uuid]['hotkey'])
			self.hotkeys.grab_hotkey(hotkey)

		phrase = {
			'uuid': p_uuid,
			'name': name if name != 'KEEP' else self._phrases[p_uuid]['name'],
			'body': body if body != 'KEEP' else self._phrases[p_uuid]['body'],
			'path': path if path != 'KEEP' else self._phrases[p_uuid]['path'],
			'script': (script if script != 'KEEP'
				else self._phrases[p_uuid]['script']),
			'send': send if send != 'KEEP' else self._phrases[p_uuid]['send'],
			'hotstring': (hotstring if hotstring != 'KEEP'
				else self._phrases[p_uuid]['hotstring']),
			'trigger': (trigger if trigger != 'KEEP'
				else self._phrases[p_uuid]['trigger']),
			'hotkey': (hotkey if hotkey != 'KEEP'
				else self._phrases[p_uuid]['hotkey']),
			'window_class': (window_class if window_class != 'KEEP'
				else self._phrases[p_uuid]['window_class']),
			'window_title': (window_title if window_title != 'KEEP'
				else self._phrases[p_uuid]['window_title']),
			'timestamp': int(time.time())}

		move = False
		if (phrase['path'] != self._phrases[p_uuid]['path'] or
			phrase['name'] != self._phrases[p_uuid]['name']):
			move = True
			old_path = os.path.abspath(os.path.join(
				conf.phrases_dir,
				self._phrases[p_uuid]['path'],
				self._phrases[p_uuid]['name']))
			new_path = os.path.abspath(os.path.join(
				conf.phrases_dir,
				phrase['path'],
				phrase['name']))

		self._phrases[p_uuid] = phrase
		if move:
			os.renames(old_path, new_path)

		with open(os.path.abspath(os.path.join(conf.phrases_dir,
			self._phrases[p_uuid]['path'],
			self._phrases[p_uuid]['name'])), 'w') as p_file:
			p_file.write(json.dumps(phrase, indent='\t', sort_keys=True))

	def remove(self, p_uuid):
		"""Remove phrase from phrases dict and delete phrase file."""

		if self._phrases[p_uuid]['hotkey'] is not None:
			self.hotkeys.ungrab_hotkey(self._phrases[p_uuid]['hotkey'])

		p_file = os.path.abspath(os.path.join(
			conf.phrases_dir, self._phrases[p_uuid]['path'],
			self._phrases[p_uuid]['name']))
		p_dir = os.path.abspath(os.path.join(
			conf.phrases_dir, self._phrases[p_uuid]['path']))

		del self._phrases[p_uuid]

		try:
			os.remove(p_file)
			os.removedirs(p_dir)
		except OSError:
			pass
