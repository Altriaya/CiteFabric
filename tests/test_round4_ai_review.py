from scripts import round4_ai_review as review


def _pair(required):
    return {
        "pair_id": "p1",
        "candidate_evidence_identical": False,
        "reference": {
            "verdict": "supported",
            "requirements": [{"requirement_id": "r1"}],
            "sufficient_sets": [["r1"]],
            "limitation_rating_required": required,
        },
        "candidates": [
            {
                "candidate_id": "c1",
                "label": "A",
                "evidence": [{"alias": "E1", "excerpt": "evidence"}],
            },
            {
                "candidate_id": "c2",
                "label": "B",
                "evidence": [{"alias": "E1", "excerpt": "other"}],
            },
        ],
    }


def _raw(limitation):
    return {
        "pairs": [
            {
                "pair_id": "p1",
                "candidates": [
                    {
                        "label": "A",
                        "sufficiency": "complete",
                        "requirement_ratings": [{"requirement_id": "r1", "state": "present"}],
                        "harmful_mismatch": False,
                        "mismatch_types": [],
                        "limitation_preserved": limitation,
                        "failure_stage": "none",
                        "evidence_aliases": ["E1"],
                        "rationale": "The requirement is present in E1.",
                    }
                ],
            }
        ]
    }


def test_normalization_uses_only_candidates_in_task_and_normalizes_limitation():
    pair = _pair(required=False)
    task = {"pair_id": "p1", "candidates": [{"label": "A"}]}
    normalized = review._normalize_response(_raw(False), [task], {"p1": pair})
    assert set(normalized["p1"]) == {"A"}
    assert normalized["p1"]["A"]["limitation_preserved"] is None

    pair = _pair(required=True)
    normalized = review._normalize_response(_raw(None), [task], {"p1": pair})
    assert normalized["p1"]["A"]["limitation_preserved"] is False


def test_batch_respects_pair_and_character_limits():
    tasks = [{"pair_id": str(i), "text": "x" * 100} for i in range(5)]
    batches = review._batch(tasks, max_pairs=2, max_chars=1000)
    assert [len(batch) for batch in batches] == [2, 2, 1]
    batches = review._batch(tasks, max_pairs=10, max_chars=250)
    assert all(len(batch) == 1 for batch in batches)
