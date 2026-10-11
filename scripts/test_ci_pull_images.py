import os
import subprocess
import unittest
from unittest.mock import call, patch

import ci_pull_images as ci


class PullImagesTests(unittest.TestCase):
    def result(self, code=0, error=""):
        return subprocess.CompletedProcess([], code, stdout="", stderr=error)

    @patch.object(ci.time, "sleep")
    @patch.object(ci.subprocess, "run")
    def test_rate_limit_retries_then_succeeds(self, run, sleep):
        run.side_effect = [self.result(1, "toomanyrequests: Rate exceeded"), self.result()]
        ci.pull("public.ecr.aws/docker/library/redis:7")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0], run.call_args_list[1])
        sleep.assert_called_once_with(15)

    @patch.object(ci.time, "sleep")
    @patch.object(ci.subprocess, "run")
    def test_exhausted_retries_fail_ci(self, run, sleep):
        run.return_value = self.result(1, "429 Too Many Requests")
        with self.assertRaises(RuntimeError):
            ci.pull("redis:7")
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(15), call(30)])

    @patch.object(ci.time, "sleep")
    @patch.object(ci.subprocess, "run")
    def test_permanent_errors_are_not_retried(self, run, sleep):
        for error in ("manifest unknown", "unauthorized: authentication required"):
            with self.subTest(error=error):
                run.reset_mock()
                run.return_value = self.result(1, error)
                with self.assertRaises(RuntimeError):
                    ci.pull("redis:bad-tag")
                run.assert_called_once()
        sleep.assert_not_called()

    @patch.object(ci.time, "sleep")
    @patch.object(ci.subprocess, "run")
    def test_network_timeout_is_bounded_and_retried(self, run, sleep):
        run.side_effect = [subprocess.TimeoutExpired(["docker"], 300), self.result()]
        ci.pull("redis:7")
        self.assertEqual(run.call_args.kwargs["timeout"], 300)
        sleep.assert_called_once_with(15)

    @patch.dict(os.environ, dict(zip(ci.IMAGE_KEYS, ["python:test", "postgres:test", "redis:test"])))
    @patch.object(ci, "pull")
    def test_all_images_are_pulled_in_order(self, pull):
        ci.main()
        self.assertEqual(pull.call_args_list, [call("python:test"), call("postgres:test"), call("redis:test")])

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(ci, "pull")
    def test_missing_configuration_fails_before_pulling(self, pull):
        with self.assertRaises(RuntimeError):
            ci.main()
        pull.assert_not_called()


if __name__ == "__main__":
    unittest.main()
