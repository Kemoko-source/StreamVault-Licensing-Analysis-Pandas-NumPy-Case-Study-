"""Tests for package-level offer eligibility and budget-constrained selection."""

import pandas as pd

from src.licensing import build_license_decision


def _offer(candidate_id, score, fee, rights="yes"):
    return {
        "candidate_id": candidate_id,
        "candidate_type": "standalone",
        "candidate_name": candidate_id,
        "collection_id": pd.NA,
        "member_tmdb_ids": candidate_id.split(":")[-1],
        "member_titles": candidate_id,
        "all_year_rank": 1,
        "all_year_score": score,
        "post_2000_rank": 1,
        "post_2000_score": score,
        "license_fee_usd": fee,
        "rights_available": rights,
        "territory": "US",
        "license_start_date": "2027-01-01",
        "license_end_date": "2027-12-31",
        "quote_date": "2026-11-01",
        "offer_source": "test quote",
    }


def test_knapsack_selects_best_candidate_mix_for_each_cohort():
    # Two $6 offers together score better than the $10 offer under a $12 cap.
    offers = pd.DataFrame(
        [
            _offer("title:1", 9.0, 10),
            _offer("title:2", 6.0, 6),
            _offer("title:3", 6.0, 6),
        ]
    )

    summary, candidates = build_license_decision(offers, budget_usd=12)

    assert summary["total_license_cost_usd"].eq(12).all()
    assert summary["total_adjusted_rating"].eq(12).all()
    assert summary["selected_packages"].eq(2).all()
    assert summary["selected_titles"].eq(2).all()
    selected = set(candidates.loc[candidates["selected"], "candidate_id"])
    assert selected == {"title:2", "title:3"}


def test_unavailable_or_incomplete_offers_are_not_selected():
    # Missing terms and unavailable rights both exclude an offer.
    offers = pd.DataFrame(
        [
            _offer("title:1", 9.0, 5, rights="no"),
            {
                **_offer("title:2", 8.0, ""),
                "rights_available": "",
                "territory": "",
                "license_start_date": "",
                "license_end_date": "",
                "quote_date": "",
                "offer_source": "",
            },
        ]
    )

    summary, candidates = build_license_decision(offers, budget_usd=12)

    assert summary["decision_status"].eq("no_eligible_offers").all()
    assert not candidates["selected"].any()
    assert candidates.loc[0, "eligibility_reason"] == "rights_unavailable"
    assert "missing_license_fee" in candidates.loc[1, "eligibility_reason"]


def test_budget_does_not_allow_a_package_to_be_split():
    # A two-film franchise is still one indivisible offer.
    offer = _offer("collection:42", 20.0, 15)
    offer["candidate_type"] = "franchise_bundle"
    offer["member_tmdb_ids"] = "11|12"
    offer["member_titles"] = "Film 11 | Film 12"

    summary, candidates = build_license_decision(pd.DataFrame([offer]), budget_usd=12)

    assert summary["decision_status"].eq("no_eligible_offers").all()
    assert candidates["eligibility_reason"].eq("fee_exceeds_budget").all()
    assert not candidates["selected"].any()
