"""Pluggable semantic-verifier backend boundary.

Backends only transform a frozen :class:`VerifierRequest` into structured
observations.  The application validates those observations and derives the
public verdict; a backend never writes receipts or retrieves more evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pydantic import Field

from .models import Model, sha
from .verifier_contract import VerifierRequest, VerifierResponse, VerifierUsage


class VerifierBackendResult(Model):
    response: VerifierResponse
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    model_revision: str | None = Field(default=None, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)
    prompt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attempts: int = Field(default=1, ge=1, le=3)
    fallback_used: bool = False
    usage: VerifierUsage = Field(
        default_factory=lambda: VerifierUsage(input_tokens=0, output_tokens=0)
    )


class VerifierBackend(Protocol):
    """Minimal async interface implemented by fake, hosted and local models."""

    @property
    def backend_id(self) -> str: ...

    async def verify(self, request: VerifierRequest) -> VerifierBackendResult: ...


class FakeVerifierBackend:
    """Deterministic dependency-injected backend for tests and local integration.

    It is intentionally unavailable through normal CLI configuration so a fake
    verdict cannot be enabled accidentally in a user workspace.
    """

    backend_id = "fake"

    def __init__(
        self,
        response: VerifierResponse
        | Callable[[VerifierRequest], VerifierResponse | VerifierBackendResult],
    ):
        self._response = response

    async def verify(self, request: VerifierRequest) -> VerifierBackendResult:
        value = self._response(request) if callable(self._response) else self._response
        if isinstance(value, VerifierBackendResult):
            return value
        return VerifierBackendResult(
            response=value,
            provider="fake",
            model="deterministic-fixture",
            model_revision="1",
            prompt_version="fake-verifier-v1",
            prompt_hash=sha(b"fake-verifier-v1"),
        )
