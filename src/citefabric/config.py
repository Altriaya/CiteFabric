from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from platformdirs import user_config_path, user_data_path
from pydantic import Field, SecretStr, model_validator

from .models import Model, Source


class Config(Model):
    data_dir: Path = Field(default_factory=lambda: user_data_path("citefabric"))
    sources: list[Source] = Field(
        default=["crossref", "arxiv", "openalex", "semantic_scholar"], min_length=1, max_length=4
    )
    contact_email: str | None = None
    openalex_api_key: SecretStr | None = None
    semantic_scholar_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    quickrouter_api_key: SecretStr | None = None
    compatible_api_key: SecretStr | None = None
    search_timeout: float = Field(default=12, gt=0, le=60)
    request_timeout: float = Field(default=8, gt=0, le=30)
    evidence_timeout: float = Field(default=45, gt=0, le=120)
    verifier_timeout: float = Field(default=30, gt=0, le=120)
    verifier_provider: Literal["none", "openai", "quickrouter", "openai_compatible"] = "none"
    verifier_base_url: str | None = Field(default=None, max_length=2048)
    verifier_model: str = Field(default="gpt-5.5-2026-04-23", min_length=1, max_length=200)
    verifier_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "medium"
    verifier_max_output_tokens: int = Field(default=4096, ge=512, le=16000)
    parse_timeout: float = Field(default=20, gt=0, le=60)
    max_download_bytes: int = Field(default=25 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)
    max_pages: int = Field(default=300, ge=1, le=1000)
    cache_bytes: int = Field(default=2 * 1024**3, ge=1024)
    offline: bool = False

    @model_validator(mode="after")
    def unique_sources(self):
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("sources must be unique")
        if self.verifier_provider == "openai_compatible" and not self.verifier_base_url:
            raise ValueError("openai_compatible verifier requires verifier_base_url")
        return self

    @classmethod
    def load(cls, **overrides) -> Config:
        path = Path(os.getenv("CITEFABRIC_CONFIG", user_config_path("citefabric") / "config.toml"))
        values = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        for name in cls.model_fields:
            key = "CITEFABRIC_" + name.upper()
            if key in os.environ:
                raw = os.environ[key]
                values[name] = raw.split(",") if name == "sources" else raw
        if "openai_api_key" not in values and os.getenv("OPENAI_API_KEY"):
            values["openai_api_key"] = os.environ["OPENAI_API_KEY"]
        if "quickrouter_api_key" not in values and os.getenv("QUICKROUTER_API_KEY"):
            values["quickrouter_api_key"] = os.environ["QUICKROUTER_API_KEY"]
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls.model_validate(values)
