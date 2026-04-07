"""Post-processing: fix mojibake caused by PowerShell ConvertTo-Json re-encoding."""
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else 'data/actions.json'

with open(path, 'r', encoding='utf-8') as f:
    raw = f.read()

fixes = [
    ('\u00c3\u00a2\u20ac\u201d', '\u2014'),  # em dash
    ('\u00c3\u00a2\u20ac\u201c', '\u2013'),  # en dash
    ('\u00c3\u00a2\u20ac\u2122', '\u2019'),  # right single quote
    ('\u00c3\u00a2\u20ac\u00a6', '\u2026'),  # ellipsis
    ('\u00c3\u00a9', '\u00e9'),               # e-acute
]

changed = False
for old, new in fixes:
    if old in raw:
        raw = raw.replace(old, new)
        changed = True

if changed:
    json.loads(raw)  # validate
    with open(path, 'w', encoding='utf-8') as f:
        f.write(raw)
    print('fix_encoding: fixed mojibake')
else:
    print('fix_encoding: no mojibake found')
