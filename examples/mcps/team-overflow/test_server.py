import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from server import execute


class SeatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'queue.sqlite')
        init = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}
        out = subprocess.check_output([sys.executable, str(Path(__file__).with_name("server.py")),
                                      "--database", self.path, "--seat", "one"], input=json.dumps(init)+"\n", text=True)
        self.assertEqual(json.loads(out)["result"]["protocolVersion"], "2025-06-18")
        self.ref = {"reference":"https://github.com/example/project/issues/1"}

    def call(self, seat, tool, args):
        db = sqlite3.connect(self.path)
        try:
            with db:
                return execute(db, seat, tool, args)
        finally:
            db.close()

    def test_queue(self):
        def offer(_):
            return self.call("one","offer",dict(self.ref,provider="codex"))
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(list(pool.map(offer,range(2))), [{"state":"offered"}]*2)
        with self.assertRaises(ValueError):
            self.call("two","claim",self.ref)
        self.assertEqual(self.call("two","status",{})["jobs"], [])
        for action,state in [("claim","claimed"),("claim","claimed"),("release","offered"),
                             ("claim","claimed"),("finish","done")]:
            self.assertEqual(self.call("one",action,self.ref)["state"],state)

    def test_usage(self):
        sample = dict(minutes=300, used_percent=25, reset_at=int(time.time())+60)
        self.call("one","publish_usage",dict(provider="claude",windows=[sample]))
        self.assertEqual(self.call("one","status",{})["usage"][0]["windows"],[sample])
        for invalid in (dict(sample, token="secret"), dict(sample,used_percent=101)):
            with self.assertRaises(ValueError):
                self.call("one","publish_usage",dict(provider="claude",windows=[invalid]))
        self.assertEqual(self.call("two","status",{})["usage"],[])


if __name__ == "__main__":
    unittest.main()
