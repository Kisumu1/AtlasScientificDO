"""Fresh USB RTD measurements with an explicit manual fallback."""
import os
import time

from .sensors import EzoRTD, SensorError


class TemperatureSource:
    def __init__(self):
        self.sensor = None
        self.port = ''
        self.retry_at = 0
        self.last_error = ''

    def close(self):
        if self.sensor is not None:
            try:
                self.sensor.close()
            finally:
                self.sensor = None
        self.port = ''

    def sample(self, config, ports, timestamp):
        result = dict(effective_c=config['temperature_c'], source='manual',
                      port='', timestamp_utc=None, error='')
        if config['mode'] != 'hardware' or config['temperature_source'] == 'manual':
            self.close()
            return result
        result['source'] = 'manual_fallback'
        result['error'] = self.last_error or 'USB temperature sensor unavailable; using manual temperature.'
        now = time.monotonic()
        if self.sensor is None and now < self.retry_at:
            return result
        try:
            if self.sensor is None:
                # DO owns its device. Skip all aliases of that USB port.
                excluded = os.path.realpath(config['port'])
                selected = config['temperature_port']
                devices = [selected] if selected else [p['device'] for p in ports()]
                candidates, seen = [], {excluded}
                try:
                    for device in devices:
                        real = os.path.realpath(device)
                        if real in seen:
                            continue
                        seen.add(real)
                        try:
                            sensor = EzoRTD(device, config['temperature_baud'])
                        except Exception:
                            continue
                        candidates.append((device, sensor))
                    if len(candidates) != 1:
                        raise SensorError('Multiple USB EZO-RTDs found; select a temperature USB device.'
                                          if candidates else 'No USB EZO-RTD found; using manual temperature.')
                    self.port, self.sensor = candidates.pop()
                finally:
                    for _, sensor in candidates:
                        sensor.close()
            value = self.sensor.read()
            self.last_error = ''
            return dict(effective_c=value, source='ezo_rtd', port=self.port,
                        timestamp_utc=timestamp(), error='')
        except Exception as exc:
            self.close()
            self.retry_at = now + 10
            result['error'] = str(exc)
            self.last_error = result['error']
            return result
