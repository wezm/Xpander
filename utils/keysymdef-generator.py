#!/usr/bin/env python3

import re

extra_matcher = re.compile(r'#define (XK_[\w|\d]*)\s*(0x[\w|\d]*)')
extra_definition = []
parse = False

groups = ['XK_LATIN1', 'XK_LATIN2', 'XK_LATIN3', 'XK_LATIN4', 'XK_LATIN8',
		'XK_LATIN9', 'XK_KATAKANA', 'XK_ARABIC', 'XK_CYRILLIC', 'XK_GREEK',
		'XK_PUBLISHING', 'XK_HEBREW', 'XK_THAI', 'XK_KOREAN', 'XK_ARMENIAN',
		'XK_GEORGIAN', 'XK_CAUCASUS', 'XK_VIETNAMESE', 'XK_CURRENCY',
		'XK_MATHEMATICAL', 'XK_SINHALA']

def dedup(seq):
	seen = set()
	seen_add = seen.add
	return [x for x in seq if not (x in seen or seen_add(x))]

with open('/usr/include/X11/keysymdef.h') as keysymdef:
	for line in keysymdef:
		for group in groups:
			if line.startswith('#ifdef {0}'.format(group)):
				parse = True
			if parse:
				if line.startswith('#endif'):
					parse = False
					break
				extra_match = extra_matcher.search(line)
				if extra_match:
					extra_definition.append(
						"{0} = {1}".format(
						extra_match.group(1), extra_match.group(2)))

extra_definition = dedup(extra_definition)

with open('../KEYSYMDEF.py', 'w') as keysymdef:
	keysymdef.write('\n'.join(extra_definition))
