import json
import sys

manifest = json.load(open(sys.argv[1], encoding='utf-8'))
platforms = [m.get('platform', {}) for m in manifest['manifests']]
assert any(p.get('os') == 'linux' and p.get('architecture') == 'arm' and p.get('variant') == 'v7' for p in platforms), 'Missing Linux ARMv7 image'
assert any(p.get('os') == 'linux' and p.get('architecture') == 'arm64' for p in platforms), 'Missing Linux ARM64 image'
print('Published manifest includes Linux ARMv7 and ARM64.')
