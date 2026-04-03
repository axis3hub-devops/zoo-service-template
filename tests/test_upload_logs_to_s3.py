from unittest.mock import MagicMock, patch


def _make_handler(tmp_path, tool_log_name="step.log"):
    """Build an EoepcaCalrissianRunnerExecutionHandler-like object for tests."""
    workdir_name = "test-workflow-usid123"
    workdir = tmp_path / workdir_name
    workdir.mkdir()

    log_file = workdir / tool_log_name
    log_file.write_text("log content")

    handler = MagicMock()
    handler.conf = {
        "pod_env_vars": {
            "AWS_DEFAULT_REGION": "eu-central-1",
            "AWS_ENDPOINT_URL": "https://s3.example.com",
        },
        "lenv": {
            "Identifier": "test-workflow",
            "usid": "usid123",
        },
        "main": {
            "tmpPath": str(tmp_path),
        },
    }
    handler.aws_access_key_id = "fake-key"
    handler.aws_secret_access_key = "fake-secret"

    return handler, f"./{tool_log_name}"


class TestUploadLogsToS3:
    """Tests for the S3 upload retry logic."""

    def test_upload_succeeds_first_attempt(self, tmp_path, rendered_service_module):
        """Upload succeeds on first try — no retry, no sleep."""
        svc = rendered_service_module
        handler, tool_log = _make_handler(tmp_path)
        mock_s3 = MagicMock()

        with patch.object(svc.boto3, "client", return_value=mock_s3):
            svc.EoepcaCalrissianRunnerExecutionHandler.upload_logs_to_s3(
                handler,
                s3_bucket="test-bucket",
                process_id="proc-1",
                tool_logs=[tool_log],
                aws_access_key_id="fake-key",
                aws_secret_access_key="fake-secret",
            )

        mock_s3.upload_file.assert_called_once()

    def test_upload_succeeds_after_retry(self, tmp_path, rendered_service_module):
        """Upload fails once then succeeds — verify retry with backoff."""
        svc = rendered_service_module
        handler, tool_log = _make_handler(tmp_path)
        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = [
            Exception("connection reset"),
            None,
        ]

        with (
            patch.object(svc.boto3, "client", return_value=mock_s3),
            patch.object(svc.time, "sleep") as mock_sleep,
        ):
            svc.EoepcaCalrissianRunnerExecutionHandler.upload_logs_to_s3(
                handler,
                s3_bucket="test-bucket",
                process_id="proc-1",
                tool_logs=[tool_log],
                aws_access_key_id="fake-key",
                aws_secret_access_key="fake-secret",
            )

        assert mock_s3.upload_file.call_count == 2
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert delay >= svc.S3_UPLOAD_BACKOFF_BASE_SECONDS ** 1
        assert delay <= svc.S3_UPLOAD_BACKOFF_BASE_SECONDS ** 1 + svc.S3_UPLOAD_JITTER_MAX_SECONDS

    def test_upload_fails_all_attempts_returns_false(self, tmp_path, rendered_service_module):
        """All retry attempts fail — upload reports failure without raising."""
        svc = rendered_service_module
        handler, tool_log = _make_handler(tmp_path)
        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = Exception("persistent S3 failure")

        with (
            patch.object(svc.boto3, "client", return_value=mock_s3),
            patch.object(svc.time, "sleep") as mock_sleep,
        ):
            upload_success = svc.EoepcaCalrissianRunnerExecutionHandler.upload_logs_to_s3(
                handler,
                s3_bucket="test-bucket",
                process_id="proc-1",
                tool_logs=[tool_log],
                aws_access_key_id="fake-key",
                aws_secret_access_key="fake-secret",
            )

        assert upload_success is False
        assert mock_s3.upload_file.call_count == svc.S3_UPLOAD_MAX_ATTEMPTS
        assert mock_sleep.call_count == svc.S3_UPLOAD_MAX_ATTEMPTS - 1

    def test_upload_skips_interceptor_logs(self, tmp_path, rendered_service_module):
        """Interceptor logs are skipped — no upload attempted."""
        svc = rendered_service_module
        handler, _ = _make_handler(tmp_path)
        mock_s3 = MagicMock()

        with patch.object(svc.boto3, "client", return_value=mock_s3):
            svc.EoepcaCalrissianRunnerExecutionHandler.upload_logs_to_s3(
                handler,
                s3_bucket="test-bucket",
                process_id="proc-1",
                tool_logs=["./data_analysis_results_interceptor.log"],
                aws_access_key_id="fake-key",
                aws_secret_access_key="fake-secret",
            )

        mock_s3.upload_file.assert_not_called()
