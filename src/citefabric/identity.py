"""Conservative identifiers: version relations are not edition equality."""

import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import unquote, urlsplit
from uuid import UUID

from .models import ExternalID, FabricError


def normalize_doi(value: str) -> str:
    value = value.strip()
    if value.lower().startswith(
        ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/")
    ):
        value = urlsplit(value).path.lstrip("/")
    elif value.lower().startswith("doi:"):
        value = value[4:]
    value = unquote(value).strip().lower()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", value):
        raise FabricError("invalid_argument", "Invalid DOI identifier.")
    return value


def arxiv_id(value: str) -> ExternalID:
    value = re.sub(r"^https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/", "", value.strip(), flags=re.I)
    value = re.sub(r"^arxiv:", "", value, flags=re.I)
    value = re.sub(r"\.pdf$", "", value)
    match = re.fullmatch(r"((?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7}))(v[1-9]\d*)?", value)
    if not match:
        raise FabricError("invalid_argument", "Invalid arXiv identifier.")
    return ExternalID(namespace="arxiv", value=match[1].lower(), version=match[2])


def parse_ref(ref: str) -> ExternalID | str:
    ref = ref.strip()
    if ref.startswith("fabric:"):
        try:
            UUID(ref[7:])
        except ValueError as exc:
            raise FabricError("invalid_argument", "Invalid fabric ID.") from exc
        return ref
    lower = ref.lower()
    if lower.startswith(
        (
            "doi:",
            "10.",
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "http://dx.doi.org/",
        )
    ):
        return ExternalID(namespace="doi", value=normalize_doi(ref))
    if lower.startswith(("arxiv:", "https://arxiv.org/", "http://arxiv.org/")):
        return arxiv_id(ref)
    if lower.startswith("openalex:"):
        value = ref.split(":", 1)[1].rsplit("/", 1)[-1].upper()
        if re.fullmatch(r"W\d+", value):
            return ExternalID(namespace="openalex", value=value)
    if lower.startswith("s2:"):
        value = ref[3:].lower()
        if re.fullmatch(r"[0-9a-f]{40}", value):
            return ExternalID(namespace="s2", value=value)
    if lower.startswith("pmid:"):
        raise FabricError("unsupported_identifier", "PMID resolution is not available in 0.1.")
    raise FabricError(
        "invalid_argument",
        "Use a DOI, arxiv:, openalex:, s2: or fabric: identifier; search titles first.",
    )


def id_key(identifier: ExternalID) -> tuple[str, str, str]:
    return identifier.namespace, identifier.value, identifier.version or ""


def normalized_title(title: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", title).casefold()))


def title_conflict(a: str, b: str) -> bool:
    return SequenceMatcher(None, normalized_title(a), normalized_title(b)).ratio() < 0.55
