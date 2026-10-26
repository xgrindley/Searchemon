import os
import tempfile
import threading
import time
import unittest

from restock.engine import Monitor


class ShutdownSpeed(unittest.TestCase):
    def test_many_slow_loops_share_one_wait(self):
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        open(cfg, "w").write("discord: {webhooks: {}}\nwatchlist: []\nsearches: []\n"
                             "discovery: {enabled: false, places: false}\n")
        m = Monitor(cfg)
        release = threading.Event()
        # Eight loops stuck in a slow request: the old code waited 5 s for each, one after another.
        m.threads = [threading.Thread(target=release.wait, args=(30,), daemon=True) for _ in range(8)]
        for t in m.threads:
            t.start()
        t0 = time.time()
        m.stop(wait=0.6)
        took = time.time() - t0
        release.set()
        self.assertLess(took, 2.0)

    def test_close_twice_is_safe(self):
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        open(cfg, "w").write("discord: {webhooks: {}}\nwatchlist: []\nsearches: []\n"
                             "discovery: {enabled: false, places: false}\n")
        m = Monitor(cfg)
        m.close()
        m.close()


if __name__ == "__main__":
    unittest.main()


class PowerSettings(unittest.TestCase):
    def test_never_raises_and_reads_settings(self):
        from restock import power
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "config.yaml")
        open(path, "w").write("power:\n  low_priority: true\n  keep_awake: false\n")
        self.assertEqual(power.read_settings(path), {"low_priority": True, "keep_awake": False})
        self.assertEqual(power.read_settings(os.path.join(tmp, "missing.yaml")), {})
        self.assertIsInstance(power.apply({"low_priority": True}), list)
