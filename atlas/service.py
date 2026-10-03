import csv
import io
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from serial.tools import list_ports
from .sensors import DemoDO, EzoDO, EzoDOI2C, SensorError

DEFAULTS = dict(mode='hardware', port='', baud=9600, interval_s=2,
                temperature_c=20.0, salinity_ppt=0.0, pressure_kpa=101.3,
                transport='uart', i2c_address=97)
FIELDS = ['timestamp_utc', 'mode', 'sensor', 'mg_l', 'saturation_pct',
          'temperature_c', 'salinity_ppt', 'pressure_kpa', 'calibration_points']


def validate_config(raw):
    if not isinstance(raw, dict) or set(raw) != set(DEFAULTS):
        raise ValueError('Provide all connection and compensation settings')
    result = dict(raw)
    if raw['mode'] not in ('hardware', 'demo'):
        raise ValueError('Invalid mode')
    if raw['transport'] not in ('i2c', 'uart'):
        raise ValueError('Choose I2C or UART')
    if type(raw['i2c_address']) is not int or not 8 <= raw['i2c_address'] <= 119:
        raise ValueError('I2C address must be between 8 and 119 (default 97 / 0x61)')
    if not isinstance(raw['port'], str) or len(raw['port']) > 250 or any(ord(c) < 32 for c in raw['port']):
        raise ValueError('Invalid serial port')
    if raw['transport'] == 'i2c' and raw['port'] and not re.fullmatch(r'/dev/i2c-\d+', raw['port']):
        raise ValueError('I2C device must be a path such as /dev/i2c-6')
    if type(raw['baud']) is not int or raw['baud'] not in (300, 1200, 2400, 9600, 19200, 38400, 57600, 115200):
        raise ValueError('Unsupported baud rate')
    for field, low, high in [('interval_s', 1, 60), ('temperature_c', 0, 50),
                             ('salinity_ppt', 0, 42), ('pressure_kpa', 50, 150)]:
        value = raw[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{field} must be between {low} and {high}')
    return result


class Service:
    def __init__(self, directory, demo=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.config_path = self.directory / 'settings.json'
        self.config = dict(DEFAULTS)
        if self.config_path.exists():
            saved = json.loads(self.config_path.read_text())
            # Old USB-only installations keep their explicitly selected UART connection.
            if isinstance(saved, dict) and 'transport' not in saved:
                saved.update(transport='uart', i2c_address=97)
            self.config = validate_config(saved)
        if demo:
            self.config['mode'] = 'demo'
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.sensor = None
        self.status = 'waiting'
        self.error = ''
        self.identity = ''
        self.points = None
        self.latest = None
        self.history = deque(maxlen=1800)
        self.recording = False
        self.session = None
        self.log_error = ''
        self.db = sqlite3.connect(self.directory / 'readings.sqlite3', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, mode TEXT, started TEXT, stopped TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS samples (session TEXT, data TEXT)')
        self.db.execute('CREATE INDEX IF NOT EXISTS samples_session ON samples(session)')
        # A previous unclean shutdown ends that recording rather than silently resuming it.
        self.db.execute('UPDATE sessions SET stopped=? WHERE stopped IS NULL', (self.now(),))
        self.db.commit()
        self.thread = threading.Thread(target=self.run, daemon=True)

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

    @staticmethod
    def ports(transport='uart'):
        if transport == 'i2c':
            return [dict(device=str(p), description='Navigator external I2C' if p.name == 'i2c-6' else 'Linux I2C bus', serial_number=None)
                    for p in sorted(Path('/dev').glob('i2c-*'))]
        ports = [dict(device=p.device, description=p.description, serial_number=p.serial_number)
                 for p in list_ports.comports()]
        if sys.platform != 'linux':
            return ports
        # /dev is mounted from BlueOS, but sysfs metadata may be incomplete in
        # the container. Include USB device nodes even when pySerial misses them.
        ports = {p['device']: p for p in ports
                 if re.fullmatch(r'/dev/tty(?:USB|ACM)\d+', p['device'])}
        for pattern in ('ttyUSB*', 'ttyACM*'):
            for p in sorted(Path('/dev').glob(pattern)):
                if re.fullmatch(r'tty(?:USB|ACM)\d+', p.name):
                    ports.setdefault(str(p), dict(device=str(p), description='USB serial device', serial_number=None))
        # Prefer a stable USB serial identity on the Linux host mounted by BlueOS.
        stable = [dict(device=str(p), description='Stable USB identity: ' + p.name, serial_number=None)
                  for p in sorted(Path('/dev/serial/by-id').glob('*'))
                  if p.exists() and re.fullmatch(r'tty(?:USB|ACM)\d+', p.resolve().name)]
        return stable + [ports[key] for key in sorted(ports)]

    def find_and_connect(self, raw):
        config = validate_config(dict(raw, mode='hardware'))
        with self.lock:
            if self.recording:
                raise ValueError('Stop recording before finding a sensor')
            devices = [p['device'] for p in self.ports(config['transport'])]
            if config['transport'] == 'i2c':
                # Probe only the selected bus/address, or Navigator's external bus.
                devices = [p for p in devices if p == (config['port'] or '/dev/i2c-6')]
            elif config['port'] in devices:
                devices.remove(config['port'])
                devices.insert(0, config['port'])
            if not devices:
                raise SensorError('No matching devices found. Plug the USB carrier into the BlueOS Pi with a data cable, or check the selected I2C bus.')
            self.disconnect()
            seen, errors = set(), []
            for port in devices:
                resolved = os.path.realpath(port)
                if resolved in seen:
                    continue
                seen.add(resolved)
                candidate = None
                adopted = False
                try:
                    candidate = (EzoDO(port, config['baud']) if config['transport'] == 'uart'
                                 else EzoDOI2C(port, config['i2c_address']))
                    candidate.compensate(config)
                    points = candidate.calibration()
                    candidate.read()  # Verify actual measurements before saving the connection.
                    self.configure(dict(config, port=port))
                    self.sensor, self.identity, self.points = candidate, candidate.identity, points
                    adopted = True
                    self.tick()
                    if self.status != 'connected':
                        raise SensorError(self.error)
                    return dict(port=port, identity=self.identity)
                except Exception as exc:
                    if candidate is not None and not adopted:
                        candidate.close()
                    errors.append(f'{port}: {exc}')
            self.status, self.error = 'disconnected', 'No EZO-DO connected. ' + ' | '.join(errors)
            raise SensorError(self.error)

    def disconnect(self):
        if self.sensor:
            self.sensor.close()
        self.sensor = None
        self.identity = ''
        self.points = None

    def configure(self, raw):
        config = validate_config(raw)
        with self.lock:
            if self.recording:
                raise ValueError('Stop recording before changing settings')
            temporary = self.config_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(config, indent=2))
            os.replace(temporary, self.config_path)
            self.disconnect()
            self.config = config
            self.latest = None
            self.history.clear()
            self.status, self.error = 'waiting', ''

    def tick(self):
        with self.lock:
            if self.config['mode'] == 'hardware' and not self.config['port']:
                self.status = 'waiting'
                return
            try:
                if self.sensor is None:
                    self.status = 'connecting'
                    if self.config['mode'] == 'demo':
                        self.sensor = DemoDO()
                    elif self.config['transport'] == 'i2c':
                        self.sensor = EzoDOI2C(self.config['port'], self.config['i2c_address'])
                    else:
                        self.sensor = EzoDO(self.config['port'], self.config['baud'])
                    self.sensor.compensate(self.config)
                    self.points = self.sensor.calibration()
                    self.identity = self.sensor.identity
                values = self.sensor.read()
                sample = dict(timestamp_utc=self.now(), mode=self.config['mode'],
                              sensor='ezo-do', **values, calibration_points=self.points,
                              **{k: self.config[k] for k in ('temperature_c', 'salinity_ppt', 'pressure_kpa')})
                self.latest = sample
                self.history.append(sample)
                self.status, self.error = 'connected', ''
                if self.recording:
                    try:
                        self.db.execute('INSERT INTO samples VALUES (?, ?)', (self.session, json.dumps(sample)))
                        self.db.commit()
                    except sqlite3.Error as exc:
                        self.db.rollback()
                        self.recording = False
                        self.log_error = f'Recording stopped: {exc}'
            except Exception as exc:
                self.error = str(exc)
                self.status = 'disconnected'
                self.disconnect()

    def run(self):
        while not self.stop.is_set():
            started = time.monotonic()
            self.tick()
            delay = self.config['interval_s'] if self.status == 'connected' else 5
            self.stop.wait(max(0.1, delay - (time.monotonic() - started)))

    def state(self):
        with self.lock:
            age = None if self.latest is None else (datetime.now(timezone.utc) -
                  datetime.fromisoformat(self.latest['timestamp_utc'])).total_seconds()
            stale = age is None or age > max(5, self.config['interval_s'] * 2.5) or self.status != 'connected'
            sessions = [dict(id=row[0], mode=row[1], started=row[2], stopped=row[3]) for row in
                        self.db.execute('SELECT * FROM sessions ORDER BY started DESC LIMIT 100')]
            return dict(config=dict(self.config), status=self.status, error=self.error,
                        identity=self.identity, calibration_points=self.points,
                        latest=self.latest, stale=stale, age_s=age, history=list(self.history),
                        recording=self.recording, session=self.session, sessions=sessions,
                        log_error=self.log_error)

    def record(self, enabled):
        with self.lock:
            if enabled and not self.recording:
                if self.status != 'connected':
                    raise ValueError('Connect a sensor or start demo mode first')
                stamp = self.now()
                import uuid
                self.session = uuid.uuid4().hex
                self.db.execute('INSERT INTO sessions VALUES (?, ?, ?, NULL)',
                                (self.session, self.config['mode'], stamp))
                self.db.commit()
                self.recording, self.log_error = True, ''
            elif not enabled and self.recording:
                self.db.execute('UPDATE sessions SET stopped=? WHERE id=?', (self.now(), self.session))
                self.db.commit()
                self.recording = False

    def calibrate(self, kind):
        with self.lock:
            if kind not in ('air', 'zero'):
                raise ValueError('Choose air or zero calibration')
            if self.config['mode'] != 'hardware' or self.sensor is None or self.status != 'connected':
                raise ValueError('Calibration requires connected hardware')
            if self.recording:
                raise ValueError('Stop recording before calibration')
            try:
                self.points = self.sensor.calibrate(kind)
                self.latest = None
                self.history.clear()
            except Exception:
                self.status = 'disconnected'
                self.error = 'Calibration was not confirmed; reconnect and check calibration status'
                self.disconnect()
                raise

    def export(self, session):
        # Separate connection and read transaction produce a streaming snapshot, even during recording.
        db = sqlite3.connect(self.directory / 'readings.sqlite3')
        try:
            if not db.execute('SELECT 1 FROM sessions WHERE id=?', (session,)).fetchone():
                raise ValueError('Recording not found')
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            yield output.getvalue().encode()
            for (raw,) in db.execute('SELECT data FROM samples WHERE session=? ORDER BY rowid', (session,)):
                output.seek(0)
                output.truncate()
                writer.writerow(json.loads(raw))
                yield output.getvalue().encode()
        finally:
            db.close()

    def close(self):
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=20)
        with self.lock:
            self.record(False)
            self.disconnect()
            self.db.close()
