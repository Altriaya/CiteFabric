"""Bounded provider requests with shared leases, cache, retries and coalescing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from .config import Config
from .models import CacheStatus, FabricError, OutcomeStatus, now, sha
from .storage import Store, dump


@dataclass
class FetchResult:
    text: str
    cache_status: CacheStatus
    attempts: int
    degraded_code: str | None = None
    retrieved_at: str = field(default_factory=now)


class ProviderFailure(FabricError):
    def __init__(
        self,
        code: str,
        status: OutcomeStatus,
        retryable: bool = False,
        retry_after: float | None = None,
        attempts: int = 0,
    ):
        super().__init__(code, code.replace("_", " ") + ".", retryable=retryable)
        self.status = status
        self.retry_after = retry_after
        self.attempts = attempts


def retry_after(value: str | None) -> float:
    if value is None:
        return 1.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            return max(0.0, (date - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 1.0


class ProviderRuntime:
    def __init__(self, config: Config, store: Store, http: httpx.AsyncClient | None = None):
        self.config, self.store = config, store
        self.http = http or httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "CiteFabric/0.1 (+local research client)"},
        )
        self._owns_http = http is None
        self._pending: dict[str, list] = {}

    async def close(self):
        tasks = [entry[0] for entry in self._pending.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._owns_http:
            await self.http.aclose()

    async def fetch(
        self,
        source: str,
        url: str,
        params: dict,
        *,
        headers: dict | None = None,
        ttl: float = 86400,
        refresh: bool = False,
    ) -> FetchResult:
        headers = headers or {}
        scope = sha(dump(headers).encode())
        key = "http:" + sha(dump([source, url, params, scope]).encode())
        if not refresh:
            cached = self.store.cache_get(key)
            if cached:
                return FetchResult(
                    cached[0]["text"], "fresh", 0, retrieved_at=cached[0]["retrieved_at"]
                )
        if self.config.offline:
            cached = self.store.cache_get(key, stale=True)
            if cached:
                return FetchResult(
                    cached[0]["text"],
                    "stale" if cached[1] else "fresh",
                    0,
                    "offline" if cached[1] else None,
                    retrieved_at=cached[0]["retrieved_at"],
                )
            raise ProviderFailure("offline", "unavailable")
        if key not in self._pending:
            task = asyncio.create_task(self._fetch(source, url, params, headers, key, scope, ttl))
            self._pending[key] = [task, 0]
        entry = self._pending[key]
        entry[1] += 1
        try:
            return await asyncio.shield(entry[0])
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                if not entry[0].done():
                    entry[0].cancel()
                self._pending.pop(key, None)
                # Do not let close() race a detached request's lease cleanup.
                await asyncio.gather(entry[0], return_exceptions=True)

    async def _fetch(self, source, url, params, headers, key, scope, ttl):
        interval = {"arxiv": 3.0, "crossref": 1.0, "semantic_scholar": 1.0, "openalex": 0.25}[
            source
        ]
        # arXiv has one cross-process budget regardless of query/credential details.
        budget_key = source + ("" if source == "arxiv" else ":" + scope)
        last_error = ProviderFailure("provider_unavailable", "unavailable", True)
        deadline = time.monotonic() + self.config.request_timeout
        attempts = 0
        try:
            async with asyncio.timeout(self.config.request_timeout):
                for attempt in range(2):
                    token = None
                    while token is None:
                        token, delay = self.store.acquire(
                            budget_key, interval, self.config.request_timeout + 1
                        )
                        if token is None:
                            if delay >= deadline - time.monotonic():
                                raise ProviderFailure(
                                    "provider_rate_limited", "rate_limited", True, delay, attempts
                                )
                            await asyncio.sleep(min(delay, 0.2))
                    cooldown, transient = 0.0, False
                    try:
                        attempts += 1
                        async with self.http.stream(
                            "GET",
                            url,
                            params=params,
                            headers=headers,
                            timeout=max(0.01, deadline - time.monotonic()),
                        ) as response:
                            if response.status_code == 429:
                                cooldown = retry_after(response.headers.get("Retry-After"))
                                last_error = ProviderFailure(
                                    "provider_rate_limited",
                                    "rate_limited",
                                    True,
                                    cooldown,
                                    attempts,
                                )
                            elif response.status_code in {401, 403}:
                                cooldown = 60
                                raise ProviderFailure(
                                    "authentication_required",
                                    "permission_denied",
                                    False,
                                    attempts=attempts,
                                )
                            elif response.status_code == 404:
                                raise ProviderFailure(
                                    "provider_not_found", "no_results", attempts=attempts
                                )
                            elif response.status_code >= 500:
                                transient = True
                                cooldown = retry_after(response.headers.get("Retry-After"))
                                last_error = ProviderFailure(
                                    "provider_unavailable", "unavailable", True, cooldown, attempts
                                )
                            elif response.status_code != 200:
                                raise ProviderFailure(
                                    "provider_rejected_request", "unavailable", attempts=attempts
                                )
                            else:
                                chunks, size = [], 0
                                async for chunk in response.aiter_bytes():
                                    size += len(chunk)
                                    if size > 4 * 1024 * 1024:
                                        raise ProviderFailure(
                                            "resource_limit", "unavailable", attempts=attempts
                                        )
                                    chunks.append(chunk)
                                text = b"".join(chunks).decode("utf-8")
                                # Syntax/semantic validation belongs to the provider. Only
                                # syntactically valid payloads get cached by acknowledge().
                                return FetchResult(text, "miss", attempts)
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        transient = True
                        last_error = ProviderFailure(
                            "provider_timeout"
                            if isinstance(exc, httpx.TimeoutException)
                            else "provider_unavailable",
                            "unavailable",
                            True,
                            attempts=attempts,
                        )
                    finally:
                        self.store.release(budget_key, token, transient, cooldown)
                    if attempt == 0 and last_error.retryable:
                        continue
                    raise last_error
        except TimeoutError:
            last_error = ProviderFailure("provider_timeout", "unavailable", True, attempts=attempts)
        except ProviderFailure as exc:
            last_error = exc
        cached = self.store.cache_get(key, stale=True)
        if cached and last_error.status != "no_results":
            return FetchResult(
                cached[0]["text"],
                "stale",
                attempts,
                last_error.code,
                retrieved_at=cached[0]["retrieved_at"],
            )
        raise last_error

    def acknowledge(
        self,
        source: str,
        url: str,
        params: dict,
        headers: dict,
        text: str,
        ttl: float,
        retrieved_at: str | None = None,
    ):
        scope = sha(dump(headers).encode())
        key = "http:" + sha(dump([source, url, params, scope]).encode())
        self.store.cache_put(key, {"text": text, "retrieved_at": retrieved_at or now()}, ttl)
