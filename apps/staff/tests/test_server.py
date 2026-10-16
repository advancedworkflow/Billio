"""Santé du serveur : niveaux vert / orange / rouge et alertes de surcharge."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.staff import server


def fake_snapshot(**values):
    gauges = []
    for key, value in values.items():
        peak = value[1] if isinstance(value, tuple) else None
        value = value[0] if isinstance(value, tuple) else value
        gauges.append({'key': key, 'label': key, 'value': value, 'display': str(value), 'detail': 'détail',
                       'level': server.level(key, value), 'peak': peak, 'peak_level': server.level(key, peak)})
    return {'gauges': gauges, 'history_count': 0}


class ServerHealthTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_levels(self):
        self.assertEqual([server.level('ram', v) for v in (50, 80, 92)], ['ok', 'warning', 'critical'])
        self.assertEqual([server.level('load', v) for v in (0.3, 1.2, 2.5)], ['ok', 'warning', 'critical'])
        self.assertEqual(server.level('cpu', None), 'ok')

    def test_alerts_red_orange_and_past_peak(self):
        items = server.alerts(fake_snapshot(ram=95, swap=30, disk=40, load=(0.2, 2.4)))
        by_key = {i['title'].split(' :')[0].split(' dans')[0]: i for i in items}
        self.assertEqual(by_key['Mémoire presque pleine']['level'], 'critical')
        self.assertEqual(by_key['Le serveur utilise beaucoup le swap']['level'], 'warning')
        self.assertEqual(by_key['Charge du serveur élevée']['level'], 'warning')  # pic passé, valeur actuelle normale
        self.assertIn('pic : 2.4', by_key['Charge du serveur élevée']['title'])
        self.assertTrue(any(i['level'] == 'ok' and i['title'].startswith('disk') for i in items))

    def test_web_workers_saturation(self):
        # 3 workers, 3600 requêtes d'1,8 s en une heure → occupés 60 % du temps
        with mock.patch.dict('os.environ', {'WEB_CONCURRENCY': '3'}):
            self.assertEqual(server.web_busy({'count': 3600, 'avg_ms': 1800})['web_busy'], 60)
            self.assertEqual(server.web_busy({'count': 9000, 'avg_ms': 1800})['web_busy'], 100)

    def test_worker_records_samples_and_run(self):
        server.record_sample()
        server.record_worker_run(420, 600)
        snap = server.snapshot({'count': 0, 'avg_ms': 0})
        run = next(g for g in snap['gauges'] if g['key'] == 'worker_run')
        self.assertEqual((run['value'], run['level']), (70, 'warning'))
        self.assertEqual(server.peaks()['count'], 1)
