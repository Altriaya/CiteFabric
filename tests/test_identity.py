import pytest

from citefabric.identity import arxiv_id, normalize_doi, parse_ref
from citefabric.models import FabricError, SourceRecord

from .conftest import record


def test_identifiers_preserve_meaning():
    assert normalize_doi("https://doi.org/10.1234/A%28B%29.") == "10.1234/a(b)."
    assert normalize_doi("DOI:10.1234/A_B") == "10.1234/a_b"
    assert arxiv_id("https://arxiv.org/pdf/hep-th/9901001v2.pdf").version == "v2"
    assert arxiv_id("arxiv:2401.01234v12").value == "2401.01234"
    with pytest.raises(FabricError):
        parse_ref("A paper title")
    with pytest.raises(FabricError, match="PMID"):
        parse_ref("pmid:123")


def test_exact_doi_deduplicates_preserving_sources_and_snapshots(store):
    first = store.ingest(record())
    before = store.metadata(first.metadata_snapshot_id)
    second = store.ingest(record(provider="openalex"))
    assert second.edition_id == first.edition_id
    assert len(store.records(second.edition_id)) == 2
    assert store.metadata(before.snapshot_id) == before
    assert second.metadata_snapshot_id != before.snapshot_id
    assert second.identity_status == "verified"


def test_similar_titles_do_not_merge_distinct_dois(store):
    a = store.ingest(record())
    b = store.ingest(record(doi="10.1234/different"))
    assert a.fabric_id != b.fabric_id
    assert store.paper(a.fabric_id).relations[0]["relation"] == "possible_duplicate"


def test_strong_id_conflicts_are_quarantined(store):
    a = store.ingest(record())
    bad = store.ingest(record(title="Zinc catalysis of alkaline hydrogen production"))
    assert bad.identity_status == "conflict"
    assert (
        store.metadata(bad.metadata_snapshot_id).title
        == store.metadata(a.metadata_snapshot_id).title
    )
    assert len(store.records(a.edition_id)) == 1
    assert (
        store.db.execute("SELECT count(*) FROM source_records WHERE edition_id IS NULL").fetchone()[
            0
        ]
        == 1
    )


def test_arxiv_versions_share_work_but_not_edition(store):
    def version(v):
        return SourceRecord(
            provider="arxiv",
            source_id="2401.01234" + v,
            title="A study of memory",
            version=v,
            kind="preprint",
            external_ids=[arxiv_id("2401.01234" + v)],
        )

    a, b = store.ingest(version("v1")), store.ingest(version("v2"))
    assert a.fabric_id == b.fabric_id
    assert a.edition_id != b.edition_id
    assert store.lookup(arxiv_id("2401.01234v1"))[0].edition_id == a.edition_id
    assert len(store.paper(a.fabric_id).edition_ids) == 2


def test_two_store_instances_share_rate_budget(config):
    from citefabric.storage import Store

    a, b = Store(config.data_dir), Store(config.data_dir)
    try:
        token, wait = a.acquire("arxiv", 3, 10)
        assert token and wait == 0
        second, wait = b.acquire("arxiv", 3, 10)
        assert second is None and wait > 0
        a.release("arxiv", token)
        second, wait = b.acquire("arxiv", 3, 10)
        assert second is None and 0 < wait <= 3
    finally:
        a.close()
        b.close()


def test_aggregator_bridge_cannot_change_doi(store):
    from citefabric.models import ExternalID

    a = record()
    a.external_ids.append(ExternalID(namespace="s2", value="a" * 40))
    original = store.ingest(a)
    changed = record(provider="semantic_scholar", doi="10.1234/different")
    changed.external_ids.append(ExternalID(namespace="s2", value="a" * 40))
    result = store.ingest(changed)
    assert result.identity_status == "conflict"
    assert result.edition_id == original.edition_id
    assert {e.value for e in result.external_ids if e.namespace == "doi"} == {"10.1234/example"}


async def test_explicit_arxiv_version_cannot_be_overridden(config):
    from citefabric.client import CiteFabricClient

    async with CiteFabricClient(config) as client:
        versions = []
        for version in ("v1", "v2"):
            versions.append(
                client.store.ingest(
                    SourceRecord(
                        provider="arxiv",
                        source_id="2401.01234" + version,
                        title="Memory",
                        kind="preprint",
                        version=version,
                        external_ids=[arxiv_id("2401.01234" + version)],
                    )
                )
            )
        result = await client.get_paper("arxiv:2401.01234v1", edition_id=versions[1].edition_id)
        assert result.status == "failed" and result.errors[0].code == "invalid_argument"
