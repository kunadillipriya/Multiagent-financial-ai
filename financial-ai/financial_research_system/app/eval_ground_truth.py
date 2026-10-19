"""
eval_ground_truth.py
---------------------
Hand-verified correct answers for the 3 seed companies, used by
evaluation.py to score the Extraction Agent and Red Flag Agent. This is
possible (and honest) because these 3 documents are synthetic, authored for
this project -- every number below was copied by hand from
seed_documents/*.txt, and every red flag was independently verified against
the Red Flag Agent's own threshold rules in red_flag_agent.py (see the
comments next to the less-obvious ones).
"""

GROUND_TRUTH_METRICS = {
    "aurora": {
        "total_revenue": {"FY2024": 482_300_000, "FY2023": 410_100_000},
        "cost_of_revenue": {"FY2024": 217_500_000, "FY2023": 168_200_000},
        "gross_profit": {"FY2024": 264_800_000, "FY2023": 241_900_000},
        "gross_margin_pct": {"FY2024": 54.90, "FY2023": 59.00},
        "operating_expenses": {"FY2024": 198_400_000, "FY2023": 171_300_000},
        "operating_income": {"FY2024": 66_400_000, "FY2023": 70_600_000},
        "operating_margin_pct": {"FY2024": 13.77, "FY2023": 17.22},
        "net_income": {"FY2024": 41_200_000, "FY2023": 52_700_000},
        "net_margin_pct": {"FY2024": 8.54, "FY2023": 12.85},
        "diluted_eps": {"FY2024": 1.12, "FY2023": 1.44},
        "total_assets": {"FY2024": 912_600_000, "FY2023": 780_400_000},
        "total_liabilities": {"FY2024": 498_700_000, "FY2023": 365_100_000},
        "total_debt": {"FY2024": 340_000_000, "FY2023": 210_000_000},
        "total_shareholders_equity": {"FY2024": 413_900_000, "FY2023": 415_300_000},
        "cash_and_equivalents": {"FY2024": 128_400_000, "FY2023": 156_900_000},
        "operating_cash_flow": {"FY2024": 88_100_000, "FY2023": 97_300_000},
        "free_cash_flow": {"FY2024": 52_300_000, "FY2023": 71_100_000},
        "debt_to_equity_ratio": {"FY2024": 0.82, "FY2023": 0.51},
        "current_ratio": {"FY2024": 1.35, "FY2023": 1.68},
        "return_on_equity_pct": {"FY2024": 9.95, "FY2023": 12.69},
    },
    "nova": {
        "total_revenue": {"FY2024": 1_204_500_000, "FY2023": 1_158_900_000},
        "cost_of_revenue": {"FY2024": 758_800_000, "FY2023": 752_100_000},
        "gross_profit": {"FY2024": 445_700_000, "FY2023": 406_800_000},
        "gross_margin_pct": {"FY2024": 37.00, "FY2023": 35.10},
        "operating_expenses": {"FY2024": 312_600_000, "FY2023": 298_400_000},
        "operating_income": {"FY2024": 133_100_000, "FY2023": 108_400_000},
        "operating_margin_pct": {"FY2024": 11.05, "FY2023": 9.35},
        "net_income": {"FY2024": 89_400_000, "FY2023": 68_200_000},
        "net_margin_pct": {"FY2024": 7.42, "FY2023": 5.89},
        "diluted_eps": {"FY2024": 2.31, "FY2023": 1.79},
        "total_assets": {"FY2024": 2_145_300_000, "FY2023": 2_088_700_000},
        "total_liabilities": {"FY2024": 1_102_400_000, "FY2023": 1_187_600_000},
        "total_debt": {"FY2024": 640_000_000, "FY2023": 735_000_000},
        "total_shareholders_equity": {"FY2024": 1_042_900_000, "FY2023": 901_100_000},
        "cash_and_equivalents": {"FY2024": 210_600_000, "FY2023": 164_300_000},
        "operating_cash_flow": {"FY2024": 178_900_000, "FY2023": 151_200_000},
        "free_cash_flow": {"FY2024": 121_400_000, "FY2023": 94_600_000},
        "debt_to_equity_ratio": {"FY2024": 0.61, "FY2023": 0.82},
        "current_ratio": {"FY2024": 1.52, "FY2023": 1.41},
        "return_on_equity_pct": {"FY2024": 8.57, "FY2023": 7.57},
    },
    "meridian": {
        "total_revenue": {"FY2024": 675_200_000, "FY2023": 698_400_000},
        "cost_of_revenue": {"FY2024": 412_300_000, "FY2023": 389_500_000},
        "gross_profit": {"FY2024": 262_900_000, "FY2023": 308_900_000},
        "gross_margin_pct": {"FY2024": 38.94, "FY2023": 44.24},
        "operating_expenses": {"FY2024": 238_600_000, "FY2023": 221_400_000},
        "operating_income": {"FY2024": 24_300_000, "FY2023": 87_500_000},
        "operating_margin_pct": {"FY2024": 3.60, "FY2023": 12.53},
        "net_income": {"FY2024": 8_700_000, "FY2023": 58_900_000},
        "net_margin_pct": {"FY2024": 1.29, "FY2023": 8.43},
        "diluted_eps": {"FY2024": 0.21, "FY2023": 1.42},
        "total_assets": {"FY2024": 1_340_800_000, "FY2023": 1_298_600_000},
        "total_liabilities": {"FY2024": 842_100_000, "FY2023": 712_300_000},
        "total_debt": {"FY2024": 520_000_000, "FY2023": 380_000_000},
        "total_shareholders_equity": {"FY2024": 498_700_000, "FY2023": 586_300_000},
        "cash_and_equivalents": {"FY2024": 64_200_000, "FY2023": 112_800_000},
        "operating_cash_flow": {"FY2024": 31_600_000, "FY2023": 95_400_000},
        "free_cash_flow": {"FY2024": -8_900_000, "FY2023": 54_200_000},
        "debt_to_equity_ratio": {"FY2024": 1.04, "FY2023": 0.65},
        "current_ratio": {"FY2024": 1.11, "FY2023": 1.49},
        "return_on_equity_pct": {"FY2024": 1.75, "FY2023": 10.05},
    },
}

# Expected SET of red-flag types the Red Flag Agent should raise for each
# seed company, derived by hand from the rule book in red_flag_agent.py
# applied to the real numbers/language above. Order doesn't matter -- this
# is compared as a set (precision/recall), not an exact sequence.
#
# Aurora's ROE fell (9.95-12.69)/12.69 = -21.6% (> 20% threshold) and its
# current ratio fell (1.35-1.68)/1.68 = -19.6% (> 10% threshold) -- both
# legitimate trend triggers, verified by hand.
GROUND_TRUTH_RED_FLAGS = {
    "aurora": {
        "rising_debt", "rising_leverage", "margin_compression",
        "emphasis_of_matter", "debt_covenant_mention", "rising_dso",
        "declining_returns", "liquidity_weakening",
    },
    "nova": set(),  # the "clean" company: debt fell, margins improved, no audit issues
    "meridian": {
        "rising_debt", "rising_leverage", "margin_compression", "declining_returns",
        "liquidity_weakening", "liquidity_risk", "high_leverage", "negative_free_cash_flow",
        "emphasis_of_matter", "litigation", "product_recall", "material_weakness", "rising_dso",
    },
}


def match_company_key(name_or_filename: str):
    """Maps a document's company_name/filename to one of the ground-truth
    keys above, or None if it doesn't match any seed company (e.g. a real
    user-uploaded document, which has no ground truth to score against)."""
    lowered = (name_or_filename or "").lower()
    if "aurora" in lowered:
        return "aurora"
    if "nova" in lowered:
        return "nova"
    if "meridian" in lowered:
        return "meridian"
    return None
