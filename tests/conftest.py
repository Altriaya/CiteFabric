import pytest

from citefabric.config import Config
from citefabric.models import Author, ExternalID, Issued, SourceRecord
from citefabric.storage import Store


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path / "workspace", offline=True)


@pytest.fixture
def store(config):
    value = Store(config.data_dir)
    yield value
    value.close()


def record(
    provider="crossref", title="Memory improves task completion", doi="10.1234/example", **kwargs
):
    return SourceRecord(
        provider=provider,
        source_id=doi,
        title=title,
        authors=[Author(display_name="Alex Example", given="Alex", family="Example")],
        issued=Issued(year=2024),
        kind="journal_article",
        external_ids=[ExternalID(namespace="doi", value=doi)],
        **kwargs,
    )


def crossref_body(items=None):
    return {
        "status": "ok",
        "message": {
            "items": items
            if items is not None
            else [
                {
                    "DOI": "10.1234/example",
                    "title": ["Memory improves task completion"],
                    "author": [{"given": "Alex", "family": "Example"}],
                    "issued": {"date-parts": [[2024]]},
                    "type": "journal-article",
                }
            ]
        },
    }


def pdf_bytes(text=None):
    """Small deterministic PDF for parser regression, not an exported artifact."""
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        content = DecodedStreamObject()
        content.set_data(
            (
                "BT /F1 12 Tf 50 700 Td ("
                + text.replace("(", r"\(").replace(")", r"\)")
                + ") Tj ET"
            ).encode()
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()
