import socket
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from wsproto import ConnectionType, WSConnection
from wsproto.events import Request, TextMessage, Ping, Pong, CloseConnection
from atlas.__main__ import handler
from atlas.cockpit import CockpitTelemetry, values

class CockpitTests(unittest.TestCase):
    def test_hardware_only_and_unavailable_sentinels(self):
        snapshot=dict(mode='hardware',status='connected',stale=False,latest=dict(mg_l=0,saturation_pct=0))
        self.assertEqual(values(snapshot),{'Atlas oxygen':0,'Atlas saturation':0,'Atlas connected':1})
        for change in (dict(mode='demo'),dict(status='disconnected'),dict(stale=True),dict(latest=None)):
            self.assertEqual(values(dict(snapshot,**change)),{'Atlas oxygen':-1,'Atlas saturation':-1,'Atlas connected':0})

    def test_real_websocket_stream_ping_and_read_only_close(self):
        snapshot=dict(mode='hardware',status='connected',stale=False,latest=dict(mg_l=8.74,saturation_pct=96.1))
        telemetry=CockpitTelemetry(lambda:snapshot)
        service=SimpleNamespace(cockpit=telemetry)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(service))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        protocol=WSConnection(ConnectionType.CLIENT)
        try:
            with socket.create_connection(server.server_address,timeout=3) as client:
                client.sendall(protocol.send(Request(host='localhost',target='/cockpit/ws')))
                messages=[]
                while len(messages)<3:
                    protocol.receive_data(client.recv(8192))
                    messages.extend(e.data for e in protocol.events() if isinstance(e,TextMessage))
                self.assertEqual(messages[:3],['Atlas oxygen=8.74','Atlas saturation=96.1','Atlas connected=1'])
                self.assertEqual(telemetry.state()['clients'],1)
                client.sendall(protocol.send(Ping(payload=b'check')))
                pong=False
                while not pong:
                    protocol.receive_data(client.recv(8192))
                    pong=any(isinstance(e,Pong) and e.payload==b'check' for e in protocol.events())
                client.sendall(protocol.send(TextMessage(data='calibrate')))
                closed=False
                while not closed:
                    protocol.receive_data(client.recv(8192))
                    closed=any(isinstance(e,CloseConnection) and e.code==1003 for e in protocol.events())
        finally:
            telemetry.close();server.shutdown();server.server_close();thread.join(3)
        self.assertEqual(telemetry.state()['clients'],0)
