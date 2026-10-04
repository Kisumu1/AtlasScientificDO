"""Read-only Cockpit data stream; never sends MAVLink or sensor commands."""
import logging
import select
import threading
from wsproto import ConnectionType, WSConnection
from wsproto.events import AcceptConnection, CloseConnection, Ping, TextMessage


def values(snapshot):
    live = snapshot['mode'] == 'hardware' and snapshot['status'] == 'connected' and not snapshot['stale']
    latest = snapshot['latest'] if live else None
    return {'Atlas oxygen': latest['mg_l'] if latest else -1,
            'Atlas saturation': latest['saturation_pct'] if latest else -1,
            'Atlas connected': int(bool(latest))}


class CockpitTelemetry:
    def __init__(self, measurement):
        self.measurement = measurement
        self.stop = threading.Event()
        self.clients = 0
        self.lock = threading.Lock()

    def stream(self, handler):
        protocol = WSConnection(ConnectionType.SERVER)
        headers = [(key.encode('ascii'), value.encode('latin-1')) for key, value in handler.headers.items()]
        try:
            protocol.initiate_upgrade_connection(headers, handler.path)
            list(protocol.events())
            handler.connection.sendall(protocol.send(AcceptConnection()))
        except Exception:
            return handler.send({'error': 'Expected a WebSocket connection'}, status=400)
        handler.close_connection = True
        handler.connection.settimeout(3)
        with self.lock:
            self.clients += 1
        try:
            while not self.stop.is_set():
                for name, value in values(self.measurement()).items():
                    handler.connection.sendall(protocol.send(TextMessage(data=f'{name}={value}')))
                if select.select([handler.connection], [], [], 2)[0]:
                    data = handler.connection.recv(4096)
                    if not data:
                        break
                    protocol.receive_data(data)
                    for event in protocol.events():
                        if isinstance(event, CloseConnection):
                            handler.connection.sendall(protocol.send(event.response()))
                            return
                        if isinstance(event, Ping):
                            handler.connection.sendall(protocol.send(event.response()))
                        if isinstance(event, TextMessage):
                            # This endpoint accepts no hardware/settings commands.
                            handler.connection.sendall(protocol.send(CloseConnection(code=1003, reason='Read-only stream')))
                            return
        except Exception as exc:
            logging.debug('Cockpit stream closed: %s', exc)
        finally:
            with self.lock:
                self.clients -= 1

    def state(self):
        with self.lock:
            return dict(status='connected' if self.clients else 'ready', clients=self.clients, error='')

    def close(self):
        self.stop.set()
