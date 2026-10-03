import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_release import prepare


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'VERSION').write_text('0.1.2-beta.1')
        (self.root / 'blueos-settings.json').write_text('{"HostConfig": {}}')
        self.env = dict(GITHUB_REPOSITORY='Kisumu1/AtlasScientificDO', GITHUB_SHA='abc123')

    def test_github_registry_needs_no_dockerhub_account_or_contact_variables(self):
        # Values left from the old setup must not block the default GHCR path.
        values = prepare(dict(self.env, DOCKER_USERNAME='not an account',
                              MY_NAME='name', MY_EMAIL='email'), self.root)
        self.assertEqual(values['image'], 'ghcr.io/kisumu1/blueos-atlas-sensors')
        self.assertEqual(json.loads(values['authors'])[0]['name'], 'Kisumu1')
        self.assertEqual(json.loads(values['company'])['email'], 'Kisumu1@users.noreply.github.com')
        install = (self.root / 'release/INSTALL.txt').read_text()
        self.assertIn('Change visibility > Public', install)
        self.assertIn('Docker image: ghcr.io/kisumu1/blueos-atlas-sensors', install)
        self.assertIn('Docker tag: 0.1.2-beta.1', install)
        self.assertIn('UART / USB serial', install)
        self.assertFalse((self.root / 'release/repos').exists())

    def test_dockerhub_normalizes_username_and_generates_catalog_metadata(self):
        values = prepare(dict(self.env, REGISTRY='dockerhub', DOCKER_USERNAME=' TestOwner ',
                              MY_NAME='Test "Maintainer"', MY_EMAIL='test@example.com'), self.root)
        self.assertEqual(values['image'], 'testowner/blueos-atlas-sensors')
        self.assertEqual(values['username'], 'testowner')
        self.assertEqual(json.loads(values['authors'])[0]['name'], 'Test "Maintainer"')
        metadata = json.loads((self.root / 'release/repos/testowner/atlas-sensors/metadata.json').read_text())
        self.assertEqual(metadata['docker'], values['image'])
        self.assertEqual(metadata['website'], 'https://github.com/Kisumu1/AtlasScientificDO')

    def test_dockerhub_errors_explain_configuration_without_echoing_credentials(self):
        env = dict(self.env, REGISTRY='dockerhub', DOCKER_USERNAME='private@example.com',
                   MY_NAME='name', MY_EMAIL='email')
        with self.assertRaises(ValueError) as error:
            prepare(env, self.root)
        self.assertIn('Actions > Secrets', str(error.exception))
        self.assertNotIn(env['DOCKER_USERNAME'], str(error.exception))
        env['DOCKER_USERNAME'] = 'testowner'
        with self.assertRaisesRegex(ValueError, 'real contact email'):
            prepare(env, self.root)
        env.pop('DOCKER_USERNAME')
        with self.assertRaisesRegex(ValueError, 'Set DOCKER_USERNAME'):
            prepare(env, self.root)

    def test_invalid_registry_and_missing_github_context_fail(self):
        with self.assertRaisesRegex(ValueError, 'REGISTRY must be'):
            prepare(dict(self.env, REGISTRY='other'), self.root)
        with self.assertRaisesRegex(ValueError, 'GITHUB_REPOSITORY'):
            prepare({}, self.root)


if __name__ == '__main__':
    unittest.main()
