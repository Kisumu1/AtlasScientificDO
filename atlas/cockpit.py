"""Publish sensor telemetry through a BlueOS MAVLink router UDP input."""
import json
import logging
import os
from pathlib import Path
import socket
import struct
import threading
import time
from urllib.request import urlopen


def default_endpoint():
    if 'ATLAS_MAVLINK_UDP' in os.environ:
        return os.environ['ATLAS_MAVLINK_UDP']
    if not Path('/.dockerenv').exists():
        return ''
    try:
        for line in Path('/proc/net/route').read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == '00000000' and int(fields[3], 16) & 2:
                host = socket.inet_ntoa(struct.pack('<I', int(fields[2], 16)))
                # BlueOS's default Ping360 Heading UDP server accepts MAVLink telemetry.
                return f'{host}:14660'
    except (OSError, ValueError, IndexError):
        pass
    return ''


def values(snapshot):
    live = snapshot['mode'] == 'hardware' and snapshot['status'] == 'connected' and not snapshot['stale']
    latest = snapshot['latest'] if live else None
    return {'ATLAS_DO': latest['mg_l'] if latest else -1,
            'ATLAS_SAT': latest['saturation_pct'] if latest else -1,
            'ATLAS_OK': int(bool(latest))}


def named_value_packet(system_id, sequence, stamp, name, value):
    # MAVLink 1 NAMED_VALUE_FLOAT (251), wire order uint32, float, char[10].
    payload = struct.pack('<If10s', stamp, value, name.encode('ascii').ljust(10, b'\0'))
    header = bytes((len(payload), sequence, system_id, 25, 251))
    crc = 0xffff
    for byte in header + payload + bytes((170,)):
        tmp = byte ^ (crc & 0xff)
        tmp = (tmp ^ (tmp << 4)) & 0xff
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xffff
    return b'\xfe' + header + payload + struct.pack('<H', crc)


class CockpitTelemetry:
    def __init__(self, measurement):
        self.measurement = measurement
        endpoint = default_endpoint()
        self.address = None
        self.verify_url = ''
        if endpoint:
            host, port = endpoint.rsplit(':', 1)
            self.address = (host, int(port))
            self.verify_url = os.environ.get('ATLAS_MAVLINK_URL', f'http://{host}:6040/v1/mavlink').rstrip('/')
        self.system_id = int(os.environ.get('ATLAS_SYSTEM_ID', '1'))
        if not 1 <= self.system_id <= 255:
            raise ValueError('ATLAS_SYSTEM_ID must be between 1 and 255')
        self.sequence = 0
        self.started = time.monotonic()
        self.error = ''
        self.status = 'waiting' if self.address else 'disabled'
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def publish(self, snapshot):
        stamp = int((time.monotonic() - self.started) * 1000) % (2**32)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for name, value in values(snapshot).items():
                sender.sendto(named_value_packet(self.system_id, self.sequence, stamp, name, value), self.address)
                self.sequence = (self.sequence + 1) % 256
        # UDP delivery is not guaranteed. Confirm ingestion, using read-only REST.
        if self.verify_url:
            self.stop.wait(0.2)
            url = f'{self.verify_url}/vehicles/{self.system_id}/components/25/messages/NAMED_VALUE_FLOAT'
            with urlopen(url, timeout=1) as response:
                message = json.load(response)['message']
            if message['time_boot_ms'] != stamp:
                raise OSError('BlueOS has not received sensor telemetry. Check the MAVLink UDP endpoint.')

    def run(self):
        if not self.address:
            return
        while not self.stop.is_set():
            try:
                self.publish(self.measurement())
                self.status, self.error = 'publishing', ''
            except Exception as exc:
                self.status, self.error = 'unavailable', str(exc)
                logging.debug('Cockpit telemetry unavailable: %s', exc)
            self.stop.wait(2 if self.status == 'publishing' else 10)

    def state(self):
        return dict(status=self.status, error=self.error)

    def close(self):
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=8)
