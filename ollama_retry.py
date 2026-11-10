"""Retry transient failures of synchronous Ollama chat requests."""

import shlex
import sys
# from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import sleep
# from time import perf_counter

from ollama import Client, ResponseError
# from ollama import ChatResponse


class RetryingOllamaClient(Client):
    """Keep retrying a chat request in place when the server reports a transient error."""

    def __init__(self, *args, capture_dir=None, **kwargs):
        if capture_dir:
            hooks = dict(kwargs.get("event_hooks") or {})
            hooks["request"] = [
                *hooks.get("request", []),
                lambda request: capture_chat_request(request, Path(capture_dir)),
            ]
            kwargs["event_hooks"] = hooks
        super().__init__(*args, **kwargs)

    def chat(self, *args, **kwargs):
        # The fourth attempt is final, so its original error propagates to the caller.
        for delay in (2, 4, 8):
            try:
                return super().chat(*args, **kwargs)
            except ResponseError as error:
                if error.status_code not in {500, 502, 503, 504}:
                    raise
                # print(f"Ollama returned HTTP {error.status_code}. Retrying chat in {delay}s.",
                #       file=sys.stderr, flush=True)
                sleep(delay)
        return super().chat(*args, **kwargs)

    # Optional request timing diagnostics.
    # def _chat_attempt(self, *args, **kwargs):
    #     model = kwargs.get("model", args[0] if args else "<default>")
    #     print(f"{datetime.now().isoformat(timespec='milliseconds')} Ollama chat started ({model})",
    #           file=sys.stderr, flush=True)
    #     started = perf_counter()
    #     details = []
    #     try:
    #         response = super().chat(*args, **kwargs)
    #         if isinstance(response, ChatResponse):
    #             content = "nonempty" if (response.message.content or "").strip() else "empty"
    #             details.append(f"content={content}")
    #             for field in ("done_reason", "prompt_eval_count", "eval_count"):
    #                 value = getattr(response, field)
    #                 if value is not None:
    #                     details.append(f"{field}={value}")
    #             for field in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
    #                 value = getattr(response, field)
    #                 if value is not None:
    #                     details.append(f"{field}={value / 1_000_000_000:.3f}s")
    #         return response
    #     except ResponseError as error:
    #         details.append(f"HTTP {error.status_code}")
    #         raise
    #     except Exception as error:
    #         details.append(type(error).__name__)
    #         raise
    #     finally:
    #         elapsed = perf_counter() - started
    #         suffix = f" [{', '.join(details)}]" if details else ""
    #         print(f"{datetime.now().isoformat(timespec='milliseconds')} Ollama chat ended ({model}) after {elapsed:.2f}s{suffix}",
    #               file=sys.stderr, flush=True)


def capture_chat_request(request, directory):
    """Save the serialized chat body and print a replay command without credentials."""
    if request.method != "POST" or not request.url.path.rstrip("/").endswith("/api/chat"):
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=directory, prefix="ollama-chat-", suffix=".json", delete=False) as body:
            body.write(request.content)
            path = Path(body.name).resolve()
    except OSError as error:
        print(f"Could not capture Ollama request: {error}", file=sys.stderr, flush=True)
        return

    command = ["curl", "--location", "--include", "--data-binary", f"@{path}",
               "--write-out", "\\nHTTP %{http_code} in %{time_total}s\\n"]
    for header in ("Content-Type", "Accept", "User-Agent"):
        if header in request.headers:
            command.extend(("--header", f"{header}: {request.headers[header]}"))
    command.append(str(request.url.copy_with(username="", password="")))
    replay = shlex.join(command)
    if request.headers.get("Authorization"):
        replay += ' --header "Authorization: Bearer ${OLLAMA_API_KEY:?Set OLLAMA_API_KEY}"'
    print(f"Ollama replay command (body saved locally):\n{replay}", file=sys.stderr, flush=True)
