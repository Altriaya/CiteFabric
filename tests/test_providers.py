import asyncio
import json

import httpx
import pytest

from citefabric.client import CiteFabricClient
from citefabric.models import Outcome, aggregate
from citefabric.providers import arxiv_entries, crossref, openalex, semantic_scholar
from citefabric.runtime import ProviderRuntime, retry_after

from .conftest import crossref_body


@pytest.mark.parametrize(
    "states,has_data,expected",
    [
        (["no_results", "no_results"], False, "no_results"),
        (["ok", "rate_limited"], True, "partial"),
        (["no_results", "rate_limited"], False, "partial"),
        (["unavailable", "rate_limited"], False, "failed"),
        (["ok", "ok"], True, "ok"),
        (["partial"], True, "partial"),
    ],
)
def test_outcome_aggregation(states, has_data, expected):
    assert (
        aggregate([Outcome(id=str(i), status=s) for i, s in enumerate(states)], has_data)
        == expected
    )


async def test_failed_provider_does_not_erase_results(config):
    def handler(request):
        if request.url.host == "api.crossref.org":
            return httpx.Response(200, json=crossref_body())
        return httpx.Response(429, headers={"Retry-After": "120"})

    config.offline = False
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        async with CiteFabricClient(config, http_client=http) as client:
            result = await client.search_papers("memory", sources=["crossref", "semantic_scholar"])
            assert result.status == "partial"
            assert len(result.data["papers"]) == 1
            assert result.outcomes[1].status == "rate_limited"
            assert result.outcomes[1].retry_after_seconds > 100


async def test_one_malformed_record_preserves_valid_records(config):
    body = crossref_body()
    body["message"]["items"].append({"title": ["No DOI"]})
    config.offline = False
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    ) as http:
        async with CiteFabricClient(config, http_client=http) as client:
            result = await client.search_papers("memory", sources=["crossref"])
            assert result.status == "partial"
            assert result.outcomes[0].records_received == 2
            assert result.outcomes[0].records_valid == 1


async def test_cache_and_cursor_do_not_refetch(config):
    calls = []
    items = [
        {
            "DOI": f"10.1234/item{i}",
            "title": [f"Memory experiment {i}"],
            "issued": {"date-parts": [[2020 + i]]},
        }
        for i in range(4)
    ]

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=crossref_body(items))

    config.offline = False
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        async with CiteFabricClient(config, http_client=http) as client:
            first = await client.search_papers("memory", sources=["crossref"], limit=2)
            second = await client.search_papers(
                "memory", sources=["crossref"], limit=2, cursor=first.meta.next_cursor
            )
            assert len(calls) == 1
            assert not {x["fabric_id"] for x in first.data["papers"]} & {
                x["fabric_id"] for x in second.data["papers"]
            }
            bad = await client.search_papers(
                "different", sources=["crossref"], cursor=first.meta.next_cursor
            )
            assert bad.errors[0].code == "invalid_argument"
            cached = await client.search_papers("memory", sources=["crossref"])
            assert cached.outcomes[0].cache_status == "fresh" and len(calls) == 1


async def test_one_waiter_cancels_without_cancelling_shared_request(config, store):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, text='{"ok":true}')

    config.offline = False
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        runtime = ProviderRuntime(config, store, http)
        a = asyncio.create_task(runtime.fetch("crossref", "https://api.crossref.org/works", {}))
        await entered.wait()
        b = asyncio.create_task(runtime.fetch("crossref", "https://api.crossref.org/works", {}))
        await asyncio.sleep(0)
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        release.set()
        assert (await b).text == '{"ok":true}'
        assert len(calls) == 1
        await runtime.close()


def test_provider_normalization_and_version_separation():
    record = crossref(crossref_body()["message"]["items"][0])
    assert record.issued.month is None
    oa = openalex(
        {
            "id": "https://openalex.org/W123",
            "title": "Memory",
            "abstract_inverted_index": {"improves": [1], "Memory": [0]},
            "publication_year": None,
        }
    )
    assert oa.abstract == "Memory improves" and oa.issued.year is None
    s2 = semantic_scholar(
        {
            "paperId": "a" * 40,
            "title": "Memory",
            "externalIds": {"DOI": "10.1234/test", "ArXiv": "2401.01234"},
        }
    )
    assert all(x.namespace != "arxiv" for x in s2.external_ids)
    assert s2.related_ids[0].namespace == "arxiv"


def test_arxiv_feed_and_error():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.01234v2</id><title>Memory</title><published>2024-01-03T00:00:00Z</published><author><name>A</name></author></entry></feed>"""
    record = arxiv_entries(feed)[0]
    assert record.version == "v2"
    assert record.candidates[0].url.endswith("v2")
    with pytest.raises(ValueError):
        arxiv_entries(
            feed.replace(
                "http://arxiv.org/abs/2401.01234v2",
                "http://arxiv.org/api/errors#incorrect_id_format",
            )
        )


def test_retry_after_formats():
    assert retry_after("3") == 3
    assert retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0
    assert retry_after("invalid") == 1


async def test_stale_cache_retains_failure_semantics(config):
    config.offline = False
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(429, headers={"Retry-After": "90"})
        )
    ) as http:
        async with CiteFabricClient(config, http_client=http) as client:
            provider = client.providers["crossref"]
            url, params, headers = provider.endpoint(query="memory")
            client.runtime.acknowledge(
                "crossref", url, params, headers, json.dumps(crossref_body()), -1
            )
            result = await client.search_papers("memory", sources=["crossref"])
            assert result.status == "partial" and result.meta.stale
            assert result.outcomes[0].code == "provider_rate_limited"


async def test_cached_reads_preserve_observation_time_and_expiry(config):
    config.offline = False
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=crossref_body()))
    ) as http:
        async with CiteFabricClient(config, http_client=http) as client:
            first = await client.search_papers("memory", sources=["crossref"])
            eid = first.data["papers"][0]["edition_id"]
            observed = client.store.records(eid)[0]
            snapshot = client.store.edition(eid).metadata_snapshot_id
            before = dict(
                client.store.db.execute(
                    "SELECT key,expires FROM cache WHERE key LIKE 'http:%'"
                ).fetchall()
            )
            await client.search_papers("memory", sources=["crossref"])
            after = dict(
                client.store.db.execute(
                    "SELECT key,expires FROM cache WHERE key LIKE 'http:%'"
                ).fetchall()
            )
            assert before == after
            assert client.store.records(eid)[0].retrieved_at == observed.retrieved_at
            assert client.store.edition(eid).metadata_snapshot_id == snapshot
