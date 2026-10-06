"""Fail-closed HTTP budget boundary for the fixed official Timely pilot.

Use one transport per batch and one event loop. The caller owns SDK retries
(OpenAI max_retries=0, official agent retries=1), timeout, and client lifetime.
Only text chat is supported. /v1/chat/completions requires allow_v1_path=True.
The peak price card is the experiment's 2026-10-06 USD/M-token assumption;
8 CNY/USD is a conservative planning conversion, not a live exchange rate.

Example::

    transport = BudgetedTimelyTransport(
        log_path=Path('.local/my-batch/http.jsonl'),
        batch_budget_cny='1.00', max_calls=10,
    )
    client = httpx.AsyncClient(transport=transport, follow_redirects=False)
    # Inject client into AsyncOpenAI(http_client=client, max_retries=0, ...).
    with run_context(run_id='r1', task_id='official-task-id', phase='main'):
        ...
    await client.aclose()

The ledger reports provider-usage-based peak-price estimates separately from
unresolved reservations. It is not a provider invoice. Reopening an existing
log is deliberately refused: starting a new transport starts a new budget.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import time
from typing import Any, Iterator, Mapping
import uuid
import zlib

import httpx


PRICE_CARD_DATE = "2026-10-06"
PLANNING_CNY_PER_USD = Decimal("8")
MAX_MESSAGE_BYTES = 48_000
MAX_OUTPUT_TOKENS = 2_048
MESSAGE_OVERHEAD_TOKENS = 1_024  # Per message, deliberately conservative.
MAX_REQUEST_BYTES = 128_000
# Applied separately to encoded wire bytes and decoded response bytes.
MAX_RESPONSE_BYTES = 1_048_576
_MILLION = Decimal(1_000_000)
_PRICES = {
    "deepseek-flash": (Decimal("0.30"), Decimal("0.006"), Decimal("1.20")),
    "deepseek-v4-pro": (Decimal("1.32"), Decimal("0.044"), Decimal("3.96")),
}
_LABEL_KEYS = frozenset({
    "run_id", "task_id", "case_id", "phase", "model", "agent_role", "repeat",
    "deadline_s", "condition", "seed", "budget_s",
})
_RUN_LABELS: ContextVar[dict[str, Any] | None] = ContextVar("timely_run_labels", default=None)


class TransportBlocked(RuntimeError):
    """A safe, body-free failure which must not trigger a paid retry."""


@contextmanager
def run_context(**labels: Any) -> Iterator[None]:
    """Attach scalar run labels, isolated across asyncio tasks and nested runs."""
    if set(labels) - _LABEL_KEYS:
        raise ValueError("unsupported run label")
    for value in labels.values():
        if type(value) not in (str, int, float, bool, type(None)):
            raise ValueError("run labels must be scalar")
        if isinstance(value, str) and len(value) > 256:
            raise ValueError("run label too long")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("run label must be finite")
    token = _RUN_LABELS.set({**(_RUN_LABELS.get() or {}), **labels})
    try:
        yield
    finally:
        _RUN_LABELS.reset(token)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _decode(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                       parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("JSON body is not an object")
    return value


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _cost(model: str, miss: int, hit: int, output: int) -> Decimal:
    miss_price, hit_price, output_price = _PRICES[model]
    return (miss * miss_price + hit * hit_price + output * output_price) / _MILLION * PLANNING_CNY_PER_USD


def _usage_amount(body: dict[str, Any], model: str) -> tuple[dict[str, int], Decimal]:
    """Validate reported token counts independently of request/response limits."""
    usage = body.get("usage")
    if not isinstance(usage, dict):
        raise TransportBlocked("unknown_usage")
    fields = ("prompt_tokens", "completion_tokens", "total_tokens",
              "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
    if any(not _integer(usage.get(k)) for k in fields):
        raise TransportBlocked("unknown_usage")
    values = {k: usage[k] for k in fields}
    if (values["prompt_tokens"] != values["prompt_cache_hit_tokens"] + values["prompt_cache_miss_tokens"]
            or values["total_tokens"] != values["prompt_tokens"] + values["completion_tokens"]):
        raise TransportBlocked("inconsistent_usage")
    return values, _cost(model, values["prompt_cache_miss_tokens"],
                         values["prompt_cache_hit_tokens"], values["completion_tokens"])


@dataclass(frozen=True)
class _Call:
    request_id: str
    labels: dict[str, Any]
    body: dict[str, Any]
    message_bytes: int
    input_upper: int
    reservation: Decimal
    dispatch_time: float
    start_time: float


class BudgetedTimelyTransport(httpx.AsyncBaseTransport):
    """A batch-wide budget gate, private JSONL journal, and no-retry transport.

    Network transport is always constructed here with retries=0/trust_env=False.
    The optional inner argument accepts only MockTransport for offline E2E.
    Caller must use a fresh .local JSONL path. No credentials are accepted here.
    """

    def __init__(
        self, *, log_path: Path, batch_budget_cny: str | Decimal,
        max_calls: int, inner: httpx.MockTransport | None = None,
        allow_v1_path: bool = False,
    ) -> None:
        try:
            budget = Decimal(str(batch_budget_cny))
        except (InvalidOperation, ValueError):
            raise ValueError("invalid batch budget") from None
        if not budget.is_finite() or budget <= 0:
            raise ValueError("batch budget must be finite and positive")
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be a positive integer")
        if type(allow_v1_path) is not bool:
            raise ValueError("allow_v1_path must be boolean")
        if inner is not None and type(inner) is not httpx.MockTransport:
            raise ValueError("only MockTransport may be injected; network retries are managed here")
        path = Path(log_path).resolve()
        if ".local" not in {part.casefold() for part in path.parts} or path.suffix != ".jsonl":
            raise ValueError("log_path must be a .jsonl file inside a .local directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._log = path.open("x", encoding="utf-8", newline="\n")
        self._budget = budget
        self._max_calls = max_calls
        self._paths = {"/chat/completions"}
        if allow_v1_path:
            self._paths.add("/v1/chat/completions")
        self._spent = Decimal(0)
        self._reservations: dict[str, Decimal] = {}
        self._unknown: set[str] = set()
        self._active: dict[str, asyncio.Task[Any]] = {}
        self._calls = 0
        self._stop_reason: str | None = None
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        try:
            # Journal first: no inner pool exists if the initial write fails.
            self._emit({"event": "batch_open", "schema": "timely-transport-v1",
                        "price_card_date": PRICE_CARD_DATE,
                        "planning_cny_per_usd": str(PLANNING_CNY_PER_USD),
                        "prices_usd_per_million": {m: {"miss": str(p[0]), "hit": str(p[1]), "output": str(p[2])}
                                                   for m, p in _PRICES.items()},
                        "message_overhead_tokens_each": MESSAGE_OVERHEAD_TOKENS,
                        "max_message_bytes": MAX_MESSAGE_BYTES, "max_request_bytes": MAX_REQUEST_BYTES,
                        "max_response_bytes_each_wire_decoded": MAX_RESPONSE_BYTES,
                        "max_output_tokens": MAX_OUTPUT_TOKENS,
                        "allowed_paths": sorted(self._paths), **self.snapshot()})
            self._inner = inner if inner is not None else httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        except BaseException:
            try:
                self._log.close()
            except Exception:
                pass
            raise

    def snapshot(self) -> dict[str, Any]:
        """Return accounting; CNY amounts are decimal strings.

        paid_call_count is a legacy alias of calls_dispatched, including fake
        and unresolved calls. Only the runner's paid flag indicates live use.
        """
        reserved = sum(self._reservations.values(), Decimal(0))
        unknown = sum((self._reservations[k] for k in self._unknown), Decimal(0))
        return {"batch_budget_cny": str(self._budget), "max_calls": self._max_calls,
                "calls_dispatched": self._calls, "spent_estimate_cny": str(self._spent),
                "paid_call_count": self._calls, "estimated_cny": str(self._spent),
                "unknown_reserved_cny": str(unknown),
                "in_flight_reserved_cny": str(reserved - unknown),
                "reserved_cny": str(reserved), "committed_cny": str(self._spent + reserved),
                "active_calls": len(self._active), "unknown_calls": len(self._unknown),
                "stop_reason": self._stop_reason, "closing": self._closing}

    def _emit(self, event: Mapping[str, Any]) -> None:
        # Explicit event fields only: no Request/Response repr, headers, or exception text.
        try:
            self._log.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            self._log.flush()
        except Exception:
            self._stop_reason = "journal_failure"
            raise TransportBlocked("journal_failure; batch stopped") from None

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise TransportBlocked("transport must stay on one event loop")

    async def _validate(self, request: httpx.Request) -> tuple[dict[str, Any], int, int]:
        url = request.url
        if (request.method != "POST" or url.scheme != "https" or url.host != "api.deepseek.com"
                or url.port not in (None, 443) or url.path not in self._paths
                or url.query or url.fragment or url.userinfo):
            raise TransportBlocked("request_target_not_allowed")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream:
            size += len(chunk)
            if size > MAX_REQUEST_BYTES:
                raise TransportBlocked("request_body_too_large")
            chunks.append(chunk)
        raw = b"".join(chunks)
        try:
            body = _decode(raw)
            allowed = {"model", "messages", "stream", "max_tokens", "thinking", "temperature",
                       "top_p", "frequency_penalty", "presence_penalty", "stop", "seed", "n"}
            if set(body) - allowed:
                raise ValueError("unsupported request option")
            if body.get("model") not in _PRICES or body.get("stream", False) is not False:
                raise ValueError("unsupported model or stream")
            if body.get("thinking") != {"type": "disabled"}:
                raise ValueError("thinking must be disabled")
            output = body.get("max_tokens")
            if not _integer(output) or not 1 <= output <= MAX_OUTPUT_TOKENS:
                raise ValueError("invalid max_tokens")
            if "n" in body and (type(body["n"]) is not int or body["n"] != 1):
                raise ValueError("only one completion is allowed")
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError("messages required")
            for message in messages:
                if not isinstance(message, dict) or set(message) - {"role", "content", "name", "tool_call_id"}:
                    raise ValueError("only text messages are supported")
                if message.get("role") not in {"system", "user", "assistant", "tool"}:
                    raise ValueError("unsupported message role")
                if not isinstance(message.get("content"), str):
                    raise ValueError("only text message content is supported")
                if any(not isinstance(v, str) for v in message.values()):
                    raise ValueError("message fields must be strings")
            message_bytes = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if message_bytes > MAX_MESSAGE_BYTES:
                raise ValueError("messages exceed UTF8 limit")
            input_upper = len(raw) + len(messages) * MESSAGE_OVERHEAD_TOKENS
        except (ValueError, TypeError, UnicodeError):
            raise TransportBlocked("request_body_not_allowed") from None
        # Restore even a one-shot async request body for the inner transport.
        request.stream = httpx.ByteStream(raw)
        return body, message_bytes, input_upper

    def _begin(self, body: dict[str, Any], message_bytes: int, input_upper: int,
               request_id: str, labels: dict[str, Any], dispatched: float) -> _Call:
        if self._closing or self._stop_reason:
            raise TransportBlocked("batch_stopped")
        if self._calls >= self._max_calls:
            self._stop_reason = "max_calls_reached"
            raise TransportBlocked("max_calls_reached")
        reservation = _cost(body["model"], input_upper, 0, body["max_tokens"])
        if self._spent + sum(self._reservations.values(), Decimal(0)) + reservation > self._budget:
            self._stop_reason = "budget_exhausted"
            raise TransportBlocked("budget_exhausted")
        # No await between gate, reservation, and dispatch; atomic on the bound loop.
        self._calls += 1
        self._reservations[request_id] = reservation
        task = asyncio.current_task()
        assert task is not None
        self._active[request_id] = task
        return _Call(request_id, labels, body, message_bytes, input_upper, reservation,
                     dispatched, time.monotonic())

    def _usage(self, body: dict[str, Any], call: _Call) -> tuple[dict[str, int], Decimal]:
        values, cost = _usage_amount(body, call.body["model"])
        if (values["prompt_tokens"] > call.input_upper
                or values["completion_tokens"] > call.body["max_tokens"]):
            raise TransportBlocked("usage_exceeds_bound")
        if body.get("model") != call.body["model"]:
            raise TransportBlocked("unexpected_response_model")
        if not isinstance(body.get("id"), str) or not body["id"]:
            raise TransportBlocked("missing_response_id")
        choices = body.get("choices")
        if (not isinstance(choices, list) or len(choices) != 1
                or not isinstance(choices[0], dict)
                or not isinstance(choices[0].get("message"), dict)
                or not isinstance(choices[0]["message"].get("content"), str)):
            raise TransportBlocked("invalid_completion_body")
        if cost > call.reservation:
            raise TransportBlocked("cost_exceeds_reservation")
        return values, cost

    async def _read_response(self, response: httpx.Response) -> bytes:
        """Bound both wire and decoded bytes without an unbounded gzip expansion.

        Only gzip is negotiated; identity and concatenated gzip members are
        supported. Other/stacked encodings fail closed. Pre-buffered responses
        occur in MockTransport: HTTPX has already decoded their content.
        """
        if response.is_stream_consumed:
            content = response.content
            if len(content) > MAX_RESPONSE_BYTES:
                raise TransportBlocked("response_too_large")
            return content
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in ("", "identity", "gzip"):
            raise TransportBlocked("unsupported_response_encoding")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
        content = bytearray()
        wire_bytes = 0
        async for chunk in response.aiter_raw():
            wire_bytes += len(chunk)
            if wire_bytes > MAX_RESPONSE_BYTES:
                raise TransportBlocked("response_too_large")
            if decoder is None:
                content.extend(chunk)  # Identity decoded size equals bounded wire size.
                continue
            try:
                while chunk:
                    if decoder.eof:
                        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    decoded = decoder.decompress(chunk, MAX_RESPONSE_BYTES - len(content) + 1)
                    if len(content) + len(decoded) > MAX_RESPONSE_BYTES:
                        raise TransportBlocked("response_too_large")
                    content.extend(decoded)
                    chunk = decoder.unused_data
            except zlib.error:
                raise TransportBlocked("invalid_response_compression") from None
        if decoder is not None and not decoder.eof:
            raise TransportBlocked("invalid_response_compression")
        return bytes(content)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._bind_loop()
        request_id, labels = uuid.uuid4().hex, dict(_RUN_LABELS.get() or {})
        dispatched = time.monotonic()
        if self._closing:
            raise TransportBlocked("batch_closed")
        try:
            body, message_bytes, input_upper = await self._validate(request)
            call = self._begin(body, message_bytes, input_upper, request_id, labels, dispatched)
        except TransportBlocked as exc:
            self._emit({"event": "request_rejected", "request_id": request_id, "labels": labels,
                        "run_id": labels.get("run_id"),
                        "dispatch_monotonic_s": dispatched, "end_monotonic_s": time.monotonic(),
                        "reason": str(exc), **self.snapshot()})
            raise
        except Exception:
            self._emit({"event": "request_rejected", "request_id": request_id, "labels": labels,
                        "run_id": labels.get("run_id"),
                        "dispatch_monotonic_s": dispatched, "end_monotonic_s": time.monotonic(),
                        "reason": "invalid_request_stream", **self.snapshot()})
            raise TransportBlocked("invalid_request_stream") from None
        response: httpx.Response | None = None
        response_body: dict[str, Any] | None = None
        event = {"request_id": request_id, "labels": labels, "run_id": labels.get("run_id"),
                 "dispatch_monotonic_s": call.dispatch_time, "start_monotonic_s": call.start_time,
                 "requested_model": call.body["model"], "reservation_cny": str(call.reservation)}
        try:
            self._emit({"event": "request_dispatch", **event, "request_body": call.body,
                        "message_utf8_bytes": call.message_bytes, "input_tokens_upper": call.input_upper,
                        **self.snapshot()})
            # Limit decoding to an encoding with an explicitly bounded decoder.
            request.headers["accept-encoding"] = "gzip"
            response = await self._inner.handle_async_request(request)
            # A redirect is an uncertain paid attempt and never reaches HTTPX's redirect handler.
            if not 200 <= response.status_code < 300:
                raise TransportBlocked("http_status_error")
            raw = await self._read_response(response)
            try:
                response_body = _decode(raw)
            except (ValueError, TypeError, UnicodeError):
                raise TransportBlocked("invalid_response_json") from None
            usage, estimate = self._usage(response_body, call)
            # The SDK receives decoded, buffered content. Retaining the original
            # encoding/length headers would decode it again or advertise stale sizes.
            headers = response.headers.copy()
            for name in ("content-encoding", "content-length", "transfer-encoding"):
                headers.pop(name, None)
            buffered = httpx.Response(response.status_code, headers=headers, content=raw,
                                      request=request, extensions=response.extensions)
            # Commit the evidence before releasing any reservation for subsequent calls.
            self._emit({"event": "request_complete", **event,
                        "end_monotonic_s": time.monotonic(), "status_code": response.status_code,
                        "response_id": response_body["id"], "response_model": response_body["model"],
                        "response_body": response_body, "usage": usage,
                        "provider_usage_peak_estimate_cny": str(estimate),
                        "reservation_released_cny": str(call.reservation)})
            self._spent += estimate
            del self._reservations[request_id]
            return buffered
        except asyncio.CancelledError:
            self._uncertain(call, event, "cancelled", response, response_body)
            raise
        except Exception as exc:
            reason = str(exc) if isinstance(exc, TransportBlocked) else "network_or_transport_error"
            self._uncertain(call, event, reason, response, response_body)
            raise TransportBlocked(reason + "; reservation retained; batch stopped") from None
        finally:
            self._active.pop(request_id, None)
            if response is not None:
                try:
                    await response.aclose()
                except Exception:
                    # Accounting was already finalized; shutdown also closes the inner pool.
                    pass

    def _uncertain(self, call: _Call, event: dict[str, Any], reason: str,
                   response: httpx.Response | None, response_body: dict[str, Any] | None) -> None:
        self._stop_reason = reason
        self._unknown.add(call.request_id)
        # Even an invalid completion can report valid usage. Never discard a
        # known amount above our estimated bound. A model mismatch stays unknown.
        usage = estimate = None
        if response_body is not None and response_body.get("model") == call.body["model"]:
            try:
                usage, estimate = _usage_amount(response_body, call.body["model"])
            except TransportBlocked:
                pass
        if estimate is not None:
            self._reservations[call.request_id] = max(self._reservations[call.request_id], estimate)
        # Unknown and spent remain disjoint: this amount stays reserved until reconciled.
        try:
            self._emit({"event": "request_unknown", **event, "reason": reason,
                        "end_monotonic_s": time.monotonic(),
                        "status_code": response.status_code if response is not None else None,
                        "response_body": response_body,
                        "usage": usage,
                        "provider_usage_peak_estimate_cny": str(estimate) if estimate is not None else None,
                        **self.snapshot()})
        except TransportBlocked:
            # A broken journal must not release money or replace CancelledError.
            pass

    async def aclose(self) -> None:
        """Stop dispatch, cancel/drain active calls, close the pool, and flush the journal.

        Shield cleanup from caller cancellation. The close task remains owned here;
        call aclose again to wait for it if the first caller was cancelled.
        Closing during a request cancels its entire owning caller task.
        """
        self._bind_loop()
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._finish_close())
        await asyncio.shield(self._close_task)

    async def _finish_close(self) -> None:
        tasks = set(self._active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self._inner.aclose()
        finally:
            try:
                self._emit({"event": "batch_close", "end_monotonic_s": time.monotonic(), **self.snapshot()})
            finally:
                self._log.close()
