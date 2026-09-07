"""Generate JSON labels and concrete install instructions from GitHub configuration."""
import json
import os
import re
from pathlib import Path


def prepare(env, root):
    def required(key):
        value = env.get(key, '').strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError(f'Set {key} in GitHub Actions secrets/variables first')
        return value

    username = required('DOCKER_USERNAME')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', username):
        raise ValueError('DOCKER_USERNAME must be your Docker Hub username, not an email')
    name, email = required('MY_NAME'), required('MY_EMAIL')
    if '@' not in email:
        raise ValueError('MY_EMAIL must be a contact email')
    repo, commit = required('GITHUB_REPOSITORY'), required('GITHUB_SHA')
    version = (root / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
        raise ValueError('VERSION must contain a semantic version')
    image = f'{username}/blueos-atlas-sensors'
    source = f'https://github.com/{repo}'
    readme = f'https://raw.githubusercontent.com/{repo}/{commit}/README.md'
    outputs = dict(image=image, version=version, source=source, readme=readme,
                   authors=json.dumps([dict(name=name, email=email)]),
                   company=json.dumps(dict(name=name, email=email, about='Atlas Scientific sensor integration for BlueOS')),
                   links=json.dumps(dict(source=source, support=source+'/issues')))
    release = root / 'release'
    registration = release / 'repos' / username / 'atlas-sensors'
    registration.mkdir(parents=True, exist_ok=True)
    (registration / 'metadata.json').write_text(json.dumps(dict(
        name='Atlas Sensors', website=source, docker=image,
        description='Atlas EZO dissolved oxygen over isolated USB: live readings, calibration and CSV logging.'), indent=2))
    settings = (root / 'blueos-settings.json').read_text()
    (release / 'blueos-settings.json').write_text(settings)
    instructions = (f'BlueOS > Extensions > Installed > +\n\n'
                    f'Extension Identifier: {username}.atlas-sensors\n'
                    f'Extension Name: Atlas Sensors\nDocker image: {image}\nDocker tag: {version}\n'
                    f'Custom settings: paste blueos-settings.json from this artifact.\n\n'
                    f'After installation, open Atlas Sensors in the BlueOS sidebar and choose the Atlas USB port.\n'
                    f'The Pi chooses its matching ARM image automatically.\n\n'
                    f'Optional public Bazaar submission: add extension_logo.png next to metadata.json,\n'
                    f'and company_logo.png under repos/{username}/; submit repos/ to\n'
                    f'https://github.com/bluerobotics/BlueOS-Extensions-Repository\n')
    (release / 'INSTALL.txt').write_text(instructions)
    return outputs


if __name__ == '__main__':
    values = prepare(os.environ, Path('.'))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        for key, value in values.items():
            output.write(f'{key}={value}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
        summary.write('## Prepared extension release\n\n' + (Path('release') / 'INSTALL.txt').read_text())
