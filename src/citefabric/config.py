from __future__ import annotations

import os
import tomllib
from pathlib import Path

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
    search_timeout: float = Field(default=12, gt=0, le=60)
    request_timeout: float = Field(default=8, gt=0, le=30)
    evidence_timeout: float = Field(default=45, gt=0, le=120)
    parse_timeout: float = Field(default=20, gt=0, le=60)
    max_download_bytes: int = Field(default=25 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)
    max_pages: int = Field(default=300, ge=1, le=1000)
    cache_bytes: int = Field(default=2 * 1024**3, ge=1024)
    offline: bool = False

    @model_validator(mode="after")
    def unique_sources(self):
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("sources must be unique")
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
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls.model_validate(values)
