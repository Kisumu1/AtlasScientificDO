import csv
import io
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from atlas.sensors import EzoRTD, SensorError
from atlas.service import DEFAULTS, Service, validate_config
from atlas.temperature import TemperatureSource
from test_extension import FakeSerial


class RTDProtocolTests(unittest.TestCase):
    @patch('atlas.sensors.time.sleep')
    def test_identity_celsius_and_read_without_changing_calibration(self, _):
        serial = FakeSerial()
        serial.identity = b'22.1\r?I,RTD,2.12\r*OK\r'
        serial.reading = b'22.123\r*OK\r'
        with patch('atlas.sensors.serial.Serial', return_value=serial):
            driver = EzoRTD('/dev/ttyUSB1', 9600)
        self.assertEqual(driver.read(), 22.123)
        self.assertIn('S,c', serial.commands)
        self.assertNotIn('O,mg,1', serial.commands)
        self.assertFalse(any(c.startswith('Cal') for c in serial.commands))
        driver.close()

    def test_wrong_identity_is_not_reconfigured(self):
        serial = FakeSerial()
        with patch('atlas.sensors.serial.Serial', return_value=serial):
            with self.assertRaisesRegex(SensorError, 'EZO-RTD'):
                EzoRTD('/dev/ttyUSB0', 9600)
        self.assertEqual(serial.commands, ['i'])
        self.assertTrue(serial.closed)

    def test_invalid_disconnected_and_unsupported_temperatures_are_rejected(self):
        driver = EzoRTD.__new__(EzoRTD)
        for lines in ([], ['nan'], ['inf'], ['-999'], ['51'], ['22,30'], ['22', '23'], ['*ER']):
            with self.subTest(lines=lines), patch.object(driver, 'command', return_value=lines):
                with self.assertRaises(SensorError):
                    driver.read()


class TemperatureSourceTests(unittest.TestCase):
    def test_auto_skips_do_and_aliases_and_uses_rtd(self):
        reader = TemperatureSource()
        sensor = Mock()
        sensor.read.return_value = 18.234
        config = dict(DEFAULTS, port='/dev/ttyUSB0')
        ports = lambda: [dict(device='/dev/ttyUSB0'), dict(device='/dev/serial/by-id/do'),
                         dict(device='/dev/ttyUSB1'), dict(device='/dev/serial/by-id/rtd')]
        def real(path):
            return {'/dev/serial/by-id/do':'/dev/ttyUSB0', '/dev/serial/by-id/rtd':'/dev/ttyUSB1'}.get(path,path)
        with patch('atlas.temperature.os.path.realpath', side_effect=real), patch('atlas.temperature.EzoRTD', return_value=sensor) as factory:
            result = reader.sample(config, ports, lambda:'now')
        factory.assert_called_once_with('/dev/ttyUSB1', 9600)
        self.assertEqual(result, dict(effective_c=18.234, source='ezo_rtd', port='/dev/ttyUSB1', timestamp_utc='now', error=''))
        reader.close()

    def test_failed_read_never_reuses_old_temperature_and_reconnects(self):
        reader = TemperatureSource()
        sensor = Mock()
        sensor.read.side_effect = [15.5, SensorError('unplugged'), 19.0]
        config = dict(DEFAULTS, port='/dev/ttyUSB0', temperature_port='/dev/ttyUSB1')
        with patch('atlas.temperature.EzoRTD', return_value=sensor) as factory, patch('atlas.temperature.time.monotonic', side_effect=[0,2,3,13]):
            first = reader.sample(config, lambda:[], lambda:'first')
            failed = reader.sample(config, lambda:[], lambda:'failed')
            retry_wait = reader.sample(config, lambda:[], lambda:'waiting')
            recovered = reader.sample(config, lambda:[], lambda:'recovered')
        self.assertEqual(first['effective_c'], 15.5)
        for result in (failed, retry_wait):
            self.assertEqual(result['effective_c'], 20.0)
            self.assertEqual(result['source'], 'manual_fallback')
            self.assertIsNone(result['timestamp_utc'])
        self.assertEqual(recovered['effective_c'], 19.0)
        self.assertEqual(factory.call_count, 2)
        reader.close()

    def test_multiple_rtds_are_not_silently_selected(self):
        reader = TemperatureSource()
        sensors = [Mock(), Mock()]
        with patch('atlas.temperature.EzoRTD', side_effect=sensors):
            result = reader.sample(dict(DEFAULTS, port='/dev/ttyUSB0'),
                                   lambda:[dict(device='/dev/ttyUSB1'),dict(device='/dev/ttyUSB2')], lambda:'now')
        self.assertEqual(result['source'], 'manual_fallback')
        self.assertIn('Multiple', result['error'])
        for sensor in sensors:
            sensor.close.assert_called_once()

    def test_manual_and_demo_do_not_open_hardware(self):
        for changes in (dict(temperature_source='manual'),dict(mode='demo')):
            with self.subTest(changes=changes), patch('atlas.temperature.EzoRTD') as factory:
                result = TemperatureSource().sample(dict(DEFAULTS, **changes), lambda:[], lambda:'now')
                self.assertEqual(result['source'], 'manual')
                factory.assert_not_called()


class TemperatureIntegrationTests(unittest.TestCase):
    def test_fresh_temperature_is_sent_before_do_and_logged_with_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(directory)
            self.addCleanup(service.close)
            service.configure(dict(DEFAULTS, port='/dev/ttyUSB0', temperature_port='/dev/ttyUSB1'))
            do, rtd, calls = Mock(identity='?I,DO,2.17'), Mock(), []
            do.calibration.return_value = 1
            do.set_temperature.side_effect = lambda v:calls.append(('temperature',v))
            do.read.side_effect = lambda: calls.append(('read',None)) or dict(mg_l=8.1,saturation_pct=95)
            rtd.read.side_effect = [17.125, SensorError('unplugged')]
            with patch('atlas.service.EzoDO', return_value=do), patch('atlas.temperature.EzoRTD', return_value=rtd):
                service.tick()
                self.assertEqual(calls, [('temperature',17.125),('read',None)])
                self.assertEqual(service.state()['temperature']['source'], 'ezo_rtd')
                service.record(True)
                service.tick()
                row = next(csv.DictReader(io.StringIO(b''.join(service.export(service.session)).decode())))
                self.assertEqual(row['temperature_source'], 'manual_fallback')
                self.assertEqual(float(row['temperature_c']),20.0)
                self.assertEqual(row['temperature_timestamp_utc'],'')
                self.assertEqual(calls[-2:], [('temperature',20.0),('read',None)])
                self.assertEqual(service.status,'connected')
            service.close()

    def test_legacy_settings_migrate_and_old_csv_stays_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(directory)
            self.addCleanup(service.close)
            legacy = {k:v for k,v in DEFAULTS.items() if k not in ('temperature_source','temperature_port','temperature_baud')}
            self.assertEqual(validate_config(legacy)['temperature_source'],'auto')
            service.configure(dict(DEFAULTS, mode='demo'))
            service.tick()
            service.record(True)
            old = dict(service.latest)
            for key in ('temperature_source','temperature_port','temperature_timestamp_utc'):
                del old[key]
            service.db.execute('INSERT INTO samples VALUES (?,?)',(service.session,json.dumps(old)))
            service.db.commit()
            row = next(csv.DictReader(io.StringIO(b''.join(service.export(service.session)).decode())))
            self.assertEqual(row['temperature_source'],'manual')
            self.assertEqual(row['temperature_port'],'')
            service.close()

    def test_rejects_same_usb_device_and_invalid_settings(self):
        for changes in (dict(port='/dev/ttyUSB0',temperature_port='/dev/ttyUSB0'),
                        dict(temperature_source='unknown'),dict(temperature_baud=True),
                        dict(temperature_port='/dev/ttyAMA1')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_config(dict(DEFAULTS, **changes))
