import unittest
from unittest.mock import MagicMock, patch
from atlas.cockpit import CockpitTelemetry, default_endpoint, named_value_packet, values

class CockpitTests(unittest.TestCase):
    def test_real_values_and_invalid_or_demo_sentinel(self):
        snapshot = dict(mode='hardware', status='connected', stale=False, latest=dict(mg_l=8.74, saturation_pct=96.1))
        self.assertEqual(values(snapshot), dict(ATLAS_DO=8.74, ATLAS_SAT=96.1, ATLAS_OK=1))
        for change in (dict(mode='demo'), dict(status='disconnected'), dict(stale=True), dict(latest=None)):
            self.assertEqual(values(dict(snapshot, **change)), dict(ATLAS_DO=-1, ATLAS_SAT=-1, ATLAS_OK=0))

    def test_docker_gateway_and_explicit_disable(self):
        with patch.dict('os.environ', {}, clear=True), patch('atlas.cockpit.Path') as path:
            path.return_value.exists.return_value = True
            path.return_value.read_text.return_value = 'Iface Destination Gateway Flags\neth0 00000000 010011AC 0003\n'
            self.assertEqual(default_endpoint(), '172.17.0.1:14660')
        with patch.dict('os.environ', {'ATLAS_MAVLINK_UDP': ''}, clear=True):
            self.assertEqual(default_endpoint(), '')

    def test_wire_packet_matches_pymavlink_reference(self):
        # Reference generated with pymavlink's common dialect, MAVLink 1.
        self.assertEqual(named_value_packet(1, 0, 1234, 'ATLAS_DO', 8.74).hex(),
                         'fe12000119fbd20400000ad70b4141544c41535f444f00000868')

    def test_publication_and_read_only_confirmation(self):
        with patch.dict('os.environ', {'ATLAS_MAVLINK_UDP':'host:14660', 'ATLAS_SYSTEM_ID':'3'}, clear=True):
            bridge = CockpitTelemetry(lambda: None)
        with patch('atlas.cockpit.socket.socket') as udp, patch('atlas.cockpit.urlopen') as read, patch('atlas.cockpit.json.load', return_value={'message':{'time_boot_ms':0}}), patch('atlas.cockpit.time.monotonic', return_value=bridge.started):
            bridge.publish(dict(mode='hardware', status='connected', stale=False, latest=dict(mg_l=0, saturation_pct=0)))
        packets=[call.args[0] for call in udp.return_value.__enter__.return_value.sendto.call_args_list]
        self.assertEqual(len(packets),3)
        self.assertEqual([p[2] for p in packets], [0,1,2])
        self.assertTrue(all(p[3:6] == bytes((3,25,251)) for p in packets))
        self.assertEqual(read.call_args.args[0], 'http://host:6040/v1/mavlink/vehicles/3/components/25/messages/NAMED_VALUE_FLOAT')

    def test_unconfirmed_delivery_is_an_error(self):
        with patch.dict('os.environ', {'ATLAS_MAVLINK_UDP':'host:14660'}, clear=True):
            bridge=CockpitTelemetry(lambda: None)
        with patch('atlas.cockpit.socket.socket'), patch('atlas.cockpit.urlopen'), patch('atlas.cockpit.json.load', return_value={'message':{'time_boot_ms':-1}}):
            with self.assertRaisesRegex(OSError, 'not received'):
                bridge.publish(dict(mode='demo',status='connected',stale=False,latest=None))

    def test_network_failure_does_not_escape_worker(self):
        with patch.dict('os.environ', {'ATLAS_MAVLINK_UDP':'host:14660'}, clear=True):
            bridge=CockpitTelemetry(lambda: {})
        with patch.object(bridge,'publish',side_effect=OSError('offline')), patch.object(bridge.stop,'wait',side_effect=lambda _:bridge.stop.set()):
            bridge.run()
        self.assertEqual(bridge.status,'unavailable')
        self.assertEqual(bridge.error,'offline')

