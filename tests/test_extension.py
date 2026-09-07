import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from atlas.__main__ import handler
from atlas.sensors import EzoDO, SensorError, parse_do
from atlas.service import DEFAULTS, Service, validate_config


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.buffer = bytearray()
        self.commands = []
        self.closed = False
        self.reading = b'8.12,91.3\r*OK\r'
        self.identity = b'?i,D.O.,2.14\r*OK\r'
        self.ack = True

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, data):
        cmd = data.decode().strip()
        self.commands.append(cmd)
        if cmd == 'i':
            reply = self.identity
        elif cmd == 'R':
            reply = self.reading
        elif cmd == 'Cal,?':
            reply = b'?Cal,1\r*OK\r'
        else:
            reply = b'*OK\r'
        self.buffer.extend(reply)

    def read(self, count):
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def flush(self):
        pass

    def close(self):
        self.closed = True


class ProtocolTests(unittest.TestCase):
    def test_parser_rejects_corrupt_missing_and_nonfinite_data(self):
        self.assertEqual(parse_do('8.12,91.3')['mg_l'], 8.12)
        for value in ('8.12', 'NaN,30', '3,Infinity', '-1,12', '101,20', '3,351', '*ER', 'a,b', '1,2,3'):
            with self.subTest(value=value), self.assertRaises(SensorError):
                parse_do(value)

    @patch('atlas.sensors.time.sleep')
    def test_full_serial_handshake_compensation_and_calibration(self, _):
        fake = FakeSerial()
        with patch('atlas.sensors.serial.Serial', return_value=fake):
            driver = EzoDO('/dev/test', 9600)
        driver.compensate(DEFAULTS)
        self.assertIn('S,0.0,ppt', fake.commands)
        self.assertIn('P,101.3', fake.commands)
        self.assertEqual(driver.read(), dict(mg_l=8.12, saturation_pct=91.3))
        self.assertEqual(driver.calibrate('air'), 1)
        self.assertIn('Cal', fake.commands)
        fake.reading = b'*UV\r'
        with self.assertRaisesRegex(SensorError, 'UV'):
            driver.read()
        fake.reading = b'*OK\r'
        with self.assertRaises(SensorError):
            driver.read()
        driver.close()
        self.assertTrue(fake.closed)

    def test_wrong_device_is_not_configured(self):
        fake = FakeSerial()
        fake.identity = b'?i,pH,2.1\r'
        with patch('atlas.sensors.serial.Serial', return_value=fake), self.assertRaises(SensorError):
            EzoDO('/dev/test', 9600)
        self.assertEqual(fake.commands, ['i'])
        self.assertTrue(fake.closed)

    def test_timeout_is_not_a_zero_reading(self):
        driver = EzoDO.__new__(EzoDO)
        driver.serial = FakeSerial()
        driver.serial.reading = b''
        with patch('atlas.sensors.time.monotonic', side_effect=[0, 1, 4]), self.assertRaisesRegex(SensorError, 'timeout'):
            driver.read()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = Service(self.tmp.name)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_default_never_synthesizes_hardware_readings(self):
        self.service.tick()
        self.assertIsNone(self.service.state()['latest'])
        self.assertTrue(self.service.state()['stale'])

    def test_record_export_restart_and_source_separation(self):
        s = self.service
        s.configure(dict(DEFAULTS, mode='demo'))
        s.tick()
        s.record(True)
        s.tick()
        session = s.session
        with self.assertRaises(ValueError):
            s.configure(dict(DEFAULTS))
        export = b''.join(s.export(session)).decode()
        self.assertIn('timestamp_utc,mode,sensor,mg_l,saturation_pct', export)
        self.assertIn(',demo,ezo-do,', export)
        s.record(False)
        s.configure(dict(DEFAULTS))
        self.assertIsNone(s.state()['latest'])
        self.assertEqual(s.state()['history'], [])
        other = Service(self.tmp.name)
        try:
            self.assertEqual(len(other.state()['sessions']), 1)
            self.assertEqual(other.config['mode'], 'hardware')
            self.assertFalse(other.recording)
        finally:
            other.close()

    def test_disconnect_and_reconnect_do_not_fake_values(self):
        s = self.service
        s.configure(dict(DEFAULTS, port='/dev/test'))
        with patch('atlas.service.EzoDO') as factory:
            sensor = factory.return_value
            sensor.identity = '?i,D.O.,2.14'
            sensor.calibration.return_value = 1
            sensor.read.return_value = dict(mg_l=8.2, saturation_pct=90)
            s.tick()
            self.assertFalse(s.state()['stale'])
            sensor.read.side_effect = SensorError('USB unplugged')
            s.tick()
            self.assertTrue(s.state()['stale'])
            self.assertEqual(s.state()['latest']['mg_l'], 8.2)
            self.assertEqual(s.state()['status'], 'disconnected')
            sensor.read.side_effect = None
            s.tick()
            self.assertEqual(factory.call_count, 2)
            self.assertFalse(s.state()['stale'])

    def test_invalid_config_and_demo_calibration_are_rejected(self):
        for key, value in [('temperature_c', float('nan')), ('salinity_ppt', -1), ('baud', 123), ('mode', 'other'), ('interval_s', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(dict(DEFAULTS, **{key:value}))
        self.service.configure(dict(DEFAULTS, mode='demo'))
        self.service.tick()
        with self.assertRaises(ValueError):
            self.service.calibrate('air')

    def test_http_ui_state_control_and_export(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            for path in ('/', '/app.js', '/style.css', '/register_service', '/api/state', '/api/ports'):
                with urllib.request.urlopen(base+path) as response:
                    self.assertEqual(response.status, 200)
            def post(path, body, custom=True):
                headers = {'Content-Type':'application/json'}
                if custom:
                    headers['X-Atlas-Request'] = '1'
                return urllib.request.urlopen(urllib.request.Request(base+path, data=json.dumps(body).encode(), headers=headers))
            with self.assertRaises(urllib.error.HTTPError) as err:
                post('/api/config', DEFAULTS, custom=False)
            self.assertEqual(err.exception.code, 403)
            with post('/api/config', dict(DEFAULTS, mode='demo')) as response:
                self.assertEqual(response.status, 200)
            self.service.tick()
            with post('/api/record', {'enabled':True}):
                pass
            self.service.tick()
            with urllib.request.urlopen(base+'/api/export?session='+self.service.session) as response:
                self.assertIn(b',demo,ezo-do,', response.read())
            with self.assertRaises(urllib.error.HTTPError):
                post('/api/calibrate', {'kind':'air', 'confirmed':True})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
