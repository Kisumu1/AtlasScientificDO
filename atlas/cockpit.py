"""Publish named sensor telemetry for Cockpit's native bar indicators."""
import json
import logging
import os
from pathlib import Path
import socket
import struct
import threading
import time
from urllib.request import Request, urlopen


def default_url():
    if 'ATLAS_MAVLINK_URL' in os.environ:
        return os.environ['ATLAS_MAVLINK_URL'].rstrip('/')
    # BlueOS extensions run on Docker's bridge; reach the host without extra mounts.
    if not Path('/.dockerenv').exists():
        return ''
    try:
        for line in Path('/proc/net/route').read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == '00000000' and int(fields[3], 16) & 2:
                host = socket.inet_ntoa(struct.pack('<I', int(fields[2], 16)))
                return f'http://{host}:6040/v1/mavlink'
    except (OSError, ValueError, IndexError):
        pass
    return ''


def values(snapshot):
    # Demo readings never enter vehicle telemetry. -1 means unavailable, not zero oxygen.
    live = snapshot['mode'] == 'hardware' and snapshot['status'] == 'connected' and not snapshot['stale']
    latest = snapshot['latest'] if live else None
    return {'ATLAS_DO': latest['mg_l'] if latest else -1,
            'ATLAS_SAT': latest['saturation_pct'] if latest else -1,
            'ATLAS_OK': int(bool(latest))}


class CockpitTelemetry:
    def __init__(self, measurement):
        self.measurement = measurement
        self.url = default_url()
        self.system_id = int(os.environ.get('ATLAS_SYSTEM_ID', '1'))
        if not 1 <= self.system_id <= 255:
            raise ValueError('ATLAS_SYSTEM_ID must be between 1 and 255')
        self.sequence = 0
        self.started = time.monotonic()
        self.error = ''
        self.status = 'waiting' if self.url else 'disabled'
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def publish(self, snapshot):
        stamp = int((time.monotonic() - self.started) * 1000) % (2**32)
        for name, value in values(snapshot).items():
            # Older Cockpit versions only accept named values from component 1.
            # These uniquely named sensor values never send vehicle control commands.
            packet = dict(header=dict(system_id=self.system_id, component_id=1, sequence=self.sequence),
                          message=dict(type='NAMED_VALUE_FLOAT', time_boot_ms=stamp,
                                       name=list(name.ljust(10, '\0')), value=value))
            request = Request(self.url, data=json.dumps(packet, allow_nan=False).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=1) as response:
                response.read(1024)
            self.sequence = (self.sequence + 1) % 256

    def run(self):
        if not self.url:
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
