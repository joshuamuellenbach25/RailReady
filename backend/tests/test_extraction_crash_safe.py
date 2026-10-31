"""Regression: an extraction deadline / native llama abort must not take down the API process.
No real model is loaded and no AI call is made: the child-process call is replaced with stand-ins (tests/_fake_llama_child.py).
Run from backend/: python -m unittest tests.test_extraction_crash_safe -v"""
import asyncio
import os
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import ai_local  # noqa: E402
import _fake_llama_child as fake  # noqa: E402


class ExtractionCrashSafety(unittest.TestCase):
    def setUp(self):
        self.orig = ai_local._child_complete
        self.orig_timeout = ai_local.CALL_TIMEOUT_S

    def tearDown(self):
        ai_local._child_complete = self.orig
        ai_local.CALL_TIMEOUT_S = self.orig_timeout
        if ai_local._pool is not None:
            ai_local._discard_pool(ai_local._pool)

    def test_native_abort_kills_only_the_child(self):
        ai_local._child_complete = fake.abort_now
        res = ai_local.extract("replace 4 ties")
        self.assertEqual(res["status"], "Failed")
        self.assertEqual(res["error_stage"], "model_process")
        self.assertIn("stopped unexpectedly", res["error"])
        self.assertTrue(res["error"].endswith("Retry"))
        # the test (API) process is still alive and the next call gets a fresh child
        ai_local._child_complete = fake.ok
        self.assertEqual(ai_local.extract("replace 4 ties")["status"], "Done")

    def test_overrun_abandons_the_child_not_the_api(self):
        ai_local._child_complete = fake.sleep_long
        ai_local.CALL_TIMEOUT_S = 2
        ai_local.extract  # warm import
        t0 = time.time()
        pool = ai_local._get_pool()
        res = ai_local.extract("replace 4 ties")
        self.assertLess(time.time() - t0, 20)
        self.assertEqual(res["error_stage"], "model_process")
        self.assertIn("did not answer within 2s", res["error"])
        self.assertIsNot(ai_local._pool, pool)  # the overrunning child (and its llama context) was discarded
        ai_local._child_complete = fake.ok
        self.assertEqual(ai_local.extract("x")["status"], "Done")

    def test_calls_are_serialized_never_concurrent(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log = f.name
        os.environ["P17_FAKE_LOG"] = log
        ai_local._child_complete = fake.ok_logged
        out = []
        ts = [threading.Thread(target=lambda: out.append(ai_local.extract("x")["status"])) for _ in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(out, ["Done"] * 3)
        ev = [line.split() for line in open(log)]
        self.assertEqual([e[0] for e in ev], ["start", "end"] * 3)  # never two decodes in flight
        self.assertEqual(len({e[2] for e in ev}), 1)  # one child owns the single context
        os.unlink(log)

    def test_job_deadline_then_retry_does_not_crash(self):
        """Failure sequence: job deadline cancels the coroutine while the decode keeps running, then a retry starts."""
        ai_local._child_complete = fake.sleep_long
        ai_local.CALL_TIMEOUT_S = 3

        async def run():
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.to_thread(ai_local.extract, "first"), timeout=1)  # the job deadline
            ai_local._child_complete = fake.ok  # the retry arrives while the first decode is still running
            return await asyncio.wait_for(asyncio.to_thread(ai_local.extract, "retry"), timeout=30)
        res = asyncio.run(run())
        self.assertEqual(res["status"], "Done")  # waited its turn, ran in a fresh child; this process never aborted


class JobsMarksRetryable(unittest.TestCase):
    def test_model_process_failure_is_retryable(self):
        src = open(os.path.join(os.path.dirname(HERE), "jobs.py")).read()
        i = src.index('if res["error_stage"] == "model_process"')
        self.assertIn('"retryable": True', src[i:i + 400])
        self.assertIn('"error_stage": "deadline", "retryable": True', src)


if __name__ == "__main__":
    unittest.main()
