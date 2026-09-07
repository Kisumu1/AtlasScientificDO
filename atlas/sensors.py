"""Sensor drivers. Add future Atlas drivers here without changing the HTTP API."""
import math
import time

import serial


class SensorError(Exception):
    pass


def parse_do(line):
    try:
        values = [float(x) for x in line.split(',')]
    except ValueError as exc:
        raise SensorError('Invalid dissolved oxygen response') from exc
    if len(values) != 2 or not all(math.isfinite(x) for x in values):
        raise SensorError('Expected mg/L and percent saturation from the EZO-DO')
    if not (0 <= values[0] <= 100 and 0 <= values[1] <= 350):
        raise SensorError('Reading outside the EZO-DO measurement range')
    return {'mg_l': values[0], 'saturation_pct': values[1]}


class EzoDO:
    def __init__(self, port, baud):
        self.serial = serial.Serial(port, baudrate=baud, timeout=0.1,
                                    write_timeout=1, exclusive=True)
        try:
            # Identify before changing device settings. Query also works if *OK is off.
            self.identity = self.command('i', prefix='?i,', identify=True)[0]
            if not self.identity.upper().startswith('?I,D.O.,'):
                raise SensorError('Selected port is not an Atlas EZO-DO circuit')
            # Stop unsolicited samples, then enable acknowledgements for transactions.
            for cmd in ('C,0', '*OK,1'):
                self.serial.write((cmd + '\r').encode('ascii'))
                self.serial.flush()
                time.sleep(0.7)
                self.serial.reset_input_buffer()
            self.command('C,0')
            self.command('O,mg,1')
            self.command('O,%,1')
        except Exception:
            self.close()
            raise

    def command(self, command, prefix=None, identify=False):
        self.serial.reset_input_buffer()
        self.serial.write((command + '\r').encode('ascii'))
        self.serial.flush()
        deadline = time.monotonic() + 3
        payload, buffer = [], bytearray()
        while time.monotonic() < deadline:
            byte = self.serial.read(1)
            if not byte:
                continue
            if byte in (b'\r', b'\n'):
                if not buffer:
                    continue
                line = buffer.decode('ascii', errors='strict').strip()
                buffer.clear()
                if line == '*OK':
                    if identify:
                        continue
                    if prefix and not any(s.startswith(prefix) for s in payload):
                        raise SensorError('Sensor acknowledged without the requested data')
                    return payload
                if line.startswith('*'):
                    raise SensorError('EZO status: ' + line)
                if prefix is None or line.startswith(prefix):
                    payload.append(line)
                    if identify:
                        return payload
            else:
                buffer.extend(byte)
                if len(buffer) > 256:
                    raise SensorError('Oversized serial response; check port and baud rate')
        raise SensorError('EZO timeout; check UART mode, baud rate, cable, and USB mapping')

    def compensate(self, config):
        self.command(f"T,{config['temperature_c']}")
        self.command(f"S,{config['salinity_ppt']},ppt")
        self.command(f"P,{config['pressure_kpa']}")

    def calibration(self):
        reply = self.command('Cal,?', prefix='?Cal,')[0]
        try:
            points = int(reply.split(',')[1])
        except (IndexError, ValueError) as exc:
            raise SensorError('Invalid calibration status') from exc
        if points not in (0, 1, 2):
            raise SensorError('Unknown calibration status')
        return points

    def calibrate(self, kind):
        self.command({'air': 'Cal', 'zero': 'Cal,0'}[kind])
        return self.calibration()

    def read(self):
        lines = self.command('R')
        if len(lines) != 1:
            raise SensorError('Missing or ambiguous EZO reading')
        return parse_do(lines[0])

    def close(self):
        self.serial.close()


class DemoDO:
    identity = 'Simulated EZO-DO — no hardware connected'

    def compensate(self, config):
        pass

    def calibration(self):
        return None

    def read(self):
        t = time.monotonic()
        value = 8.1 + 0.24 * math.sin(t / 18) + 0.06 * math.sin(t / 3)
        return {'mg_l': round(value, 2), 'saturation_pct': round(value / 9.09 * 100, 1)}

    def close(self):
        pass
