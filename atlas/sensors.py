"""Sensor drivers. Add future Atlas drivers here without changing the HTTP API."""
import math
import os
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


class LinuxI2CBus:
    """Raw Linux I2C transactions; no SMBus register/length bytes are inserted."""
    def __init__(self, path, address):
        import fcntl  # Linux only, imported lazily so desktop demo/tests still work.
        self.fd = os.open(path, os.O_RDWR)
        try:
            fcntl.ioctl(self.fd, 0x0703, address)  # I2C_SLAVE; never force a claimed address.
        except Exception:
            self.close()
            raise

    def write(self, data):
        if os.write(self.fd, data) != len(data):
            raise SensorError('Incomplete I2C command')

    def read(self, length):
        return os.read(self.fd, length)

    def close(self):
        os.close(self.fd)


class EzoDOI2C(EzoDO):
    """EZO-DO on the original isolated carrier, connected to Navigator I2C."""
    def __init__(self, path, address):
        self.bus = LinuxI2CBus(path, address)
        try:
            self.identity = self.command('i', prefix='?i,')[0]
            if not self.identity.upper().startswith('?I,D.O.,'):
                raise SensorError('Selected I2C address is not an Atlas EZO-DO circuit')
            self.command('O,mg,1')
            self.command('O,%,1')
        except Exception:
            self.close()
            raise

    def command(self, command, prefix=None, identify=False):
        self.bus.write(command.encode('ascii'))
        # Separate transactions with a STOP between them, as required by Atlas.
        time.sleep(0.9 if command == 'R' or command.startswith('Cal') else 0.3)
        for attempt in range(21):
            response = self.bus.read(64)
            if not response:
                raise SensorError('Empty I2C response')
            status = response[0]
            if status == 254:
                time.sleep(0.1)
                continue
            if status != 1:
                description = {2: 'command rejected', 255: 'no data available'}.get(status, 'unknown status')
                raise SensorError(f'EZO I2C {description} ({status})')
            payload = response[1:].split(b'\x00', 1)[0].decode('ascii').strip()
            if prefix and not payload.startswith(prefix):
                raise SensorError('Unexpected EZO I2C response')
            return [payload] if payload else []
        raise SensorError('EZO I2C processing timeout')

    def close(self):
        self.bus.close()


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
