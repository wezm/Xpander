#!/usr/bin/env python3

import os
from setuptools import setup

src_dir = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(src_dir, 'README.md')) as readme:
	long_description = readme.read()

classifiers = [
	'Development Status :: 5 - Production/Stable',
	'Environment :: X11 Applications',
	'Environment :: X11 Applications :: GTK',
	'Intended Audience :: Developers',
	'Intended Audience :: End Users/Desktop',
	'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
	'Operating System :: POSIX :: Linux',
	'Programming Language :: Python :: 3',
	'Programming Language :: Python :: 3.3',
	'Programming Language :: Python :: 3.4',
	'Programming Language :: Python :: 3.5',
	'Programming Language :: Python :: 3 :: Only',
	'Topic :: Utilities']

data_files = [
	('share/icons/hicolor/scalable/apps', [
		'data/xpander.svg',
		'data/xpander-active.svg',
		'data/xpander-paused.svg',
		'data/xpander-active-dark.svg',
		'data/xpander-paused-dark.svg']),
	('share/applications', [
		'data/xpander-indicator.desktop'])]

setup(
	name='Xpander',
	version='1.0.0',
	description='Text expander for Linux',
	long_description=long_description,
	url='https://github.com/OzymandiasTheGreat/Xpander',
	author='Tomas Ravinskas',
	author_email='tomas.rav@gmail.com',
	license='GPLv3+',
	classifiers=classifiers,
	package_dir={'Xpander': 'lib'},
	packages=['Xpander'],
	package_data={'Xpander': ['data/Examples/*.json']},
	data_files=data_files,
	scripts=['xpander-indicator'],
	# Causes unsatisfiable dependencies in the deb
	# install_requires=['python3-xlib'],
)
