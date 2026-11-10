import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

import httpx
from ollama import Client, ResponseError

from ollama_retry import RetryingOllamaClient


class OllamaRetryTest(unittest.TestCase):
    def setUp(self):
        self.client = RetryingOllamaClient()
        self.request = {"model": "fixture", "messages": [{"role": "user", "content": "Question"}]}

    def test_captures_exact_http_body_without_authorization_value(self):
        sent = []

        def respond(request):
            sent.append(request)
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "Answer"}})

        with TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as output:
            with RetryingOllamaClient(
                "https://example.test/ollama", headers={"Authorization": "Bearer test-secret"},
                capture_dir=directory, transport=httpx.MockTransport(respond),
            ) as client:
                client.chat(**self.request)
            capture, = Path(directory).glob("*.json")
            self.assertEqual(capture.read_bytes(), sent[0].content)
            self.assertIn(str(sent[0].url), output.getvalue())
            self.assertIn("${OLLAMA_API_KEY:", output.getvalue())
            self.assertNotIn("test-secret", output.getvalue())
            self.assertNotIn(b"test-secret", capture.read_bytes())

    def test_retries_same_request_after_cuda_failure(self):
        error = ResponseError("CUDA error", 500)
        output = io.StringIO()
        with patch.object(Client, "chat", side_effect=[error, "answer"]) as chat:
            with patch("ollama_retry.sleep") as sleep, redirect_stderr(output):
                self.assertEqual(self.client.chat(**self.request), "answer")
        self.assertEqual(chat.call_args_list, [call(**self.request), call(**self.request)])
        sleep.assert_called_once_with(2)
        self.assertEqual(output.getvalue(), "")

    def test_client_error_is_not_retried(self):
        error = ResponseError("unauthorized", 401)
        with patch.object(Client, "chat", side_effect=error) as chat:
            with patch("ollama_retry.sleep") as sleep, self.assertRaises(ResponseError) as raised:
                self.client.chat(**self.request)
        self.assertIs(raised.exception, error)
        chat.assert_called_once_with(**self.request)
        sleep.assert_not_called()

    def test_exhausted_retries_raise_the_final_error(self):
        errors = [ResponseError(f"server failure {attempt}", 503) for attempt in range(4)]
        with patch.object(Client, "chat", side_effect=errors) as chat:
            with patch("ollama_retry.sleep") as sleep, redirect_stderr(io.StringIO()):
                with self.assertRaises(ResponseError) as raised:
                    self.client.chat(**self.request)
        self.assertIs(raised.exception, errors[-1])
        self.assertEqual(chat.call_args_list, [call(**self.request)] * 4)
        self.assertEqual(sleep.call_args_list, [call(2), call(4), call(8)])
