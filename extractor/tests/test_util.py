"""The test helpers themselves: game tests must FAIL, not skip silently, when FOUNDRY_GAME_DIR is set but invalid or
when FOUNDRY_REQUIRE_GAME=1 is set and no game is found (UPDATE.md step f relies on this). Each case runs in a
subprocess so the discovery state of this test run is untouched."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from _util import EXTRACTOR, GAME, TESTS, require_game

PROBE = r'''
import io, json, os, sys, unittest
sys.path[:0] = [os.environ['PROBE_TESTS'], os.environ['PROBE_EXTRACTOR']]
if os.environ['PROBE_MODE'] == 'nogame':          # simulate a machine without the game
    import foundry_export.steam as steam
    def not_found(*a, **kw):
        raise steam.GameNotFound(['probe: nothing installed'])
    steam.find_game = not_found
import _util

@_util.require_game
class ClassLevel(unittest.TestCase):
    def test_x(self):
        pass

class MethodLevel(unittest.TestCase):
    @_util.require_game
    def test_y(self):
        pass

load = unittest.defaultTestLoader.loadTestsFromTestCase
r = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([load(ClassLevel), load(MethodLevel)]))
print(json.dumps({'game': str(_util.GAME) if _util.GAME else None, 'problem': _util.GAME_PROBLEM,
                  'skipped': len(r.skipped), 'failed': len(r.failures) + len(r.errors)}))
'''


def probe(mode: str, **env_changes: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ('FOUNDRY_GAME_DIR', 'FOUNDRY_REQUIRE_GAME')}
    env.update(PROBE_MODE=mode, PROBE_TESTS=str(TESTS), PROBE_EXTRACTOR=str(EXTRACTOR))
    env.update({k: v for k, v in env_changes.items() if v is not None})
    r = subprocess.run([sys.executable, '-c', PROBE], capture_output=True, text=True, env=env, timeout=120)
    if r.returncode != 0:
        raise AssertionError(f'probe failed:\n{r.stdout}\n{r.stderr}')
    return json.loads(r.stdout.strip().splitlines()[-1])


class GameDiscoveryTests(unittest.TestCase):
    def test_invalid_env_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = probe('real', FOUNDRY_GAME_DIR=os.path.join(tmp, 'no_such_game'))
        self.assertIsNone(res['game'])
        self.assertIn('FOUNDRY_GAME_DIR is set but invalid', res['problem'])
        self.assertEqual((res['skipped'], res['failed']), (0, 2))

    def test_no_game_skips(self):
        res = probe('nogame')
        self.assertEqual((res['game'], res['problem']), (None, None))
        self.assertEqual((res['skipped'], res['failed']), (2, 0))

    def test_no_game_with_require_fails(self):
        res = probe('nogame', FOUNDRY_REQUIRE_GAME='1')
        self.assertIsNone(res['game'])
        self.assertIn('FOUNDRY_REQUIRE_GAME=1', res['problem'])
        self.assertEqual((res['skipped'], res['failed']), (0, 2))

    @require_game
    def test_valid_env_is_used(self):
        res = probe('real', FOUNDRY_GAME_DIR=str(GAME), FOUNDRY_REQUIRE_GAME='1')
        self.assertEqual((res['game'], res['problem']), (str(GAME), None))
        self.assertEqual((res['skipped'], res['failed']), (0, 0))


if __name__ == '__main__':
    unittest.main()
