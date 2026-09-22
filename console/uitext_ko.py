"""Korean for the operator copy in uitext.py: the same keys, translatable fields only (tones and glyphs stay there).

The front end lays these over the English when the interface language is Korean (web/lib/i18n.js localCopy).
Protocol and hardware tokens (SET_ZONE, NFC, ACK, MAC, UID, CRC, versions) are never translated.
"""
LADDER = {}
PANELS = {}
STATUS = {}
ACTIONS = {}
GLOSSARY = {}


def as_dict():
    return dict(ladder=LADDER, panels=PANELS, status=STATUS, actions=ACTIONS, glossary=GLOSSARY)
