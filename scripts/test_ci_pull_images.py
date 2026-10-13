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

    @patch.dict(os.environ, dict(zip(ci.IMAGE_KEYS, ["python:test", "postgres:test", "redis:test"])), clear=True)
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


    @patch.object(ci.subprocess, "run")
    @patch.object(ci, "pull")
    def test_transient_exhaustion_pulls_and_tags_explicit_fallback(self, pull, run):
        pull.side_effect = [ci.TransientPullError("Data limit exceeded"), None]
        ci.pull_with_fallback("primary:tag", "official:tag")
        self.assertEqual(pull.call_args_list, [call("primary:tag"), call("official:tag")])
        run.assert_called_once_with(["docker", "tag", "official:tag", "primary:tag"], check=True, timeout=30)

    @patch.object(ci.subprocess, "run")
    @patch.object(ci, "pull")
    def test_success_does_not_use_fallback(self, pull, run):
        ci.pull_with_fallback("primary:tag", "official:tag")
        pull.assert_called_once_with("primary:tag")
        run.assert_not_called()

    @patch.object(ci.subprocess, "run")
    @patch.object(ci, "pull")
    def test_permanent_error_never_switches_registries(self, pull, run):
        pull.side_effect = RuntimeError("manifest unknown")
        with self.assertRaises(RuntimeError):
            ci.pull_with_fallback("primary:tag", "official:tag")
        pull.assert_called_once_with("primary:tag")
        run.assert_not_called()

    @patch.object(ci.subprocess, "run")
    @patch.object(ci, "pull")
    def test_failed_fallback_is_not_tagged(self, pull, run):
        pull.side_effect = [ci.TransientPullError("429"), ci.TransientPullError("429")]
        with self.assertRaises(ci.TransientPullError):
            ci.pull_with_fallback("primary:tag", "official:tag")
        run.assert_not_called()

    @patch.object(ci.subprocess, "run")
    @patch.object(ci, "pull")
    def test_tag_failure_remains_fatal(self, pull, run):
        pull.side_effect = [ci.TransientPullError("429"), None]
        run.side_effect = subprocess.CalledProcessError(1, ["docker", "tag"])
        with self.assertRaises(subprocess.CalledProcessError):
            ci.pull_with_fallback("primary:tag", "official:tag")

    @patch.dict(os.environ, {"PYTHON_IMAGE": "primary:tag", "POSTGRES_IMAGE": "postgres:16", "REDIS_IMAGE": "redis:7", "PYTHON_IMAGE_FALLBACK": "official:tag"}, clear=True)
    @patch.object(ci, "pull_with_fallback")
    @patch.object(ci, "pull")
    def test_main_uses_only_explicit_fallback_configuration(self, pull, fallback):
        ci.main()
        fallback.assert_called_once_with("primary:tag", "official:tag")
        self.assertEqual(pull.call_args_list, [call("postgres:16"), call("redis:7")])


    @patch.object(ci.time, "sleep")
    @patch.object(ci.subprocess, "run")
    def test_actual_ecr_data_limit_uses_fallback_after_three_attempts(self, run, sleep):
        run.side_effect = [self.result(1, "toomanyrequests: Data limit exceeded")] * 3 + [self.result(), self.result()]
        ci.pull_with_fallback("public.ecr.aws/docker/library/python:3.12-slim", "docker.io/library/python:3.12-slim")
        commands = [entry.args[0] for entry in run.call_args_list]
        self.assertEqual(commands[:3], [["docker", "pull", "public.ecr.aws/docker/library/python:3.12-slim"]] * 3)
        self.assertEqual(commands[3], ["docker", "pull", "docker.io/library/python:3.12-slim"])
        self.assertEqual(commands[4], ["docker", "tag", "docker.io/library/python:3.12-slim", "public.ecr.aws/docker/library/python:3.12-slim"])
        self.assertEqual(sleep.call_args_list, [call(15), call(30)])


if __name__ == "__main__":
    unittest.main()
