#!/usr/bin/env python3
"""Provides Interface class.

	Hooks keyboard, allows sending and receiving keyboard events, translating
	from keycode to keysym to character, getting active window info and
	limited access to clipboard.
"""

import os
import sys
import re
import time
import subprocess
import threading
import queue
import logging
import gi
from gi.repository import Gtk, Gdk, GLib
from Xlib import X, display
from Xlib.ext import record
from Xlib.protocol import rq, event
from . import conf, CONSTANTS

MainLogger = logging.getLogger('Xpander')
Logger = MainLogger.getChild(__name__)

# Ensure PyGObject verion doesn't require initializing threading explicitly.
GI_VERSION_MAJOR = gi.version_info[0]
GI_VERSION_MINOR = float('{0}.{1}'.format(
	gi.version_info[1], gi.version_info[2]))
Logger.info('PyGObject version {0}.{1}'.format(
	GI_VERSION_MAJOR, GI_VERSION_MINOR))
if GI_VERSION_MINOR < 10.2:
	Logger.critical('Unsupported PyGObject version.')
	sys.exit(1)

LAYOUT_SPLIT = re.compile(r'(\w+)(?:\((\w+)\))?')


class Interface(object):
	"""X keyboard interface.

		Properties:
		active_window - obj, currently focused window object;
		active_window_class - str, string representation of currently focused
			window class;
		active_window_title - str, string representation of currently focused
			window title, contents depend on conf.window_title_lazy var;
		clipboard_contents - str, string representation of text in clipboard;
		root_window - obj, X root window object;
		xkb-current - str, currently active layout group;
		xkb-layouts - tuple of tuples, each tuple represents configured layout,
			where first member is the layout group and second member is
			the variant.

		Methods:
		get_active_window - return currently focused window's window object;
		get_window_class - return given window's class string;
		get_window_title - return given window's title string;
		grab_keyboard - actively grab keyboard, consuming all keyboard events
			untill ungrab_keyboard is called;
		keycode_to_keysym - return int keysym bound to given keycode at
			given index;
		keysym_to_keycode - return tuple of ints, where first member is keycode
			bound to given keysym and second member is key's logical state flags;
		lookup_keycode - return int keycode bound to given keysym;
		lookup_keysym - return int keysym for given str character;
		lookup_string - return str character for given int keysym;
		send_backspace - send backspace keypress given number of times;
		send_key_press - send key press event of given keycode and logical
			state flags;
		send_key_release - send key release event of given keycode and logical
			state flags;
		send_string - send keypress events for every character in given string;
		send_string_clipboard - paste given string using given method;
		start - run event loop, layout watcher and event hook threads;
		stop - kill event loop, layout watcher and event hook threads;
		ungrab_keyboard - release active keyboard grabs, allowing keyboard
			events to pass.
	"""

	def __init__(self):
		"""Initialize layout watcher, event hook and event loop.

			Arguments:
			callback - A callable to call when keyboard event occurs.
				It must take 3 arguments:
				keysym - int, keysym for the key pressed;
				keypress - boolean, True on key press, False on key release;
				modifiers - dict, contains boolean values for modifier keys'
					logical states.

			modifiers keys are <Shift>, <AltGr>, <Alt>, <Control> and <Super>.
		"""

		# Main loop
		self._main_loop = threading.Thread(
			target=self.__main_loop, name='Main Loop', daemon=True)
		self.__queue = queue.Queue()

		# Layout watching and managing
		self._layout_watcher = threading.Thread(
			target=self.__layout_watcher, name='Layout Watcher', daemon=True)
		xkbmap = subprocess.check_output(
			['setxkbmap', '-query'],
			universal_newlines=True).split('\n')
		layouts = xkbmap[2][12:].split(',')
		variants = xkbmap[3][12:].split(',')
		if not xkbmap[3].startswith('variant:'):
			variants = ['' for l in layouts]
		self.xkb_layouts = tuple(zip(layouts, variants))
		output = subprocess.check_output(
			['xkb-switch'],
			universal_newlines=True).strip()
		current_layout = LAYOUT_SPLIT.match(output).groups()
		self.xkb_current = (current_layout[0], (current_layout[1]
			if current_layout[1] else ''))
		self.__xkb_run = True
		Logger.debug('Available layouts {}.'.format(self.xkb_layouts))
		Logger.debug('Currently active layout group: {}.'.format(
			self.xkb_current))

		# X event hook
		self._event_hook = threading.Thread(
			target=self.__event_hook, name='Event Hook', daemon=True)
		Logger.debug('Initializing Xlib.')
		self.__local_display = display.Display()
		self.__record_display = display.Display()
		try:
			record_version = self.__record_display.record_get_version(0, 0)
			Logger.info('Record extention version {0}.{1}'.format(
				record_version.major_version, record_version.minor_version))
		except:
			Logger.critical('Record extension not found. Cannot continue.')
			sys.exit(1)
		self.__context = self.__record_display.record_create_context(
			0,
			[record.AllClients],
			[{
				'core_requests': (0, 0),
				'core_replies': (0, 0),
				'ext_requests': (0, 0, 0, 0),
				'ext_replies': (0, 0, 0, 0),
				'delivered_events': (X.FocusIn, X.FocusIn),
				'device_events': (X.KeyPress, X.KeyRelease),
				'errors': (0, 0),
				'client_started': False,
				'client_died': False,
			}])
		# Determine and set mod1 through mod5.
		self.__MODIFIER_MAP = self.__local_display.get_modifier_mapping()
		self.__MODIFIER_INDEX = {X.ShiftMapIndex: X.ShiftMask,
								X.LockMapIndex: X.LockMask,
								X.ControlMapIndex: X.ControlMask,
								X.Mod1MapIndex: X.Mod1Mask,
								X.Mod2MapIndex: X.Mod2Mask,
								X.Mod3MapIndex: X.Mod3Mask,
								X.Mod4MapIndex: X.Mod4Mask,
								X.Mod5MapIndex: X.Mod5Mask}
		self.MODIFIER_MASK = {'NoModifier': 0,
							'<Shift>': X.ShiftMask,
							'<Control>': X.ControlMask,
							'<Alt>': 0,
							'<AltGr>': 0,
							'<Super>': 0,
							'<NumLock>': 0}
		self.__set_modifier_masks()
		# Get available keysyms for each layout.
		self.__KEYSYMS = {}
		self.__set_keysym_sets()
		# Keypad workaround: define a list of keypad keycodes for reference.
		self.__KEYPAD_CODES = set()
		for name in dir(CONSTANTS.XK):
			if name.startswith('XK_KP'):
				self.__KEYPAD_CODES.add(self.lookup_keycode(
					getattr(CONSTANTS.XK, name)))
		# Window name atoms.
		self.__name_atom = self.__local_display.intern_atom(
			"_NET_WM_NAME", True)
		self.__visible_name_atom = self.__local_display.intern_atom(
			"_NET_WM_VISIBLE_NAME", True)
		# Set initial window info.
		self.root_window = self.__local_display.screen().root
		self.active_window = self.get_active_window()
		self.active_window_class = self.get_window_class(self.active_window)
		self.active_window_title = self.get_window_title(self.active_window)

		# Clipboard
		self.__clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
		self.__selection = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
		self.clipboard_contents = ''
		self.store_clipboard()
		self.selection_contents = ''
		self.store_selection()
		# Define paste methods
		self.__paste_method = {
			0: (self.lookup_keycode(CONSTANTS.XK.XK_v),
				(self.MODIFIER_MASK['<Control>'])),
			1: (self.lookup_keycode(CONSTANTS.XK.XK_v),
				(self.MODIFIER_MASK['<Control>'] | self.MODIFIER_MASK['<Shift>'])),
			2: (self.lookup_keycode(CONSTANTS.XK.XK_Insert),
				(self.MODIFIER_MASK['<Shift>']))}

	def __enqueue(self, method, *args):
		"""Put method and args in queue for execution in event loop."""

		self.__queue.put_nowait((method, args))

	def __main_loop(self):
		"""Execute methods with given args from queue in event loop thread."""

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

	def __layout_watcher(self):
		"""Use xkb-switch to wait for keyboard layout changes.

			When change occurs update self.xkb-current and
			enqueue self.__switch_layout.
		"""

		Logger.debug('Initializing layout watcher.')
		watch = True
		try:
			while self.__xkb_run:
				if watch:
					self.__xkb_switch = subprocess.Popen(
						['xkb-switch', '-w', '-p'],
						stdout=subprocess.PIPE,
						universal_newlines=True)
					output = self.__xkb_switch.stdout.readline(
					).strip('\n')
					current_layout = LAYOUT_SPLIT.match(output).groups()
					self.xkb_current = (current_layout[0], (current_layout[1]
						if current_layout[1] else ''))
					if self.__xkb_run:
						Logger.debug('Currently active layout group: {}.'.format(
							self.xkb_current))
						watch = False
						self.__layout_switched = False
						self.__enqueue(self.__switch_layout)
				if self.__layout_switched:
					watch = True
		except:
			Logger.exception('Missing dependency: xkb-switch. Cannot continue.')
			sys.exit(1)

	def __transient_layouts(self, _cache={}):
		"""Return tuple of strings (layouts, variants) for use with setxkbmap.

			Strings are derived from self.xkb_layouts, with self.xkb-current
			moved to first position.
		"""

		if self.xkb_current in _cache:
			Logger.debug('Transient layout order {}.'.format(
				_cache[self.xkb_current]))
			return _cache[self.xkb_current]

		transient = list(self.xkb_layouts)
		for layout in transient[:]:
			if layout == self.xkb_current:
				transient.remove(layout)
				transient.insert(0, layout)
				break
		layouts = []
		variants = []
		for layout in transient:
			layouts.append(layout[0])
			variants.append(layout[1])
		Logger.debug('Transient layout order {}.'.format(
			(','.join(layouts), ','.join(variants))))
		_cache[self.xkb_current] = ','.join(layouts), ','.join(variants)
		return ','.join(layouts), ','.join(variants)

	def __switch_layout(self):
		"""Change keyboard layout in a way python Xlib can detect."""

		# Switch X keyboard layout order.
		# This doesn't necessarily change the active layout.
		Logger.info('Switching X keyboard layout.')
		layouts, variants = self.__transient_layouts()
		subprocess.call(['setxkbmap',
						'-layout', layouts,
						'-variant', variants])
		# Reload display object so it can pick up changed layout.
		self.__reload_display()
		# Clear caches because the mapping has probably changed.
		self.keycode_to_keysym(clear_cache=True)
		self.keysym_to_keycode(clear_cache=True)
		self.lookup_keycode(clear_cache=True)
		# Restore X keyboard layout order.
		# Transient order no longer needed,
		# because display object has already picked up changes.
		self.__restore_layouts()
		# Use xkb-switch to actually switch layout.
		Logger.debug('Switching active layout.')
		subprocess.call(
			['xkb-switch', '-s',
			('{0}({1})'.format(*self.xkb_current)
				if self.xkb_current[1] else self.xkb_current[0])])
		self.__layout_switched = True

	def __restore_layouts(self):
		"""Restore X keyboard layouts to initial order stored in self.xkb_layouts."""

		Logger.debug('Restoring keyboard layouts to initial state.')
		layouts = []
		variants = []
		for layout in self.xkb_layouts:
			layouts.append(layout[0])
			variants.append(layout[1])
		subprocess.call(['setxkbmap',
						'-layout', ','.join(layouts),
						'-variant', ','.join(variants)])

	def __get_keysym_sets(self, layout):
		"""Parse xkb symbols file for given layout.

			layout must be a tuple where first member is layout group string
			and second member is layout variant string.

			Return tuple of 4 sets, first set contains keysyms for unmodified
			keys, second for shifted, third contains keysyms for alt grid,
			forth for shifted alt grid."""

		# Variant is a group withing file.
		# If variant is an empty string, default group should be parsed.
		if layout[1] == '' or layout[1] is None:
			layout = (layout[0], 'default')

		keysym_set = set()
		keysym_set_shift = set()
		keysym_set_alt = set()
		keysym_set_alt_shift = set()
		includes = []
		definition_location = '/usr/share/X11/xkb/symbols'
		match_include = re.compile(r'include\s*\"(\w*)(?:\((\w*)\))*\"')
		match_keys = re.compile(r'.*[\[|<].*[\]|>].*\[\s*([\w|\d]*)'
			r'(?:,\s*([\w|\d]*)(?:,\s*([\w|\d]*))?(?:,\s*([\w|\d]*))?)?')
		parse = False
		with open(os.path.join(definition_location, layout[0])) as definition:
			for line in definition:
				if not parse:
					if (line.startswith('xkb_symbols "{}"'.format(layout[1])) or
						line.startswith(layout[1])):
						parse = True
				if parse:
					if line.startswith('};'):
						parse = False
						break
					include = match_include.search(line)
					if include:
						includes.append((include.group(1), include.group(2)))
					key = match_keys.search(line)
					if key:
						try:
							keysym_set.add(getattr(
								CONSTANTS.XK, 'XK_' + key.group(1)))
						except:
							try:
								keysym_set.add(int(key.group(1), 16))
							except:
								#~ Logger.exception('Error building keysym set.'
								#~ 'Cannot find keysym value.')
								pass
						try:
							keysym_set_shift.add(getattr(
								CONSTANTS.XK, 'XK_' + key.group(2)))
						except:
							try:
								keysym_set_shift.add(int(key.group(2), 16))
							except:
								#~ Logger.exception('Error building keysym set.'
								#~ 'Cannot find keysym value.')
								pass
						try:
							keysym_set_alt.add(getattr(
								CONSTANTS.XK, 'XK_' + key.group(3)))
						except:
							try:
								keysym_set_alt.add(int(key.group(3), 16))
							except:
								#~ Logger.exception('Error building keysym set.'
								#~ 'Cannot find keysym value.')
								pass
						try:
							keysym_set_alt_shift.add(getattr(
								CONSTANTS.XK, 'XK_' + key.group(4)))
						except:
							try:
								keysym_set_alt_shift.add(int(key.group(4), 16))
							except:
								#~ Logger.exception('Error building keysym set.'
								#~ 'Cannot find keysym value.')
								pass

		if includes:
			for include in includes:
				normal, shifted, alt, alt_shifted = self.__get_keysym_sets(
					include)
				keysym_set |= normal
				keysym_set_shift |= shifted
				keysym_set_alt |= alt
				keysym_set_alt_shift |= alt_shifted

		return (keysym_set, keysym_set_shift,
				keysym_set_alt, keysym_set_alt_shift)

	def __set_keysym_sets(self):
		"""Fill self.__KEYSYMS dict with keysyms sets for every layout configured."""

		for layout in self.xkb_layouts:
			normal, shifted, alt, alt_shifted = self.__get_keysym_sets(layout)
			self.__KEYSYMS[layout[0]] = normal
			self.__KEYSYMS[layout[0] + '_Shift'] = shifted
			self.__KEYSYMS[layout[0] + '_Alt'] = alt
			self.__KEYSYMS[layout[0] + '_Alt_Shift'] = alt_shifted

	def __reload_display(self):
		"""Close self.__local_display's socket and create a new
		self.__local_display object.
		"""

		self.__local_display.flush()
		try:
			self.__local_display.close()
		except:
			Logger.exception('Closing display socket failed.')
		self.__local_display = display.Display()
		# Since socket is closed, create a new window object using new socket.
		self.active_window = self.get_active_window()

	def __event_hook(self):
		"""Catch X events."""

		Logger.debug('Enabling recording context.')
		self.__record_display.record_enable_context(
			self.__context, self.__process_event)

	def __process_event(self, event):
		"""Process X event, taking appropriate action or sending event to handler."""

		# Event filter
		if event.category != record.FromServer:
			return
		if event.client_swapped:
			return
		if not len(event.data) or event.data[0] < 2:
			return

		# Processor
		data = event.data
		while len(data):
			event, data = rq.EventField(None).parse_binary_value(
				data, self.__record_display.display, None, None)

			# Focused window changed.
			if event.type is X.FocusIn:
				self.__enqueue(self.__update_active_window)

			# Keyboard event occured.
			if event.type in {X.KeyPress, X.KeyRelease}:
				self.__enqueue(self.__handle_key_event,
								event.type,
								event.detail,
								event.state)

	def __update_active_window(self):
		"""Update active window object and class and title strings."""

		self.active_window = self.get_active_window()
		self.active_window_class = self.get_window_class(self.active_window)
		self.active_window_title = self.get_window_title(self.active_window)

	def __handle_key_event(self, type_, keycode, state):
		"""Further process keyboard event and send data to callback."""

		if not conf.window_title_lazy:
			self.active_window_title = self.get_window_title(self.active_window)

		keypress = (type_ == X.KeyPress)
		keysym = self.keycode_to_keysym(keycode, 0)
		index, modifiers = self.translate_state(state, keycode)
		if keysym not in CONSTANTS.NO_INDEX:
			keysym = self.keycode_to_keysym(keycode, index)

		conf._service(keysym, keypress, modifiers)

	def __set_modifier_masks(self):
		"""Parse self.__MODIFIER_MAP and update self.MODIFIER_MASK."""

		for index, mask in self.__MODIFIER_INDEX.items():
			keylist = [self.keycode_to_keysym(key, 0)
						for key in self.__MODIFIER_MAP[index]]
			if ((CONSTANTS.XK.XK_Alt_L in keylist) or
				(CONSTANTS.XK.XK_Alt_R in keylist)):
				self.MODIFIER_MASK['<Alt>'] = mask
			elif CONSTANTS.XK.XK_ISO_Level3_Shift in keylist:
				self.MODIFIER_MASK['<AltGr>'] = mask
			elif ((CONSTANTS.XK.XK_Super_L in keylist) or
				(CONSTANTS.XK.XK_Super_R in keylist)):
				self.MODIFIER_MASK['<Super>'] = mask
			elif CONSTANTS.XK.XK_Num_Lock in keylist:
				self.MODIFIER_MASK['<NumLock>'] = mask

	def translate_state(self, state, keycode, _modifiers={}):
		"""Parse keyboard event state flags and return modifier index and dict.

			Index is used by keycode_to_keysym method and dict is sent to callback.
		"""

		index = 0
		if (((state & self.MODIFIER_MASK['<Shift>']) ^ (state & X.LockMask)) and
			keycode not in self.__KEYPAD_CODES):
			index += 1
			if state & self.MODIFIER_MASK['<Shift>']:
				_modifiers['<Shift>'] = True
		else:
			_modifiers['<Shift>'] = False
		if ((state & self.MODIFIER_MASK['<AltGr>']) and
			keycode not in self.__KEYPAD_CODES):
			index += 4
			_modifiers['<AltGr>'] = True
		else:
			_modifiers['<AltGr>'] = False
		if (state & self.MODIFIER_MASK['<NumLock>'] and
			keycode in self.__KEYPAD_CODES):
			index += 7
		if state & self.MODIFIER_MASK['<Alt>']:
			_modifiers['<Alt>'] = True
		else:
			_modifiers['<Alt>'] = False
		if state & X.ControlMask:
			_modifiers['<Control>'] = True
		else:
			_modifiers['<Control>'] = False
		if state & self.MODIFIER_MASK['<Super>']:
			_modifiers['<Super>'] = True
		else:
			_modifiers['<Super>'] = False

		return index, _modifiers

	def keycode_to_keysym(self, keycode=0, index=0, clear_cache=False, _cache={}):
		"""Return int keysym bound to given keycode at given index.

			Arguments:
			keycode - int keycode;
			index - int index, 0 is unmodified, 1 - shifted, 4 - alt grid,
				5 - shifted alt grid, 7 - num locked;
			clear_cache - if True clear cache and return None.
		"""

		if clear_cache:
			_cache.clear()
			return

		key = (keycode, index)
		if key in _cache:
			return _cache[key]

		keysym = self.__local_display.keycode_to_keysym(keycode, index)
		_cache[key] = keysym

		return keysym

	def lookup_string(self, keysym, _cache={}):
		"""Return str character for given int keysym.

			If there's no printable character for given keysym, return str
			name of given keysym. If name is not found return empty string.
		"""

		if keysym in _cache:
			return _cache[keysym]

		if keysym in CONSTANTS.PRINTABLE:
			string = CONSTANTS.PRINTABLE[keysym]
		elif keysym == CONSTANTS.XK.XK_Return:
			string = '\n'
		elif keysym == CONSTANTS.XK.XK_Tab:
			string = '\t'
		else:
			for name in dir(CONSTANTS.XK):
				if getattr(CONSTANTS.XK, name) == keysym:
					string = name
					break
			else:
				string = ''
		_cache[keysym] = string

		return string

	def lookup_keycode(self, keysym=0, clear_cache=False, _cache={}):
		"""Return int keycode bound to given keysym.

			If clear_cache is True, clear cache and return None.
		"""

		if clear_cache:
			_cache.clear()
			return

		if keysym in _cache:
			return _cache[keysym]

		keycode = self.__local_display.keysym_to_keycode(keysym)
		_cache[keysym] = keycode
		return keycode

	def get_active_window(self):
		"""Return currently focused window's window object."""

		try:
			window = self.__local_display.get_input_focus().focus
		except:
			Logger.exception('Problem getting active window. '
			'Window {0}, {1}'.format(window, type(window)))

		return window

	def get_window_class(self, window):
		"""Return given window's class string.

			If window's class cannot be determined, return empty string.
		"""

		try:
			wm_class = window.get_wm_class()
			if (wm_class is None or wm_class == ''):
				return self.get_window_class(window.query_tree().parent)
		except:
			#~ Logger.exception('Cannot determine window class. '
			#~ 'Window {0}, {1}'.format(window, type(window)))
			return ''
		#~ Logger.debug('Active window class {0}.{1}.'.format(
			#~ wm_class[0], wm_class[1]))

		return '{0}.{1}'.format(wm_class[0], wm_class[1])

	def get_window_title(self, window):
		"""Return given window's title string.

			If window title cannot be determined, return empty string.
		"""

		try:
			atom = window.get_property(self.__visible_name_atom, 0, 0, 255)
			if atom is None:
				atom = window.get_property(self.__name_atom, 0, 0, 255)
			if atom:
				#~ Logger.debug('Active window title {}.'.format(atom.value))
				return atom.value
			else:
				return self.get_window_title(window.query_tree().parent)
		except:
			#~ Logger.exception('Cannot determine window title. '
			#~ 'Window {0}, {1}'.format(window, type(window)))
			return ''

	def grab_keyboard(self):
		"""Actively grab keyboard, consuming all keyboard events untill
		ungrab_keyboard is called.
		"""

		self.__enqueue(self.__grab_keyboard)

	def __grab_keyboard(self):
		"""See grab_keyboard."""

		self.active_window.grab_keyboard(
			True, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
		self.__local_display.flush()

	def grab_key(self, keycode, modifier_mask):
		"""Passively grab key."""

		self.__enqueue(self.__grab_key, keycode, modifier_mask)

	def __grab_key(self, keycode, modifier_mask):
		"""See grab_key()"""

		self.root_window.grab_key(
			keycode, modifier_mask, False, X.GrabModeAsync, X.GrabModeAsync)

	def ungrab_key(self, keycode, modifier_mask):
		"""Release passive key grab."""

		self.__enqueue(self.__ungrab_key, keycode, modifier_mask)

	def __ungrab_key(self, keycode, modifier_mask):
		"""See ungrab_key()"""

		self.root_window.ungrab_key(keycode, modifier_mask)

	def ungrab_keyboard(self):
		"""Release active keyboard grabs, allowing keyboard events to pass"""

		self.__enqueue(self.__ungrab_keyboard)

	def __ungrab_keyboard(self):
		"""See ungrab_keyboard."""

		self.__local_display.ungrab_keyboard(X.CurrentTime)
		self.__local_display.flush()

	def lookup_keysym(self, string, _cache={}):
		"""Return int keysym for given string.

			string must be a single unicode character or a name of the keysym.
		"""

		if string in _cache:
			return _cache[string]

		for keysym, char in CONSTANTS.PRINTABLE.items():
			if char == string:
				_cache[string] = keysym
				return keysym
				break
		else:
			if string == '\b':
				_cache[string] = CONSTANTS.XK.XK_BackSpace
				return CONSTANTS.XK.XK_BackSpace
			elif string == '\t':
				_cache[string] = CONSTANTS.XK.XK_Tab
				return CONSTANTS.XK.XK_Tab
			elif string == '\n':
				_cache[string] = CONSTANTS.XK.XK_Return
				return CONSTANTS.XK.XK_Return
			else:
				for name in dir(CONSTANTS.XK):
					if name == string:
						_cache[string] = getattr(CONSTANTS.XK, name)
						return getattr(CONSTANTS.XK, name)
				else:
					_cache[string] = 0
					return 0

	def keysym_to_keycode(self, keysym=0, clear_cache=False, _cache={}):
		"""Return tuple of ints.

			First member is keycode bound to given keysym and second member is
			key's logical state flags.

			If clear_cache is True, clear cache and return None.
		"""

		if clear_cache:
			_cache.clear()
			return

		if keysym in _cache:
			return _cache[keysym]

		keycode = self.lookup_keycode(keysym)
		state = 0
		layout_mask = 0x2000

		for index, layout in enumerate(self.xkb_layouts):
			if keysym in self.__KEYSYMS[layout[0]]:
				state |= layout_mask * index
				_cache[keysym] = keycode, state
				return keycode, state
			elif keysym in self.__KEYSYMS[layout[0] + '_Shift']:
				state |= self.MODIFIER_MASK['<Shift>'] | (layout_mask * index)
				_cache[keysym] = keycode, state
				return keycode, state
			elif keysym in self.__KEYSYMS[layout[0] + '_Alt']:
				state |= (
					self.MODIFIER_MASK['<AltGr>'] | (layout_mask * index))
				_cache[keysym] = keycode, state
				return keycode, state
			elif keysym in self.__KEYSYMS[layout[0] + '_Alt_Shift']:
				state |= (
					self.MODIFIER_MASK['<AltGr>'] |
					self.MODIFIER_MASK['<Shift>'] | (layout_mask * index))
				_cache[keysym] = keycode, state
				return keycode, state
		else:
			_cache[keysym] = keycode, state
			return keycode, state

	def send_key_press(self, keycode, state):
		"""Send key press event of given keycode and logical state flags."""

		self.__enqueue(self.__send_key_press, keycode, state)

	def __send_key_press(self, keycode, state):
		"""See send_key_press."""

		key_press = event.KeyPress(detail=keycode,
									time=X.CurrentTime,
									root=self.root_window,
									window=self.active_window,
									child=X.NONE,
									root_x=0,
									root_y=0,
									event_x=0,
									event_y=0,
									state=state,
									same_screen=1)
		self.active_window.send_event(key_press)

	def send_key_release(self, keycode, state):
		"""Send key release event of given keycode and logical state flags."""

		self.__enqueue(self.__send_key_release, keycode, state)

	def __send_key_release(self, keycode, state):
		"""See send_key_press."""

		key_release = event.KeyRelease(detail=keycode,
										time=X.CurrentTime,
										root=self.root_window,
										window=self.active_window,
										child=X.NONE,
										root_x=0,
										root_y=0,
										event_x=0,
										event_y=0,
										state=state,
										same_screen=1)
		self.active_window.send_event(key_release)

	def send_string(self, string):
		"""Send keypress events for every character in given string."""

		self.__enqueue(self.__send_string, string)

	def __send_string(self, string):
		"""See send_string."""

		keysyms = map(self.lookup_keysym, string)
		keycodes = map(self.keysym_to_keycode, keysyms)

		self.grab_keyboard()
		for keycode in keycodes:
			self.send_key_press(*keycode)
			self.send_key_release(*keycode)
		self.ungrab_keyboard()

	def send_string_clipboard(self, string, paste_method=0):
		"""Paste given string using given method.

			Paste methods:
			0 - send <Control>V keypress;
			1 - send <Control><Shift>V keypress;
			2 - send <Shift>Insert keypress.
		"""

		self.__enqueue(self.__send_string_clipboard, string, paste_method)

	def __send_paste(self, method):
		"""Send paste keypress.

			For paste methods see send_string_clipboard.
		"""

		self.__grab_keyboard()
		self.__send_key_press(*self.__paste_method[method])
		self.__send_key_release(*self.__paste_method[method])
		self.__ungrab_keyboard()

	def store_clipboard(self):
		"""Store clipboard contents in self.clipboard_contents."""

		GLib.idle_add(self.__store_clipboard)
		time.sleep(0.1)

	def __store_clipboard(self):
		"""See store_clipboard."""

		contents = self.__clipboard.wait_for_text()
		if contents is None:
			contents = ''
		self.clipboard_contents = contents

	def store_selection(self):
		"""Store primary selection contents in self.selection_contents."""

		GLib.idle_add(self.__store_selection)
		time.sleep(0.1)

	def __store_selection(self):
		"""See store_selection."""

		contents = self.__selection.wait_for_text()
		if contents is None:
			contents = ''
		self.selection_contents = contents

	def __send_string_clipboard(self, string, method):
		"""See send_string_clipboard."""

		self.store_clipboard()
		GLib.idle_add(self.__clipboard.set_text, string, -1)
		GLib.idle_add(self.__clipboard.store)
		time.sleep(0.2)
		self.__send_paste(method)
		# Add short pause to avoid overwriting string
		# before it's actually pasted.
		time.sleep(0.2)
		GLib.idle_add(self.__clipboard.set_text, self.clipboard_contents, -1)
		GLib.idle_add(self.__clipboard.store)

	def send_backspace(self, count):
		"""Send backspace keypress given number of times."""

		backspace = self.lookup_keycode(CONSTANTS.XK.XK_BackSpace)
		for i in range(count):
			self.grab_keyboard()
			self.send_key_press(backspace, 0)
			self.send_key_release(backspace, 0)
			self.ungrab_keyboard()

	def caret_left(self, count):
		"""Send left keypress given number of times."""

		left = self.lookup_keycode(CONSTANTS.XK.XK_Left)
		for i in range(count):
			self.grab_keyboard()
			self.send_key_press(left, 0)
			self.send_key_release(left, 0)
			self.ungrab_keyboard()

	def caret_right(self, count):
		"""Send right keypress given number of times."""

		right = self.lookup_keycode(CONSTANTS.XK.XK_Right)
		for i in range(count):
			self.grab_keyboard()
			self.send_key_press(right, 0)
			self.send_key_release(right, 0)
			self.ungrab_keyboard()

	def start(self):
		"""Run event loop, layout watcher and event hook threads."""

		self._layout_watcher.start()
		self._event_hook.start()
		self._main_loop.start()

	def stop(self):
		"""Kill event loop, layout watcher and event hook threads."""

		self.__enqueue(None)
		Logger.info('Disbabling layout watcher.')
		self.__xkb_run = False
		self.__xkb_switch.terminate()
		Logger.info('Disabling recording context.')
		self.__local_display.record_disable_context(self.__context)
		self.__local_display.flush()
		self.__record_display.record_free_context(self.__context)
		self.__local_display.close()
		self.__record_display.close()

	def __del__(self):
		"""Call stop() to ensure threads close properly."""

		self.stop()
