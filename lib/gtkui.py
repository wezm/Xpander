#!/usr/bin/env python3

import os
import re
import collections
import time
import threading
import subprocess
import sys
import logging
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, AppIndicator3
from . import CONSTANTS, conf, manager

MainLogger = logging.getLogger('Xpander')
Logger = MainLogger.getChild(__name__)

KEY_SPLIT = re.compile(
	r'(<[\w]+>)(<[\w]+>)?(<[\w]+>)?(<[\w]+>)?(<[\w]+>)?(\w+)')

TOKENS = collections.OrderedDict(
	(('Insert', ''), ('Cursor', '$|'), ('Clipboard', '$C'), ('Selection', '$S'),
	('Literal %', '%%'), ('Date and time', '%c'), ('Date', '%x'), ('Time', '%X'),
	('Short year', '%y'), ('Year', '%Y'),
	('Short month name', '%b'), ('Month name', '%B'), ('Month number', '%m'),
	('Day', '%d'), ('Short weekday', '%a'), ('Weekday', '%A'),
	('Hour (24)', '%H'), ('Hour (12)', '%I'), ('AM/PM', '%p'),
	('Minute', '%M'), ('Second', '%S')))

TRIGGERS = collections.OrderedDict(
	(('All non-word characters', 0),
	('Space and Enter', 1),
	('Tab', 2)))

SEND = collections.OrderedDict(
	(('Clipboard (<Control>v)', [1, 0]),
	('Clipboard (<Control><Shift>v)', [1, 1]),
	('Clipboard (<Shift>Insert)', [1, 2]),
	('Keyboard', [0, 0])))


class ManagerUI(Gtk.Window):

	def __init__(self):

		Gtk.Window.__init__(self, title="Xpander")
		self.set_border_width(6)
		#~ self.set_default_size(700, 400)
		self.gui_hotkeys = Gtk.AccelGroup()
		self.add_accel_group(self.gui_hotkeys)

	def create_window(self):

		if os.path.exists('data/xpander.svg'):
			self.set_icon_from_file(os.path.abspath('data/xpander.svg'))
		else:
			self.set_icon_name('xpander')
		# General layout
		main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
					spacing=6)
		self.add(main_box)
		stack = Gtk.Stack(
			transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
		paned = Gtk.Paned()
		stack.add_titled(paned, 'manager', 'Manager')
		prefs_grid = Gtk.Grid(
			column_spacing=10, row_spacing=10, margin=10,
			halign=Gtk.Align.CENTER)
		stack.add_titled(prefs_grid, 'prefs', 'Preferences')
		stack_switcher = Gtk.StackSwitcher(halign=Gtk.Align.CENTER)
		stack_switcher.set_stack(stack)
		main_box.pack_start(stack_switcher, False, True, 0)
		main_box.pack_start(stack, True, True, 0)

		# Manager
		left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		treeview_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
		scrollable_treelist = Gtk.ScrolledWindow(width_request=150)
		scrollable_treelist.set_vexpand(True)
		# Treeview
		self.treestore = Gtk.TreeStore(str, str, str)
		self.treeview = Gtk.TreeView.new_with_model(self.treestore)
		self.add_mnemonic(Gdk.KEY_m, self.treeview)
		self.treeview.set_headers_visible(False)
		self.treeview.set_search_column(2)
		icon_renderer = Gtk.CellRendererPixbuf()
		icon_column = Gtk.TreeViewColumn('', icon_renderer, icon_name=1)
		self.treeview.append_column(icon_column)
		text_renderer = Gtk.CellRendererText()
		text_renderer.set_property("editable", True)
		text_column = Gtk.TreeViewColumn('Phrases', text_renderer, text=2)
		self.treeview.append_column(text_column)
		self.load_phrases()
		# Drag and drop
		target = Gtk.TargetEntry.new('row', Gtk.TargetFlags.SAME_WIDGET, 0)
		self.treeview.enable_model_drag_source(
			Gdk.ModifierType.BUTTON1_MASK,
			[target],
			Gdk.DragAction.DEFAULT | Gdk.DragAction.MOVE)
		self.treeview.enable_model_drag_dest(
			[target], Gdk.DragAction.DEFAULT | Gdk.DragAction.MOVE)
		# Selection
		self.selection = self.treeview.get_selection()
		# Toolbar
		toolbar = Gtk.Box(margin=2, spacing=2)
		add_menu = Gtk.Menu()
		add_phrase = Gtk.MenuItem('New phrase')
		add_phrase.add_accelerator(
			'activate', self.gui_hotkeys, Gdk.KEY_n,
			Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
		add_folder = Gtk.MenuItem('New folder')
		add_folder.add_accelerator(
			'activate', self.gui_hotkeys, Gdk.KEY_n,
			Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK,
			Gtk.AccelFlags.VISIBLE)
		add_menu.append(add_phrase)
		add_menu.append(add_folder)
		add_menu.show_all()
		add_icon = Gtk.Image.new_from_icon_name('list-add-symbolic', 0)
		add_button = Gtk.MenuButton()
		add_button.add(add_icon)
		add_button.set_popup(add_menu)
		toolbar.pack_start(add_button, False, False, 0)
		remove_icon = Gtk.Image.new_from_icon_name('list-remove-symbolic', 0)
		remove_button = Gtk.Button()
		remove_button.add_accelerator(
			'clicked', self.gui_hotkeys, Gdk.KEY_Delete, 0,  # No modifier mask
			Gtk.AccelFlags.VISIBLE)
		remove_button.add(remove_icon)
		toolbar.pack_start(remove_button, False, False, 0)
		# Editor
		editor_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
		self.right_grid = Gtk.Grid(
			column_spacing=6, row_spacing=6, margin=6)
		self.right_grid.set_sensitive(False)
		self.plain_text = Gtk.RadioButton.new_with_mnemonic_from_widget(
			None, '_Plain text')
		self.right_grid.attach(self.plain_text, 0, 0, 1, 1)
		self.command = Gtk.RadioButton.new_with_label_from_widget(
			self.plain_text, 'Command')
		self.right_grid.attach(self.command, 1, 0, 1, 1)
		text_wrap = Gtk.CheckButton.new_with_mnemonic('_Wrap text')
		self.right_grid.attach(text_wrap, 3, 0, 1, 1)
		insert_token = Gtk.ComboBoxText()
		self.add_mnemonic(Gdk.KEY_i, insert_token)
		insert_token.set_entry_text_column(0)
		for token in TOKENS:
			insert_token.append_text(token)
		insert_token.set_active(0)
		self.right_grid.attach(insert_token, 4, 0, 2, 1)
		scrollable_textview = Gtk.ScrolledWindow()
		scrollable_textview.set_hexpand(True)
		scrollable_textview.set_vexpand(True)
		self.textview = Gtk.TextView()
		self.add_mnemonic(Gdk.KEY_b, self.textview)
		scrollable_textview.add(self.textview)
		self.right_grid.attach(scrollable_textview, 0, 1, 6, 5)
		hotstring_label = Gtk.Label.new_with_mnemonic('_Abbreviation:')
		self.right_grid.attach(hotstring_label, 0, 6, 1, 1)
		self.hotstring = Gtk.Entry(max_length=128)
		hotstring_label.set_mnemonic_widget(self.hotstring)
		self.right_grid.attach_next_to(
			self.hotstring, hotstring_label, Gtk.PositionType.RIGHT, 2, 1)
		trigger_label = Gtk.Label.new_with_mnemonic('_Trigger on:')
		self.right_grid.attach_next_to(
			trigger_label, self.hotstring, Gtk.PositionType.RIGHT, 1, 1)
		self.triggers = Gtk.ComboBoxText()
		trigger_label.set_mnemonic_widget(self.triggers)
		self.triggers.set_entry_text_column(0)
		for trigger in TRIGGERS:
			self.triggers.append_text(trigger)
		self.right_grid.attach_next_to(
			self.triggers, trigger_label, Gtk.PositionType.RIGHT, 2, 1)
		hotkey_label = Gtk.Label.new_with_mnemonic('_Hotkey:')
		self.right_grid.attach(hotkey_label, 0, 7, 1, 1)
		self.hotkey = Gtk.Label()
		hotkey_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
		hotkey_frame.add(self.hotkey)
		self.right_grid.attach_next_to(
			hotkey_frame, hotkey_label, Gtk.PositionType.RIGHT, 2, 1)
		hotkey_button = Gtk.Button('Set')
		hotkey_label.set_mnemonic_widget(hotkey_button)
		self.right_grid.attach_next_to(
			hotkey_button, hotkey_frame, Gtk.PositionType.RIGHT, 1, 1)
		send_label = Gtk.Label.new_with_mnemonic('_Send via:')
		self.right_grid.attach(send_label, 0, 8, 1, 1)
		self.send = Gtk.ComboBoxText()
		send_label.set_mnemonic_widget(self.send)
		self.send.set_entry_text_column(0)
		for method in SEND:
			self.send.append_text(method)
		self.right_grid.attach_next_to(
			self.send, send_label, Gtk.PositionType.RIGHT, 2, 1)
		filter_class_label = Gtk.Label.new_with_mnemonic(
			'Filter by window _class:')
		self.right_grid.attach(filter_class_label, 0, 9, 2, 1)
		self.filter_class = Gtk.Entry()
		self.right_grid.attach_next_to(
			self.filter_class, filter_class_label, Gtk.PositionType.RIGHT, 2, 1)
		set_filter_class = Gtk.ToggleButton('Select')
		filter_class_label.set_mnemonic_widget(set_filter_class)
		self.right_grid.attach_next_to(
			set_filter_class, self.filter_class, Gtk.PositionType.RIGHT, 1, 1)
		filter_title_label = Gtk.Label.new_with_mnemonic(
			'_Filter by window title:')
		self.right_grid.attach(filter_title_label, 0, 10, 2, 1)
		self.filter_title = Gtk.Entry()
		self.right_grid.attach_next_to(
			self.filter_title, filter_title_label, Gtk.PositionType.RIGHT, 2, 1)
		set_filter_title = Gtk.ToggleButton('Select')
		filter_title_label.set_mnemonic_widget(set_filter_title)
		self.right_grid.attach_next_to(
			set_filter_title, self.filter_title, Gtk.PositionType.RIGHT, 1, 1)
		self.filter_case = Gtk.CheckButton.new_with_mnemonic('_Case sensitive')
		self.right_grid.attach_next_to(
			self.filter_case, set_filter_title, Gtk.PositionType.RIGHT, 1, 1)
		save_phrase = Gtk.Button('Save')
		save_phrase.add_accelerator(
			'clicked', self.gui_hotkeys, Gdk.KEY_s,
			Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
		self.right_grid.attach(save_phrase, 5, 11, 1, 1)

		# Preferences
		phrase_dir_label = Gtk.Label.new_with_mnemonic(
			'Phrase _directory (needs restart)')
		prefs_grid.attach(phrase_dir_label, 0, 0, 2, 1)
		phrase_dir = Gtk.FileChooserButton.new(
			'Phrase directory', Gtk.FileChooserAction.SELECT_FOLDER)
		phrase_dir.set_create_folders(True)
		phrase_dir.set_current_folder(conf.phrases_dir)
		phrase_dir_label.set_mnemonic_widget(phrase_dir)
		prefs_grid.attach(
			phrase_dir, 3, 0, 2, 1)
		indicator_theme_label = Gtk.Label.new_with_mnemonic(
			'Prefer light _indicator icon theme (needs restart)')
		prefs_grid.attach(indicator_theme_label, 0, 1, 2, 1)
		indicator_theme = Gtk.Switch()
		indicator_theme.set_active(conf.indicator_theme_light)
		indicator_theme_label.set_mnemonic_widget(indicator_theme)
		prefs_grid.attach(indicator_theme, 4, 1, 1, 1)
		folder_warning_label = Gtk.Label.new_with_mnemonic(
			'_Warn when deleting a folder')
		prefs_grid.attach(folder_warning_label, 0, 2, 2, 1)
		folder_warning_switch = Gtk.Switch()
		folder_warning_switch.set_active(conf.warn_folder_delete)
		folder_warning_label.set_mnemonic_widget(folder_warning_switch)
		prefs_grid.attach(folder_warning_switch, 4, 2, 1, 1)
		backspace_undo_label = Gtk.Label.new_with_mnemonic(
			'_Backspace undoes expansion')
		prefs_grid.attach(backspace_undo_label, 0, 3, 2, 1)
		backspace_undo = Gtk.Switch()
		backspace_undo.set_active(conf.backspace_undo)
		backspace_undo_label.set_mnemonic_widget(backspace_undo)
		prefs_grid.attach(backspace_undo, 4, 3, 1, 1)
		lazy_title_label = Gtk.Label.new_with_mnemonic(
			'_Lazy window title matching')
		prefs_grid.attach(lazy_title_label, 0, 4, 2, 1)
		lazy_title = Gtk.Switch()
		lazy_title.set_active(conf.window_title_lazy)
		lazy_title_label.set_mnemonic_widget(lazy_title)
		prefs_grid.attach(lazy_title, 4, 4, 1, 1)
		pause_expansion_label = Gtk.Label.new_with_mnemonic('_Pause expansion')
		prefs_grid.attach(pause_expansion_label, 0, 5, 1, 1)
		self.pause_expansion = Gtk.Label()
		if conf.pause_service:
			pause_modifiers = ''
			for modifier in conf.pause_service[1]:
				pause_modifiers += modifier
			self.pause_expansion.set_text(
				pause_modifiers + conf.pause_service[0])
		pause_expansion_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
		pause_expansion_frame.add(self.pause_expansion)
		prefs_grid.attach(pause_expansion_frame, 2, 5, 2, 1)
		pause_expansion_set = Gtk.Button('Set')
		pause_expansion_label.set_mnemonic_widget(pause_expansion_set)
		prefs_grid.attach(pause_expansion_set, 4, 5, 1, 1)
		show_manager_label = Gtk.Label.new_with_mnemonic('_Show manager')
		prefs_grid.attach(show_manager_label, 0, 6, 1, 1)
		self.show_manager = Gtk.Label()
		if conf.show_manager:
			show_modifiers = ''
			for modifier in conf.show_manager[1]:
				show_modifiers += modifier
			self.show_manager.set_text(show_modifiers + conf.show_manager[0])
		show_manager_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
		show_manager_frame.add(self.show_manager)
		prefs_grid.attach(show_manager_frame, 2, 6, 2, 1)
		show_manager_set = Gtk.Button('Set')
		show_manager_label.set_mnemonic_widget(show_manager_set)
		prefs_grid.attach(show_manager_set, 4, 6, 1, 1)

		# Packing
		scrollable_treelist.add(self.treeview)
		treeview_frame.add(scrollable_treelist)
		left_box.pack_start(treeview_frame, True, True, 0)
		toolbar_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
		toolbar_frame.add(toolbar)
		left_box.pack_start(toolbar_frame, False, True, 0)
		paned.add1(left_box)
		editor_frame.add(self.right_grid)
		paned.add2(editor_frame)

		# Signals
		text_renderer.connect('edited', self.row_edited)
		add_phrase.connect('activate', self.new_phrase)
		add_folder.connect('activate', self.new_folder)
		remove_button.connect('clicked', self.remove_item)
		self.treeview.connect('drag-data-get', self.drag_data_get)
		self.treeview.connect('drag-data-received', self.drag_data_received)
		self.selection.connect('changed', self.selection_changed)
		text_wrap.connect('toggled', self.wrap_text)
		insert_token.connect('changed', self.token_insert)
		hotkey_button.connect('clicked', self.get_phrase_hotkey)
		set_filter_class.connect('toggled', self.set_window_class)
		set_filter_title.connect('toggled', self.set_window_title)
		save_phrase.connect('clicked', self.save_phrase)
		phrase_dir.connect('file-set', self.set_phrase_dir)
		indicator_theme.connect('notify::active', self.set_indicator_theme)
		folder_warning_switch.connect(
			'notify::active', self.folder_warning_toggle)
		backspace_undo.connect('notify::active', self.backspace_undo_toggle)
		lazy_title.connect('notify::active', self.lazy_title_toggle)
		pause_expansion_set.connect('clicked', self.get_pause_expansion)
		show_manager_set.connect('clicked', self.get_show_manager)

	def sort_treeview(self):

		self.treestore.set_sort_column_id(2, Gtk.SortType.ASCENDING)
		self.treestore.set_sort_column_id(1, Gtk.SortType.DESCENDING)

	def load_phrases(self):

		seen_paths = {'.': None}
		for p_uuid in conf._phrases:
			phrase = conf._phrases[p_uuid]
			if phrase['path'] in seen_paths:
				self.treestore.append(
					seen_paths[phrase['path']],
					[p_uuid, 'document', phrase['name'][:-5]])
			else:
				path_iter = phrase['path'].split('/')
				path = '.'
				for folder in path_iter:
					path = os.path.join(path, folder)
					if path not in seen_paths:
						tree_iter = self.treestore.append(
							seen_paths[os.path.dirname(path)],
							['0', 'folder', folder])
						seen_paths[path] = tree_iter
				self.treestore.append(
					seen_paths[os.path.join('.', phrase['path'])],
					[p_uuid, 'document', phrase['name'][:-5]])
		self.sort_treeview()

	def get_rel_path(self, tree_iter):

		if tree_iter is None:
			return '.'

		rel_path = []
		for i in range(self.treestore.iter_depth(tree_iter) + 1):
			if self.treestore[tree_iter][0] == '0':
				rel_path.append(self.treestore[tree_iter][2])
			tree_iter = self.treestore.iter_parent(tree_iter)
		rel_path = os.path.join(*reversed(rel_path))
		return rel_path

	def check_name(self, model, parent_iter, name):

		name_unique = True
		check_iter = model.iter_children(parent_iter)
		for i in range(model.iter_n_children(parent_iter)):
			if model[check_iter][2] == name:
				name_unique = False
				break
			check_iter = model.iter_next(check_iter)
		return name_unique

	def get_new_phrase_name(self, model, parent_iter):

		phrase_count = 0
		phrase_name = 'New phrase'
		while not self.check_name(model, parent_iter, phrase_name):
			phrase_count += 1
			phrase_name = 'New phrase ' + str(phrase_count)
		return phrase_name

	def row_edited(self, renderer, path, text):

		def move_children(parent_iter):

			child_iter = self.treestore.iter_children(parent_iter)
			for i in range(self.treestore.iter_n_children(parent_iter)):
				if self.treestore[child_iter][0] == '0':
					move_children(child_iter)
				else:
					path = self.get_rel_path(parent_iter)
					p_uuid = self.treestore[child_iter][0]
					conf._phrases_manager.edit(p_uuid, path=path)
				child_iter = self.treestore.iter_next(child_iter)

		if self.treestore[path][0] == '0':
			self.treestore[path][2] = text
			tree_iter = self.treestore.get_iter(path)
			move_children(tree_iter)
		else:
			self.treestore[path][2] = text
			p_uuid = self.treestore[path][0]
			conf._phrases_manager.edit(p_uuid, name=text + '.json')
		self.sort_treeview()

	def new_phrase(self, menu_item):

		model, tree_iter = self.selection.get_selected()
		if (tree_iter is None or
			model.iter_parent(tree_iter) is None and model[tree_iter][0] != '0'):
			parent_iter = None
			path = '.'
		elif model[tree_iter][0] == '0':
			parent_iter = tree_iter
			path = self.get_rel_path(tree_iter)
		else:
			parent_iter = model.iter_parent(tree_iter)
			path = self.get_rel_path(tree_iter)
		name = self.get_new_phrase_name(model, parent_iter)
		p_uuid = conf._phrases_manager.new(name + '.json', path=path)
		model.append(parent_iter, [p_uuid, 'document', name])
		self.sort_treeview()

	def new_folder(self, menu_item):

		model, tree_iter = self.selection.get_selected()
		if (tree_iter is None or
			model.iter_parent(tree_iter) is None and model[tree_iter][0] != '0'):
			parent_iter = None
		elif model[tree_iter][0] == '0':
			parent_iter = tree_iter
		else:
			parent_iter = model.iter_parent(tree_iter)
		folder_count = 0
		folder_name = 'New folder'
		while not self.check_name(model, parent_iter, folder_name):
			folder_count += 1
			folder_name = 'New folder ' + str(folder_count)
		self.treestore.append(parent_iter, ['0', 'folder', folder_name])
		self.sort_treeview()

	def remove_item(self, widget):

		def remove_children(model, parent_iter):

			child_iter = model.iter_children(parent_iter)
			for i in range(model.iter_n_children(parent_iter)):
				if model[child_iter][0] == '0':
					remove_children(model, child_iter)
				else:
					conf._phrases_manager.remove(model[child_iter][0])
				model.remove(child_iter)

		model, tree_iter = self.selection.get_selected()
		if tree_iter is not None:
			if model[tree_iter][0] != '0':
				conf._phrases_manager.remove(model[tree_iter][0])
				model.remove(tree_iter)
			else:
				delete = True
				if conf.warn_folder_delete:
					dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.WARNING,
						Gtk.ButtonsType.OK_CANCEL, 'Delete folder')
					dialog.format_secondary_text(
						'This will also delete the phrases in this folder.')
					response = dialog.run()
					if response == Gtk.ResponseType.CANCEL:
						delete = False
					dialog.destroy()
				if delete:
					remove_children(model, tree_iter)
					model.remove(tree_iter)

	def drag_data_get(self, widget, context, data, info, timestamp):

		model, tree_iter = self.selection.get_selected()
		path = model.get_path(tree_iter)
		string = path.to_string()
		data.set(data.get_target(), 0, string.encode())

	def drag_data_received(self, widget, context, x, y, data, info, timestamp):

		def move_children(model, source, dest):

			child_iter = model.iter_children(source)
			for i in range(model.iter_n_children(source)):
				content = model.get(child_iter, 0, 1, 2)
				name_count = 0
				p_name = content[2]
				if model[child_iter][0] == '0':
					if self.check_name(model, dest, p_name):
						parent = model.insert(dest, -1, content)
					else:
						check_iter = model.iter_children(dest)
						for i in range(model.iter_n_children(dest)):
							if model[check_iter][2] == p_name:
								parent = check_iter
								break
							check_iter = model.iter_next(check_iter)
					move_children(model, child_iter, parent)
					model.remove(child_iter)
				else:
					while not self.check_name(model, dest, p_name):
						name_count += 1
						p_name = content[2] + ' ({})'.format(name_count)
					new_row = [content[0], content[1], p_name]
					p_name += '.json'
					tree_iter = model.insert(dest, -1, new_row)
					p_path = self.get_rel_path(model.iter_parent(tree_iter))
					p_uuid = self.treestore[tree_iter][0]
					conf._phrases_manager.edit(p_uuid, path=p_path, name=p_name)
					model.remove(child_iter)

		model = widget.get_model()
		source = model.get_iter_from_string(data.get_data().decode())
		content = model.get(source, 0, 1, 2)
		path, pos = widget.get_dest_row_at_pos(x, y)
		dest = model.get_iter(path)
		if pos in {Gtk.TreeViewDropPosition.BEFORE,
					Gtk.TreeViewDropPosition.AFTER}:
			dest = model.iter_parent(dest)
		elif model[dest][0] != '0':
			dest = model.iter_parent(dest)
		if model[source][0] != '0':
			p_path = self.get_rel_path(dest)
			model.remove(source)
			name_count = 0
			p_name = content[2]
			while not self.check_name(model, dest, p_name):
				name_count += 1
				p_name = content[2] + ' ({})'.format(name_count)
			new_row = [content[0], content[1], p_name]
			p_name += '.json'
			conf._phrases_manager.edit(content[0], path=p_path, name=p_name)
			print(dest)
			model.insert(dest, -1, new_row)
		else:
			if self.check_name(model, dest, content[2]):
				parent = model.insert(dest, -1, content)
			else:
				check_iter = model.iter_children(dest)
				for i in range(model.iter_n_children(dest)):
					if model[check_iter][2] == content[2]:
						parent = check_iter
						break
					check_iter = model.iter_next(check_iter)
			move_children(model, source, parent)
			model.remove(source)
		self.sort_treeview()

	def selection_changed(self, selection):

		model, tree_iter = selection.get_selected()
		text_buffer = self.textview.get_buffer()
		p_uuid = '0'
		if tree_iter is not None:
			p_uuid = model[tree_iter][0]
		if p_uuid != '0':
			self.right_grid.set_sensitive(True)
			phrase = conf._phrases[p_uuid]
			if phrase['script']:
				self.command.set_active(True)
			else:
				self.plain_text.set_active(True)
			text_buffer.set_text(phrase['body'])
			if phrase['hotstring']:
				self.hotstring.set_text(phrase['hotstring'])
			else:
				self.hotstring.set_text('')
			for index, trigger in enumerate(TRIGGERS.values()):
				if trigger == phrase['trigger']:
					self.triggers.set_active(index)
					break
			hotkey_modifiers = ''
			if phrase['hotkey']:
				for modifier in phrase['hotkey'][1]:
					hotkey_modifiers += modifier
				self.hotkey.set_text(hotkey_modifiers + phrase['hotkey'][0])
			else:
				self.hotkey.set_text('')
			for index, method in enumerate(SEND.values()):
				if method == phrase['send']:
					self.send.set_active(index)
					break
			if phrase['window_class']:
				self.filter_class.set_text(','.join(phrase['window_class']))
			else:
				self.filter_class.set_text('')
			if phrase['window_title']:
				title, case_sensitive = phrase['window_title']
				self.filter_title.set_text(title)
				self.filter_case.set_active(case_sensitive)
			else:
				self.filter_title.set_text('')
				self.filter_case.set_active(False)
		else:
			self.right_grid.set_sensitive(False)
			text_buffer.set_text('')
			self.hotstring.set_text('')
			self.triggers.set_active(-1)
			self.hotkey.set_text('')
			self.send.set_active(-1)
			self.filter_class.set_text('')
			self.filter_title.set_text('')
			self.filter_case.set_active(False)

	def wrap_text(self, widget):

		if widget.get_active():
			self.textview.set_wrap_mode(Gtk.WrapMode.WORD)
		else:
			self.textview.set_wrap_mode(Gtk.WrapMode.NONE)

	def token_insert(self, widget):

		text = widget.get_active_text()
		token = TOKENS[text]
		if token != '':
			text_buffer = self.textview.get_buffer()
			text_buffer.insert_at_cursor(token, len(token.encode()))
		widget.set_active(0)

	def get_phrase_hotkey(self, widget):

		self.key_event_hid = self.connect(
			'key-press-event', self.capture_hotkey, self.set_phrase_hotkey)

	def set_phrase_hotkey(self, string):

		self.hotkey.set_text(string)

	def capture_hotkey(self, widget, event, callback):

		keysym = conf._interface.keycode_to_keysym(event.hardware_keycode)
		if keysym not in CONSTANTS.MODIFIERS:
			string = conf._interface.lookup_string(keysym)
			index, modifiers = conf._interface.translate_state(
				event.state, event.hardware_keycode)
			modifier_string = ''
			for modifier in modifiers:
				if modifiers[modifier]:
					modifier_string += modifier
			if modifier_string:
				self.disconnect(self.key_event_hid)
				callback(modifier_string + string)
			elif keysym == CONSTANTS.XK.XK_Escape:
				self.disconnect(self.key_event_hid)
			elif keysym == CONSTANTS.XK.XK_BackSpace:
				self.disconnect(self.key_event_hid)
				callback('')

	def set_window_class(self, widget):

		if widget.get_active():
			window_class = conf._interface.active_window_class
			get_class_thread = threading.Thread(
				target=self.get_window_class,
				args=(widget, window_class),
				daemon=True)
			get_class_thread.start()

	def get_window_class(self, widget, window_class):

		while widget.get_active():
			if window_class == conf._interface.active_window_class:
				time.sleep(0.5)
			else:
				filter_list = self.filter_class.get_text().split(',')
				if conf._interface.active_window_class not in filter_list:
					filter_list.append(conf._interface.active_window_class)
				filter_class = ','.join(filter_list)
				GLib.idle_add(self.filter_class.set_text, filter_class)
				GLib.idle_add(widget.set_active, False)

	def set_window_title(self, widget):

		if widget.get_active():
			window_title = conf._interface.active_window_title
			get_title_thread = threading.Thread(
				target=self.get_window_title,
				args=(widget, window_title),
				daemon=True)
			get_title_thread.start()

	def get_window_title(self, widget, window_title):

		while widget.get_active():
			if window_title == conf._interface.active_window_title:
				time.sleep(0.5)
			else:
				filter_title = conf._interface.active_window_title
				GLib.idle_add(self.filter_title.set_text, filter_title)
				GLib.idle_add(widget.set_active, False)

	def save_phrase(self, widget):

		model, tree_iter = self.selection.get_selected()
		text_buffer = self.textview.get_buffer()
		p_uuid = '0'
		if tree_iter is not None:
			p_uuid = model[tree_iter][0]
		if p_uuid != '0':
			body_start, body_end = text_buffer.get_bounds()
			p_body = text_buffer.get_text(body_start, body_end, False)
			hotstring = self.hotstring.get_text()
			p_hotstring = hotstring if hotstring else None
			trigger = self.triggers.get_active_text()
			p_trigger = TRIGGERS[trigger]
			hotkey = KEY_SPLIT.match(self.hotkey.get_text())
			if hotkey:
				hotkey = hotkey.groups()
				p_hotkey = (
					hotkey[5],
					[modifier for modifier in hotkey[:-2]
						if modifier is not None])
			else:
				p_hotkey = None
			send_method = self.send.get_active_text()
			p_send = SEND[send_method]
			filter_class = self.filter_class.get_text()
			if filter_class:
				p_filter_class = filter_class.split(',')
			else:
				p_filter_class = None
			filter_title = self.filter_title.get_text()
			if filter_title:
				p_filter_title = (filter_title, self.filter_case.get_active())
			else:
				p_filter_title = None
			conf._phrases_manager.edit(
				p_uuid, body=p_body, script=self.command.get_active(),
				hotstring=p_hotstring, trigger=p_trigger, hotkey=p_hotkey,
				send=p_send, window_class=p_filter_class,
				window_title=p_filter_title)

	def restart_app(self, warning_text):

		dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.WARNING,
			Gtk.ButtonsType.OK_CANCEL, 'Restart now?')
		dialog.format_secondary_text(warning_text)
		response = dialog.run()
		dialog.destroy()
		if response == Gtk.ResponseType.OK:
			try:
				subprocess.Popen(['xpander-indicator'])
			except FileNotFoundError:
				subprocess.Popen(['./xpander-indicator'])
			conf._interface.stop()
			conf._service.stop()
			Gtk.main_quit()
			sys.exit(0)

	def set_phrase_dir(self, widget):

		conf._conf_manager.edit('phrases_dir', widget.get_filename())
		self.restart_app('Phrase editing and creation will not'
			' function corectly until application is restarted.')

	def set_indicator_theme(self, widget, pspec):

		conf._conf_manager.edit('indicator_theme_light', widget.get_active())
		self.restart_app(
			'Changes will not take effect until application is restarted.')

	def folder_warning_toggle(self, widget, pspec):

		conf._conf_manager.edit('warn_folder_delete', widget.get_active())

	def backspace_undo_toggle(self, widget, pspec):

		conf._conf_manager.edit('backspace_undo', widget.get_active())

	def lazy_title_toggle(self, widget, pspec):

		conf._conf_manager.edit('window_title_lazy', widget.get_active())

	def get_pause_expansion(self, widget):

		self.key_event_hid = self.connect(
			'key-press-event', self.capture_hotkey, self.set_pause_expansion)

	def set_pause_expansion(self, string):

		hotkey = KEY_SPLIT.match(string)
		if hotkey:
			hotkey = hotkey.groups()
			g_hotkey = (
					hotkey[5],
					[modifier for modifier in hotkey[:-2]
						if modifier is not None])
		else:
			g_hotkey = None
		conf._conf_manager.edit('pause_service', g_hotkey)
		self.pause_expansion.set_text(string)

	def get_show_manager(self, widget):

		self.key_event_hid = self.connect(
			'key-press-event', self.capture_hotkey, self.set_show_manager)

	def set_show_manager(self, string):

		hotkey = KEY_SPLIT.match(string)
		if hotkey:
			hotkey = hotkey.groups()
			g_hotkey = (
					hotkey[5],
					[modifier for modifier in hotkey[:-2]
						if modifier is not None])
		else:
			g_hotkey = None
		conf._conf_manager.edit('show_manager', g_hotkey)
		self.show_manager.set_text(string)

class Indicator(object):

	def __init__(self, quit_callback):
		self.quit_callback = quit_callback

		if conf.indicator_theme_light:
			if os.path.exists('data/xpander-active.svg'):
				self.indicator_active = os.path.abspath('data/xpander-active.svg')
				self.indicator_paused = os.path.abspath('data/xpander-paused.svg')
			else:
				self.indicator_active = 'xpander-active'
				self.indicator_paused = 'xpander-paused'
		else:
			if os.path.exists('data/xpander-active-dark.svg'):
				self.indicator_active = os.path.abspath('data/xpander-active-dark.svg')
				self.indicator_paused = os.path.abspath('data/xpander-paused-dark.svg')
			else:
				self.indicator_active = 'xpander-active-dark'
				self.indicator_paused = 'xpander-paused-dark'

		self.indicator = AppIndicator3.Indicator.new(
			'Xpander',
			self.indicator_active,
			AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
		self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
		self.indicator.set_menu(self.build_menu())
		self.manager_ui = ManagerUI()
		Gtk.main()

	def build_menu(self):

		menu = Gtk.Menu()
		conf._menu_toggle_service = Gtk.CheckMenuItem('Pause Expansion')
		conf._menu_toggle_service.connect('toggled', self.toggle_service)
		conf._menu_show_manager = Gtk.ImageMenuItem('Manager')
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
		if conf._run_service:
			GLib.idle_add(self.indicator.set_icon, self.indicator_active)
		else:
			GLib.idle_add(self.indicator.set_icon, self.indicator_paused)

	def show_manager(self, menu_item):

		self.manager_ui.create_window()
		self.manager_ui.show_all()

	def quit(self, menu_item):

		self.quit_callback()
		Gtk.main_quit()
		# If Gtk throws an error or just a warning, main_quit() might not
		# actually close the app
		sys.exit(0)

