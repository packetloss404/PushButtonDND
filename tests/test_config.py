import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        results = Path(__file__).resolve().parents[1] / 'test-results'
        results.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=results)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'config.json'
        self.backup = Path(self.directory.name) / 'backup.json'
        self.temp = Path(self.directory.name) / 'temp.json'
        self.constants = patch.multiple(config, CONFIG_PATH=str(self.path), BACKUP_PATH=str(self.backup), TEMP_PATH=str(self.temp))
        self.constants.start()
        self.addCleanup(self.constants.stop)

    def settings(self, ssid='test network'):
        settings = config.get_default_config()
        settings['wifi']['ssid'] = ssid
        return settings

    def test_missing_and_corrupt_config_enter_safe_defaults(self):
        settings, error = config.load_config()
        self.assertIsNone(error)
        self.assertEqual(settings['wifi']['ssid'], '')
        for value in ('not json', '[]', '{"wifi": null}', '{"mqtt": {"port": 70000}}'):
            with self.subTest(value=value):
                self.path.write_text(value)
                settings, error = config.load_config()
                self.assertTrue(error)
                self.assertEqual(settings, config.get_default_config())

    def test_older_config_gets_new_default_keys(self):
        self.path.write_text(json.dumps({'wifi': {'ssid': 'old network'}}))
        settings, error = config.load_config()
        self.assertIsNone(error)
        self.assertEqual(settings['wifi'], {'ssid': 'old network', 'password': ''})
        self.assertEqual(settings['desk'], config.get_default_config()['desk'])

    def test_validation_rejects_bad_shapes_and_network_values(self):
        cases = [('wifi', None), ('security', []), ('mqtt', 'broken'), ('desk', 3)]
        for section, value in cases:
            with self.subTest(section=section):
                settings = self.settings()
                settings[section] = value
                self.assertFalse(config.validate_config(settings)[0])
        for port in (0, 65536, '1883', True, 1.5):
            settings = self.settings()
            settings['mqtt']['port'] = port
            self.assertFalse(config.validate_config(settings)[0], port)
        for url in ('https://door/api/set', 'httpfoo', 'http://', 'http://user@door/', 'http://door/#fragment'):
            settings = self.settings()
            settings['desk']['receiver_url'] = url
            self.assertFalse(config.validate_config(settings)[0], url)
        for section, key, value in (('mqtt', 'qos', 2), ('mqtt', 'enabled', 'yes'), ('mqtt', 'topic_prefix', 'a/#'), ('security', 'auth_token', 'x\r\nHost: evil'), ('teams', 'polling_interval', 0), ('wifi', 'ssid', 'é' * 17)):
            settings = self.settings()
            settings[section][key] = value
            self.assertFalse(config.validate_config(settings)[0], (section, key))

    def test_save_backup_restore_and_reset_round_trip(self):
        first = self.settings('first')
        first['security']['auth_token'] = 'token &=é'
        self.assertEqual(config.save_config(first), (True, None))
        self.assertEqual(config.load_config(), (first, None))
        self.assertEqual(config.save_config(self.settings('second')), (True, None))
        self.assertEqual(json.loads(self.backup.read_text()), first)
        self.assertEqual(config.restore_backup(), (True, None))
        self.assertEqual(config.load_config(), (first, None))
        self.assertEqual(json.loads(self.backup.read_text()), first)
        self.assertEqual(config.reset_config(), (True, None))
        self.assertFalse(self.path.exists())
        self.assertTrue(self.backup.exists())

    def test_save_restores_optional_defaults(self):
        settings = self.settings()
        del settings['desk']
        del settings['mqtt']['device_name']
        self.assertEqual(config.save_config(settings), (True, None))
        stored = json.loads(self.path.read_text())
        self.assertIn('desk', stored)
        self.assertEqual(stored['mqtt']['device_name'], 'DND Light')

    def test_invalid_save_never_changes_active_config(self):
        original = self.settings()
        config.save_config(original)
        invalid = self.settings('bad')
        invalid['mqtt']['port'] = 0
        self.assertFalse(config.save_config(invalid)[0])
        self.assertEqual(json.loads(self.path.read_text()), original)

    def test_failed_atomic_replace_preserves_active_config(self):
        original = self.settings()
        config.save_config(original)
        real_replace = config._replace_file
        def fail_active(source, destination):
            if destination == str(self.path):
                raise OSError('simulated flash rename failure')
            return real_replace(source, destination)
        with patch.object(config, '_replace_file', side_effect=fail_active):
            self.assertFalse(config.save_config(self.settings('new'))[0])
        self.assertEqual(json.loads(self.path.read_text()), original)

    def test_bad_backup_cannot_replace_active_and_bad_active_keeps_good_backup(self):
        config.save_config(self.settings('first'))
        config.save_config(self.settings('second'))
        good_backup = self.backup.read_text()
        self.path.write_text('corrupt')
        self.assertTrue(config.save_config(self.settings('third'))[0])
        self.assertEqual(self.backup.read_text(), good_backup)
        self.backup.write_text('{"wifi":null}')
        self.assertFalse(config.restore_backup()[0])
        self.assertEqual(config.load_config()[0]['wifi']['ssid'], 'third')

    def test_factory_reset_reboots_even_without_active_file(self):
        reset = unittest.mock.Mock()
        with patch.dict('sys.modules', {'machine': types.SimpleNamespace(reset=reset)}):
            self.assertEqual(config.factory_reset(), (True, None))
        reset.assert_called_once_with()

    def test_factory_reset_does_not_reboot_after_deletion_failure(self):
        config.save_config(self.settings())
        reset = unittest.mock.Mock()
        with patch.object(os, 'remove', side_effect=PermissionError(13, 'denied')):
            with patch.dict('sys.modules', {'machine': types.SimpleNamespace(reset=reset)}):
                self.assertFalse(config.factory_reset()[0])
        reset.assert_not_called()


if __name__ == '__main__':
    unittest.main()
