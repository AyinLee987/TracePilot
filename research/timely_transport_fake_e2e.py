"""Offline, no-key E2E checks. Run directly; every transport uses MockTransport."""

from __future__ import annotations

import asyncio
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
from unittest.mock import patch
import uuid

import httpx

from timely_transport import BudgetedTimelyTransport, MAX_RESPONSE_BYTES, TransportBlocked, run_context


URL = "https://api.deepseek.com/chat/completions"
PAYLOAD = {"model": "deepseek-flash", "messages": [{"role": "user", "content": "hello 世界"}],
           "max_tokens": 32, "thinking": {"type": "disabled"}, "stream": False}


def completion(model: str = "deepseek-flash") -> dict:
    return {"id": "fake-completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "fake answer"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
                      "prompt_cache_hit_tokens": 60, "prompt_cache_miss_tokens": 40}}


async def blocked(coro) -> None:
    try:
        await coro
    except TransportBlocked:
        return
    raise AssertionError("request was not blocked")


class TrackedStream(httpx.AsyncByteStream):
    """A real async response stream, unlike Response(json=...)'s buffered body."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.chunks_read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


async def main() -> None:
    out = Path(__file__).resolve().parents[1] / ".local" / "timely-transport-checks" / uuid.uuid4().hex
    out.mkdir(parents=True)
    cases = 0

    def transport(name, handler, **kwargs):
        return BudgetedTimelyTransport(log_path=out / (name + ".jsonl"),
                                       batch_budget_cny=kwargs.pop("batch_budget_cny", "1"),
                                       max_calls=kwargs.pop("max_calls", 8),
                                       inner=httpx.MockTransport(handler), **kwargs)

    async def ok(request):
        return httpx.Response(200, json=completion(json.loads(request.content)["model"]),
                              headers={"X-Fake-Private-Header": "DO_NOT_LOG_HEADER"})

    t = transport("success", ok, max_calls=1)
    async with httpx.AsyncClient(transport=t) as client:
        with run_context(run_id="r-success", task_id="fake"):
            result = await client.post(URL, json=PAYLOAD, headers={"Authorization": "FAKE_HEADER_NOT_A_KEY"})
            assert result.json()["choices"][0]["message"]["content"] == "fake answer"
        assert Decimal(t.snapshot()["estimated_cny"]) == Decimal("0.00019488")
        assert Decimal(t.snapshot()["reserved_cny"]) == 0
        await blocked(client.post(URL, json=PAYLOAD))
        assert t.snapshot()["paid_call_count"] == 1
        assert t.snapshot()["stop_reason"] == "max_calls_reached"
    text = (out / "success.jsonl").read_text(encoding="utf-8")
    assert "FAKE_HEADER_NOT_A_KEY" not in text and "DO_NOT_LOG_HEADER" not in text
    events = [json.loads(line) for line in text.splitlines()]
    assert any(e.get("run_id") == "r-success" and e["event"] == "request_complete" for e in events)
    assert events[-1]["event"] == "batch_close"
    cases += 1

    # Valid reported usage above the bound must enlarge, never cap, the liability.
    for mode in ("input_above_bound", "output_above_bound", "model_mismatch"):
        data = completion()
        if mode == "input_above_bound":
            data["usage"] = {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 0,
                             "prompt_cache_miss_tokens": 1_000_000, "completion_tokens": 10,
                             "total_tokens": 1_000_010}
            expected_cost = Decimal("2.400096")
        elif mode == "output_above_bound":
            data["usage"]["completion_tokens"] = 1000
            data["usage"]["total_tokens"] = 1100
            expected_cost = Decimal("0.00969888")
        else:
            data["model"] = "unrecognized-version"
            expected_cost = None

        async def invalid_reply(request):
            return httpx.Response(200, json=data)

        t = transport(mode, invalid_reply)
        async with httpx.AsyncClient(transport=t) as client:
            await blocked(client.post(URL, json=PAYLOAD))
            snap = t.snapshot()
            assert snap["stop_reason"] == ("unexpected_response_model" if mode == "model_mismatch" else "usage_exceeds_bound")
            assert snap["unknown_calls"] == 1 and Decimal(snap["estimated_cny"]) == 0
            await blocked(client.post(URL, json=PAYLOAD))
            assert t.snapshot()["calls_dispatched"] == 1
        events = [json.loads(line) for line in (out / (mode + ".jsonl")).read_text(encoding="utf-8").splitlines()]
        dispatch = next(e for e in events if e["event"] == "request_dispatch")
        uncertain = next(e for e in events if e["event"] == "request_unknown")
        reserve = Decimal(dispatch["reservation_cny"])
        assert Decimal(uncertain["unknown_reserved_cny"]) == max(reserve, expected_cost or reserve)
        assert Decimal(uncertain["committed_cny"]) == max(reserve, expected_cost or reserve)
        assert uncertain["provider_usage_peak_estimate_cny"] == (str(expected_cost) if expected_cost else None)
        if expected_cost:
            assert expected_cost > reserve
        cases += 1

    # Endpoint/body gates reject before the inner transport sees anything.
    calls = 0

    async def counted(request):
        nonlocal calls
        calls += 1
        return await ok(request)

    t = transport("rejections", counted)
    async with httpx.AsyncClient(transport=t) as client:
        for url in ("http://api.deepseek.com/chat/completions", "https://example.com/chat/completions",
                    "https://api.deepseek.com/v1/chat/completions", URL + "?leak=no"):
            await blocked(client.post(url, json=PAYLOAD))
        await blocked(client.get(URL))
        for change in ({"stream": True}, {"thinking": {"type": "enabled"}},
                       {"model": "unapproved"}, {"max_tokens": 2049}, {"n": 2},
                       {"messages": [{"role": "user", "content": "x" * 48001}]}):
            await blocked(client.post(URL, json={**PAYLOAD, **change}))
        assert calls == 0 and t.snapshot()["paid_call_count"] == 0
    cases += 1

    t = transport("v1", ok, allow_v1_path=True)
    async with httpx.AsyncClient(transport=t) as client:
        assert (await client.post("https://api.deepseek.com/v1/chat/completions", json=PAYLOAD)).status_code == 200
    cases += 1

    t = transport("budget", counted, batch_budget_cny="0.000001")
    async with httpx.AsyncClient(transport=t) as client:
        await blocked(client.post(URL, json=PAYLOAD))
        assert t.snapshot()["paid_call_count"] == 0 and calls == 0
        assert t.snapshot()["stop_reason"] == "budget_exhausted"
    cases += 1

    # Success without complete usage, inconsistent usage and HTTP errors retain reservations.
    for mode in ("unknown", "inconsistent", "redirect", "server_error", "network_error"):
        seen = []

        async def bad(request):
            seen.append(request.url.host)
            if mode == "network_error":
                raise httpx.ReadError("DO_NOT_LOG_EXCEPTION", request=request)
            if mode in ("redirect", "server_error"):
                return httpx.Response(302 if mode == "redirect" else 500,
                                      headers={"Location": "https://example.com/leak"},
                                      text="DO_NOT_LOG_ERROR_BODY")
            data = completion()
            if mode == "unknown":
                del data["usage"]
            else:
                data["usage"]["total_tokens"] = 999
            return httpx.Response(200, json=data)

        t = transport(mode, bad)
        async with httpx.AsyncClient(transport=t, follow_redirects=True) as client:
            await blocked(client.post(URL, json=PAYLOAD))
            first = t.snapshot()
            assert first["unknown_calls"] == 1 and Decimal(first["unknown_reserved_cny"]) > 0
            assert Decimal(first["estimated_cny"]) == 0 and first["stop_reason"]
            await blocked(client.post(URL, json=PAYLOAD))
            assert seen == ["api.deepseek.com"]
            assert t.snapshot()["unknown_reserved_cny"] == first["unknown_reserved_cny"]
        text = (out / (mode + ".jsonl")).read_text(encoding="utf-8")
        assert "DO_NOT_LOG_EXCEPTION" not in text and "DO_NOT_LOG_ERROR_BODY" not in text
        cases += 1

    # Cancellation during the actual transport await is not converted to an ordinary error.
    started = asyncio.Event()

    async def hang(request):
        started.set()
        await asyncio.Future()

    t = transport("cancel", hang)
    async with httpx.AsyncClient(transport=t) as client:
        task = asyncio.create_task(client.post(URL, json=PAYLOAD))
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was lost")
        assert t.snapshot()["unknown_calls"] == 1 and t.snapshot()["stop_reason"] == "cancelled"
        await blocked(client.post(URL, json=PAYLOAD))
    cases += 1

    # Simultaneous calls share reservations and keep ContextVar labels separate.
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(request):
        started.set()
        await release.wait()
        return await ok(request)

    t = transport("concurrency", slow, batch_budget_cny="0.004")
    async with httpx.AsyncClient(transport=t) as client:
        with run_context(run_id="first"):
            first = asyncio.create_task(client.post(URL, json=PAYLOAD))
        await started.wait()
        with run_context(run_id="second"):
            await blocked(client.post(URL, json=PAYLOAD))
        assert t.snapshot()["paid_call_count"] == 1
        assert Decimal(t.snapshot()["committed_cny"]) <= Decimal("0.004")
        release.set()
        await first
    events = [json.loads(line) for line in (out / "concurrency.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {e["run_id"] for e in events if e["event"] == "request_complete"} == {"first"}
    assert {e["run_id"] for e in events if e["event"] == "request_rejected"} == {"second"}
    cases += 1

    # Closing the client owns cancellation/draining of an outstanding request.
    started = asyncio.Event()
    t = transport("shutdown", hang)
    client = httpx.AsyncClient(transport=t)
    task = asyncio.create_task(client.post(URL, json=PAYLOAD))
    await started.wait()
    await client.aclose()
    assert task.cancelled() and t.snapshot()["active_calls"] == 0
    assert t.snapshot()["unknown_calls"] == 1
    await t.aclose()  # Idempotent.
    cases += 1

    # Legal streamed bodies are decoded once, buffered, and still usable by clients.
    plain = json.dumps(completion()).encode("utf-8")
    for mode in ("plain", "gzip", "gzip_members", "exact_limit"):
        decoded = plain + b" " * (MAX_RESPONSE_BYTES - len(plain)) if mode == "exact_limit" else plain
        if mode == "gzip":
            wire = gzip.compress(decoded)
        elif mode == "gzip_members":
            split = len(decoded) // 2
            wire = gzip.compress(decoded[:split]) + gzip.compress(decoded[split:])
        else:
            wire = decoded
        chunk_size = 17 if mode.startswith("gzip") else 13_117
        stream = TrackedStream([wire[i:i + chunk_size] for i in range(0, len(wire), chunk_size)])

        async def streamed(request):
            assert request.headers["accept-encoding"] == "gzip"
            headers = {"Content-Type": "application/json", "Content-Length": str(len(wire)),
                       "X-Private-Test-Header": "DO_NOT_LOG_STREAM_HEADER"}
            if mode.startswith("gzip"):
                headers["Content-Encoding"] = "gzip"
            return httpx.Response(200, headers=headers, stream=stream)

        t = transport("stream_" + mode, streamed)
        async with httpx.AsyncClient(transport=t) as client:
            result = await client.post(URL, json=PAYLOAD)
            assert result.content == decoded and result.json() == completion()
            assert "content-encoding" not in result.headers
            assert int(result.headers["content-length"]) == len(decoded)
            assert stream.closed and stream.chunks_read == len(stream.chunks)
            assert Decimal(t.snapshot()["reserved_cny"]) == 0
        assert "DO_NOT_LOG_STREAM_HEADER" not in (out / ("stream_" + mode + ".jsonl")).read_text(encoding="utf-8")
        cases += 1

    # Reject on the first over-limit chunk, without draining the rest of the stream.
    for mode in ("plain_overflow", "gzip_expansion", "gzip_truncated", "unsupported_encoding"):
        encoding = None if mode == "plain_overflow" else "gzip"
        if mode == "plain_overflow":
            chunks, expected_read = [b" " * MAX_RESPONSE_BYTES, b"!", b"DO_NOT_LOG_TAIL"], 2
        elif mode == "gzip_expansion":
            chunks, expected_read = [gzip.compress(b" " * (MAX_RESPONSE_BYTES + 1)), b"DO_NOT_LOG_TAIL"], 1
        elif mode == "gzip_truncated":
            chunks, expected_read = [gzip.compress(plain)[:-1]], 1
        else:
            encoding = "br"
            chunks, expected_read = [b"DO_NOT_LOG_BODY"], 0
        stream = TrackedStream(chunks)

        async def oversized(request):
            return httpx.Response(200, headers={"Content-Encoding": encoding} if encoding else {},
                                  stream=stream)

        t = transport(mode, oversized)
        async with httpx.AsyncClient(transport=t) as client:
            await blocked(client.post(URL, json=PAYLOAD))
            snap = t.snapshot()
            assert stream.closed and stream.chunks_read == expected_read
            assert snap["unknown_calls"] == 1 and Decimal(snap["unknown_reserved_cny"]) > 0
            assert Decimal(snap["estimated_cny"]) == 0
            assert snap["stop_reason"] == ({"gzip_truncated": "invalid_response_compression",
                                             "unsupported_encoding": "unsupported_response_encoding"}.get(mode, "response_too_large"))
            await blocked(client.post(URL, json=PAYLOAD))
            assert t.snapshot()["paid_call_count"] == 1
        text = (out / (mode + ".jsonl")).read_text(encoding="utf-8")
        assert "DO_NOT_LOG" not in text
        assert all(e.get("response_body") is None for e in map(json.loads, text.splitlines())
                   if e["event"] == "request_unknown")
        cases += 1

    # Cancellation while reading the response also closes its stream and retains money.
    reading = asyncio.Event()

    class WaitingStream(TrackedStream):
        async def __aiter__(self):
            yield plain[:10]
            reading.set()
            await asyncio.Future()

    waiting = WaitingStream([])

    async def pending_response(request):
        return httpx.Response(200, stream=waiting)

    t = transport("cancel_response", pending_response)
    async with httpx.AsyncClient(transport=t) as client:
        task = asyncio.create_task(client.post(URL, json=PAYLOAD))
        await reading.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("response-read cancellation was lost")
        assert waiting.closed and t.snapshot()["unknown_calls"] == 1
        assert t.snapshot()["stop_reason"] == "cancelled"
    cases += 1

    # Exercise the real SDK boundary with gzip data and explicit dummy credentials.
    from openai import AsyncOpenAI

    sdk_stream = TrackedStream([gzip.compress(plain)])

    async def sdk_reply(request):
        assert json.loads(request.content)["thinking"] == {"type": "disabled"}
        return httpx.Response(200, headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
                              stream=sdk_stream)

    t = transport("sdk_roundtrip", sdk_reply)
    async with AsyncOpenAI(api_key="offline-no-credential", base_url="https://api.deepseek.com", max_retries=0,
                           http_client=httpx.AsyncClient(transport=t, follow_redirects=False)) as sdk:
        result = await sdk.chat.completions.create(
            model=PAYLOAD["model"], messages=PAYLOAD["messages"], max_tokens=32, stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        assert result.choices[0].message.content == "fake answer"
        assert result.model == PAYLOAD["model"] and result.usage.total_tokens == 110
    assert sdk_stream.closed and Decimal(t.snapshot()["reserved_cny"]) == 0
    cases += 1

    # Constructor failures close the journal; no pool is created after a failed write.
    class FailedJournal(io.StringIO):
        def write(self, value):
            raise OSError("simulated journal failure")

    journal = FailedJournal()
    with patch.object(Path, "open", return_value=journal), patch("timely_transport.httpx.AsyncHTTPTransport") as pool:
        try:
            BudgetedTimelyTransport(log_path=out / "init_write_failure.jsonl", batch_budget_cny="1", max_calls=1)
        except TransportBlocked:
            pass
        else:
            raise AssertionError("journal failure accepted")
        assert journal.closed
        pool.assert_not_called()
    cases += 1
    journal = io.StringIO()
    with patch.object(Path, "open", return_value=journal), patch("timely_transport.httpx.AsyncHTTPTransport", side_effect=RuntimeError("simulated init failure")):
        try:
            BudgetedTimelyTransport(log_path=out / "init_pool_failure.jsonl", batch_budget_cny="1", max_calls=1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("pool failure accepted")
        assert journal.closed
    cases += 1
    print(json.dumps({"mode": "offline_mock_only", "passed_cases": cases, "output_dir": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
