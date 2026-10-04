from scripts.round4_holdout_authoring import (
    bibliography_like,
    bibliography_start,
    candidate_stratum,
    select_candidates,
)


def test_bibliography_filters_heading_and_standalone_entry():
    assert bibliography_start("Discussion\n\nReferences\n[1] A") == 11
    assert bibliography_start("Related work discusses references in prose.") is None
    assert bibliography_like("[12] Smith, J. et al. A study. arXiv:2101.00001 (2021).")
    assert not bibliography_like("We compare with Smith et al. (2021) and improve accuracy by 4%.")


def test_candidate_strata_and_balanced_selection():
    assert candidate_stratum("Table 2 reports accuracy of 91.2% on the test set.") == "material"
    assert (
        candidate_stratum("However, this conclusion applies only to adults in the cohort.")
        == "scope_condition"
    )
    assert (
        candidate_stratum("We introduce a new encoder for document representations.") == "narrative"
    )
    candidates = []
    for index, stratum in enumerate(
        ("material",) * 5 + ("narrative",) * 5 + ("scope_condition",) * 5
    ):
        candidates.append(
            {"score": (1, 0, -100), "page": index + 1, "start": 0, "stratum": stratum}
        )
    selected = select_candidates(candidates, 9, stratified=True)
    assert {
        name: sum(item["stratum"] == name for item in selected)
        for name in {item["stratum"] for item in selected}
    } == {
        "material": 3,
        "narrative": 3,
        "scope_condition": 3,
    }
