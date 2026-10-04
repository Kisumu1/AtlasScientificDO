import json
import unittest
from unittest.mock import MagicMock, patch

from atlas.cockpit import CockpitTelemetry, default_url, values


class CockpitTests(unittest.TestCase):
    def test_real_values_and_invalid_or_demo_sentinel(self):
        snapshot = dict(mode='hardware', status='connected', stale=False,
                        latest=dict(mg_l=8.74, saturation_pct=96.1))
        self.assertEqual(values(snapshot), dict(ATLAS_DO=8.74, ATLAS_SAT=96.1, ATLAS_OK=1))
        for change in (dict(mode='demo'), dict(status='disconnected'), dict(stale=True), dict(latest=None)):
            self.assertEqual(values(dict(snapshot, **change)), dict(ATLAS_DO=-1, ATLAS_SAT=-1, ATLAS_OK=0))

    def test_docker_gateway_and_explicit_disable(self):
        with patch.dict('os.environ', {}, clear=True), patch('atlas.cockpit.Path') as path:
            path.return_value.exists.return_value = True
            path.return_value.read_text.return_value = 'Iface Destination Gateway Flags\neth0 00000000 010011AC 0003\n'
            self.assertEqual(default_url(), 'http://172.17.0.1:6040/v1/mavlink')
        with patch.dict('os.environ', {'ATLAS_MAVLINK_URL': ''}, clear=True):
            self.assertEqual(default_url(), '')

    def test_publication_packets_are_sensor_telemetry_only(self):
        with patch.dict('os.environ', {'ATLAS_MAVLINK_URL':'http://host:6040/v1/mavlink', 'ATLAS_SYSTEM_ID':'3'}):
            bridge = CockpitTelemetry(lambda: None)
        with patch('atlas.cockpit.urlopen', return_value=MagicMock()) as send:
            bridge.publish(dict(mode='hardware', status='connected', stale=False,
                                latest=dict(mg_l=0, saturation_pct=0)))
        packets = [json.loads(call.args[0].data) for call in send.call_args_list]
        self.assertEqual(len(packets), 3)
        self.assertEqual([p['header']['sequence'] for p in packets], [0, 1, 2])
        self.assertTrue(all(p['message']['type'] == 'NAMED_VALUE_FLOAT' for p in packets))
        self.assertTrue(all(p['header']['system_id'] == 3 and p['header']['component_id'] == 1 for p in packets))
        self.assertEqual([p['message']['value'] for p in packets], [0, 0, 1])
        self.assertTrue(all(len(p['message']['name']) == 10 for p in packets))
        self.assertTrue(all(call.kwargs['timeout'] == 1 for call in send.call_args_list))

    def test_network_failure_does_not_escape_worker(self):
        with patch.dict('os.environ', {'ATLAS_MAVLINK_URL':'http://host:6040/v1/mavlink'}):
            bridge = CockpitTelemetry(lambda: {})
        with patch.object(bridge, 'publish', side_effect=OSError('offline')), patch.object(bridge.stop, 'wait', side_effect=lambda _: bridge.stop.set()):
            bridge.run()
        self.assertEqual(bridge.status, 'unavailable')
        self.assertEqual(bridge.error, 'offline')
