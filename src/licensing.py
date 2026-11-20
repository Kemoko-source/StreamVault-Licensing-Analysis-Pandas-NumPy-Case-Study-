"""Compare verified franchise-package and standalone offers to the $14M cap."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OFFERS_PATH = PROJECT_ROOT / "data" / "raw" / "license_offers_template.csv"
DECISION_SUMMARY_PATH = PROJECT_ROOT / "reports" / "license_decision_summary.csv"
DECISION_CANDIDATES_PATH = PROJECT_ROOT / "reports" / "license_decision_candidates.csv"
BUDGET_USD = Decimal("14000000.00")
OFFER_FIELDS = (
    "license_fee_usd",
    "rights_available",
    "territory",
    "license_start_date",
    "license_end_date",
    "quote_date",
    "offer_source",
)
SCOPE_CAVEAT = (
    "Assumes offers marked available cover the intended territory and window. "
    "Portfolio value is the sum of audience scores, not financial ROI."
)


def _money_to_cents(value: object) -> tuple[int | None, str | None]:
    # Cents keep budget comparisons exact instead of using floating-point money.
    if pd.isna(value) or not str(value).strip():
        return None, "missing_license_fee"
    try:
        amount = Decimal(str(value).strip()).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except InvalidOperation:
        return None, "invalid_license_fee"
    if not amount.is_finite():
        return None, "invalid_license_fee"
    if amount < 0:
        return None, "negative_license_fee"
    return int(amount * 100), None


def _rights_status(value: object) -> tuple[bool | None, str | None]:
    if pd.isna(value) or not str(value).strip():
        return None, "missing_rights_status"
    normalized = str(value).strip().casefold()
    if normalized in {"yes", "y", "true", "1", "available"}:
        return True, None
    if normalized in {"no", "n", "false", "0", "unavailable"}:
        return False, "rights_unavailable"
    return None, "invalid_rights_status"


def _has_value(value: object) -> bool:
    return not pd.isna(value) and bool(str(value).strip())


def _knapsack(
    candidates: list[tuple[int, float, int]],
    budget_cents: int,
) -> tuple[int, ...]:
    """Return candidate positions maximizing total score within the fee cap."""
    # Track the best score for each spend amount as each candidate is considered.
    states: dict[int, tuple[float, tuple[int, ...]]] = {0: (0.0, ())}

    for position, (fee_cents, score, _) in enumerate(candidates):
        updated = states.copy()
        for spent, (current_score, selected) in states.items():
            total_spend = spent + fee_cents
            if total_spend > budget_cents:
                continue
            total_score = current_score + score
            previous = updated.get(total_spend)
            if previous is None or total_score > previous[0] + 1e-12:
                updated[total_spend] = (total_score, selected + (position,))

        # Drop states that cost more but do not improve the score.
        best_score = float("-inf")
        states = {}
        for spent in sorted(updated):
            candidate_score, selected = updated[spent]
            if candidate_score > best_score + 1e-12:
                states[spent] = (candidate_score, selected)
                best_score = candidate_score

    _, (_, selected_positions) = min(
        states.items(),
        key=lambda item: (-item[1][0], item[0]),
    )
    return selected_positions


def build_license_decision(
    offers: pd.DataFrame,
    budget_usd: object = BUDGET_USD,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select whole franchise packages or standalone offers per cohort."""
    required = {
        "candidate_id",
        "candidate_type",
        "candidate_name",
        "member_tmdb_ids",
        "member_titles",
        "all_year_rank",
        "all_year_score",
        "post_2000_rank",
        "post_2000_score",
        *OFFER_FIELDS,
    }
    missing_columns = required.difference(offers.columns)
    if missing_columns:
        raise ValueError(f"Offers missing columns: {', '.join(sorted(missing_columns))}")

    budget_cents, budget_error = _money_to_cents(budget_usd)
    if budget_error or budget_cents is None:
        raise ValueError("budget_usd must be a non-negative finite amount")
    validated = offers.copy().reset_index(drop=True)
    duplicate_ids = validated["candidate_id"].duplicated(keep=False)
    validated["_fee_cents"] = None
    validated["eligibility_status"] = "eligible"
    validated["eligibility_reason"] = ""

    # Mark incomplete, invalid, or unavailable offers before optimizing.
    for index, row in validated.iterrows():
        reasons = []
        if not _has_value(row["candidate_id"]):
            reasons.append("missing_candidate_id")
        elif duplicate_ids.loc[index]:
            reasons.append("duplicate_candidate_id")

        fee_cents, fee_reason = _money_to_cents(row["license_fee_usd"])
        if fee_reason:
            reasons.append(fee_reason)
        elif fee_cents > budget_cents:
            reasons.append("fee_exceeds_budget")

        rights_available, rights_reason = _rights_status(row["rights_available"])
        if rights_reason:
            reasons.append(rights_reason)

        for column in (
            "candidate_type",
            "candidate_name",
            "member_tmdb_ids",
            "member_titles",
            "territory",
            "license_start_date",
            "license_end_date",
            "quote_date",
            "offer_source",
        ):
            if not _has_value(row[column]):
                reasons.append(f"missing_{column}")

        start = (
            pd.to_datetime(row["license_start_date"], errors="coerce")
            if _has_value(row["license_start_date"])
            else pd.NaT
        )
        end = (
            pd.to_datetime(row["license_end_date"], errors="coerce")
            if _has_value(row["license_end_date"])
            else pd.NaT
        )
        quote_date = (
            pd.to_datetime(row["quote_date"], errors="coerce")
            if _has_value(row["quote_date"])
            else pd.NaT
        )
        if _has_value(row["license_start_date"]) and pd.isna(start):
            reasons.append("invalid_license_start_date")
        if _has_value(row["license_end_date"]) and pd.isna(end):
            reasons.append("invalid_license_end_date")
        if _has_value(row["quote_date"]) and pd.isna(quote_date):
            reasons.append("invalid_quote_date")
        if not pd.isna(start) and not pd.isna(end) and start > end:
            reasons.append("invalid_license_date_range")
        if rights_available is False and "rights_unavailable" not in reasons:
            reasons.append("rights_unavailable")

        if fee_cents is not None:
            validated.at[index, "_fee_cents"] = fee_cents
            validated.at[index, "license_fee_usd"] = fee_cents / 100
        if reasons:
            validated.at[index, "eligibility_status"] = "excluded"
            validated.at[index, "eligibility_reason"] = ";".join(dict.fromkeys(reasons))

    validated["selected"] = False
    summary_rows = []
    # Optimize each time window on its own score column.
    for cohort, score_column, rank_column in (
        ("all_years", "all_year_score", "all_year_rank"),
        ("2000_onward", "post_2000_score", "post_2000_rank"),
    ):
        score = pd.to_numeric(validated[score_column], errors="coerce")
        eligible = validated["eligibility_status"].eq("eligible")
        cohort_eligible = eligible & score.notna() & score.ge(0)
        cohort_rows = validated.loc[cohort_eligible].copy()
        candidates = [
            (int(row["_fee_cents"]), float(row[score_column]), int(index))
            for index, row in cohort_rows.iterrows()
        ]
        selected_positions = _knapsack(candidates, budget_cents)
        selected_indices = [candidates[position][2] for position in selected_positions]
        validated.loc[selected_indices, "selected"] = True
        validated.loc[eligible & score.isna(), "eligibility_reason"] = (
            validated.loc[eligible & score.isna(), "eligibility_reason"]
            .map(lambda reason: f"{reason};not_ranked_in_cohort".strip(";"))
        )

        selected_rows = validated.loc[selected_indices]
        total_cost_cents = sum(int(value) for value in selected_rows["_fee_cents"])
        total_score = float(selected_rows[score_column].sum())
        summary_rows.append(
            {
                "cohort": cohort,
                "budget_usd": budget_cents / 100,
                "decision_status": "optimized" if len(cohort_rows) else "no_eligible_offers",
                "selected_packages": len(selected_rows),
                "selected_titles": sum(
                    len(str(value).split("|")) for value in selected_rows["member_tmdb_ids"]
                ),
                "total_license_cost_usd": total_cost_cents / 100,
                "budget_remaining_usd": (budget_cents - total_cost_cents) / 100,
                "total_adjusted_rating": total_score,
                "scope_caveat": SCOPE_CAVEAT,
            }
        )

    validated["selection_status"] = np.where(
        validated["selected"],
        "selected",
        np.where(
            validated["eligibility_status"] == "eligible",
            "eligible_not_selected",
            "excluded",
        ),
    )
    validated = validated.drop(columns="_fee_cents")
    return pd.DataFrame(summary_rows), validated


def run_license_decision(
    offers_path: str | Path = OFFERS_PATH,
    budget_usd: object = BUDGET_USD,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    offers = pd.read_csv(offers_path)
    summary, candidates = build_license_decision(offers, budget_usd)
    DECISION_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(DECISION_SUMMARY_PATH, index=False)
    candidates.to_csv(DECISION_CANDIDATES_PATH, index=False)
    return summary, candidates


def main() -> None:
    summary, _ = run_license_decision()
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
