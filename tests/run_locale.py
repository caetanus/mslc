"""Exercise the embedding API after the host adopts its environment's locale."""
import locale
import os
import subprocess
import sys

locales = subprocess.check_output(['locale', '-a'], text=True).splitlines()
comma = []
for name in locales:
    try:
        locale.setlocale(locale.LC_NUMERIC, name)
        if locale.localeconv()['decimal_point'] == ',':
            comma.append(name)
    except locale.Error:
        pass
locale.setlocale(locale.LC_ALL, 'C')
if not comma:
    print('SKIPPED: no installed comma-decimal locale')
    sys.exit(77)
# Cover both LC_ALL and the LC_NUMERIC-only host configuration.
preferred = [name for name in comma if name.lower() in ('pt_br.utf8', 'de_de.utf8')]
for name in preferred or comma[:1]:
    for category in ('LC_ALL', 'LC_NUMERIC'):
        env = dict(os.environ, LC_ALL='C', LC_NUMERIC='C')
        if category == 'LC_NUMERIC':
            env.pop('LC_ALL')
            env['LANG'] = 'C'
        env[category] = name
        subprocess.run(sys.argv[1:], env=env, check=True)
        print(f'{category}={name}: SPIR-V and reflection identical')
