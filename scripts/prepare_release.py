"""Generate JSON labels and concrete install instructions from GitHub configuration."""
import json
import os
import re
import sys
from pathlib import Path


def prepare(env, root):
    def required(key):
        value = env.get(key, '').strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError(f'Set {key} in GitHub Actions secrets/variables first')
        return value

    repo, commit = required('GITHUB_REPOSITORY'), required('GITHUB_SHA')
    owner = repo.split('/')[0]
    registry = env.get('REGISTRY', '').strip() or 'ghcr'
    if registry == 'ghcr':
        username = owner.lower()
        image = f'ghcr.io/{username}/blueos-atlas-sensors'
        # GHCR needs no manually configured credentials or contact variables.
        name, email = owner, f'{owner}@users.noreply.github.com'
    elif registry == 'dockerhub':
        username = required('DOCKER_USERNAME').lower()
        if not re.fullmatch(r'[a-z0-9]{4,30}', username):
            raise ValueError('DOCKER_USERNAME must be your Docker Hub Docker ID (4-30 letters or digits), '
                             'not an email, URL or display name. Edit it under Settings > Secrets and variables > '
                             'Actions > Secrets, or run with registry=ghcr to use your GitHub account.')
        name, email = required('MY_NAME'), required('MY_EMAIL')
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            raise ValueError('MY_EMAIL must contain a real contact email, not the word "email". '
                             'Edit it under Settings > Secrets and variables > Actions > Variables.')
        image = f'{username}/blueos-atlas-sensors'
    else:
        raise ValueError('REGISTRY must be ghcr or dockerhub')
    version = (root / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
        raise ValueError('VERSION must contain a semantic version')
    source = f'https://github.com/{repo}'
    readme = f'https://raw.githubusercontent.com/{repo}/{commit}/README.md'
    outputs = dict(username=username, image=image, version=version, source=source, readme=readme,
                   authors=json.dumps([dict(name=name, email=email)]),
                   company=json.dumps(dict(name=name, email=email, about='Atlas Scientific sensor integration for BlueOS')),
                   links=json.dumps(dict(source=source, support=source+'/issues')))
    release = root / 'release'
    release.mkdir(parents=True, exist_ok=True)
    if registry == 'dockerhub':
        registration = release / 'repos' / username / 'atlas-sensors'
        registration.mkdir(parents=True, exist_ok=True)
        (registration / 'metadata.json').write_text(json.dumps(dict(
            name='Atlas Sensors', website=source, docker=image,
            description='Atlas EZO dissolved oxygen over USB/UART or I2C: live readings, calibration and CSV logging.'), indent=2))
    settings = (root / 'blueos-settings.json').read_text()
    (release / 'blueos-settings.json').write_text(settings)
    if registry == 'ghcr':
        registry_steps = (f'Before installing, make the GitHub container package Public:\n'
                          f'https://github.com/users/{owner}/packages/container/blueos-atlas-sensors/settings\n'
                          f'Package settings > Change visibility > Public. A public source repository alone '
                          f'does not make its package public.\n'
                          f'For an organization account, use the package settings under that organization.\n\n')
        catalog_steps = ('Public Bazaar submission currently expects Docker Hub. For that later, run the '
                         'workflow with registry=dockerhub after configuring a Docker Hub account.\n')
    else:
        registry_steps = 'The Docker Hub repository must be Public before installing.\n\n'
        catalog_steps = (f'Optional public Bazaar submission: add extension_logo.png next to metadata.json,\n'
                         f'and company_logo.png under repos/{username}/; submit repos/ to\n'
                         f'https://github.com/bluerobotics/BlueOS-Extensions-Repository\n')
    instructions = (registry_steps + f'BlueOS > Extensions > Installed > +\n\n'
                    f'Extension Identifier: {username}.atlas-sensors\n'
                    f'Extension Name: Atlas Sensors\nDocker image: {image}\nDocker tag: {version}\n'
                    f'Custom settings: paste blueos-settings.json from this artifact.\n\n'
                    f'After installation, open Atlas Sensors in the BlueOS sidebar.\n'
                    f'For a USB EZO carrier, choose UART / USB serial, its listed /dev/ttyUSB device, and the '
                    f'sensor baud rate (normally 9600). The EZO-DO must be in UART mode.\n'
                    f'For the original carrier wired to the Navigator, choose I2C, /dev/i2c-6 and address 97.\n'
                    f'The Pi chooses its matching ARM image automatically.\n\n'
                    + catalog_steps)
    (release / 'INSTALL.txt').write_text(instructions)
    return outputs


if __name__ == '__main__':
    try:
        values = prepare(os.environ, Path('.'))
    except ValueError as error:
        message = str(error).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::error title=Release configuration::{message}')
        sys.exit(1)
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        for key, value in values.items():
            output.write(f'{key}={value}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
        summary.write('## Prepared extension release\n\n' + (Path('release') / 'INSTALL.txt').read_text())
