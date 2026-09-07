"""Run inside each ARM image; confirm real-mode startup without sensor hardware."""
import json
import time
import urllib.request

for attempt in range(30):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8097/register_service', timeout=3) as response:
            registration = json.load(response)
        break
    except OSError:
        time.sleep(1)
else:
    raise RuntimeError('Extension did not start')

assert registration['name'] == 'Atlas Sensors'
assert registration['works_in_relative_paths'] is True
assert all(k in registration for k in ('description', 'icon', 'company', 'version', 'webpage', 'api'))
with urllib.request.urlopen('http://127.0.0.1:8097/api/state') as response:
    state = json.load(response)
assert state['config']['mode'] == 'hardware', 'Image must never start in demo mode'
assert state['config']['transport'] == 'i2c', 'Original carrier must default to I2C'
assert state['config']['i2c_address'] == 97
assert state['latest'] is None, 'Unconnected sensor must not report measurements'
with urllib.request.urlopen('http://127.0.0.1:8097/') as response:
    assert b'Dissolved oxygen' in response.read()
print('ARM image starts in hardware mode and serves BlueOS registration and dashboard.')
