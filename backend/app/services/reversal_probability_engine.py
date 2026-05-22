"""
Reversal Probability Engine
Scores stocks 0–100 based on max pain deviation + confluence factors.
"""

import math
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SCORE_CATEGORIES = [
    (80, "Extreme", "#ef4444"),
    (60, "Strong", "#f97316"),
    (40, "Moderate", "#eab308"),
    (0,  "Weak",    "#6b7280"),
]


def calculate_reversal_score(
    distance_pct: float,
    pcr: float,
    oi_bias: str,
    days_to_expiry: int,
    spot_price: float,
    max_pain: float,
    ce_oi_change: int = 0,
    pe_oi_change: int = 0,
    rsi: float = 50.0,
    volume_ratio: float = 1.0,
    vwap: float = 0.0,
) -> dict:
    """
    Score = weighted sum of individual factors.

    Factor weights (total 100):
      - Distance from max pain        : 30
      - OI buildup direction          : 15
      - PCR extreme reading           : 15
      - Near expiry magnifier         : 10
      - RSI extreme                   : 10
      - Volume expansion              : 10
      - VWAP deviation                : 10
    """
    score = 0.0
    breakdown = {}

    # 1. Distance from max pain (0-30)
    dist_score = min(30, distance_pct * 5)
    score += dist_score
    breakdown["distance_from_max_pain"] = round(dist_score, 1)

    # 2. OI buildup direction (0-15)
    # If spot is above max pain (bearish setup): reward PE buildup, penalize CE buildup
    # If spot is below max pain (bullish setup): reward CE unwinding, PE buildup
    above_pain = spot_price > max_pain
    if above_pain:
        # Bearish scenario: CE OI increasing = more resistance = higher reversal chance
        oi_score = 7.5
        if ce_oi_change > 0:
            oi_score += 7.5
        elif pe_oi_change > 0:
            oi_score += 3.75
    else:
        # Bullish scenario: PE OI increasing = more support unwinding
        oi_score = 7.5
        if pe_oi_change > 0:
            oi_score += 7.5
        elif ce_oi_change > 0:
            oi_score += 3.75
    score += oi_score
    breakdown["oi_buildup"] = round(oi_score, 1)

    # 3. PCR extreme reading (0-15)
    # Very high PCR when spot far above pain → extreme bearish signal
    if above_pain and pcr > 1.5:
        pcr_score = 15.0
    elif above_pain and pcr > 1.2:
        pcr_score = 10.0
    elif not above_pain and pcr < 0.6:
        pcr_score = 15.0
    elif not above_pain and pcr < 0.8:
        pcr_score = 10.0
    else:
        pcr_score = 5.0
    score += pcr_score
    breakdown["pcr_reading"] = round(pcr_score, 1)

    # 4. Near expiry magnifier (0-10)
    if days_to_expiry <= 2:
        expiry_score = 10.0
    elif days_to_expiry <= 5:
        expiry_score = 8.0
    elif days_to_expiry <= 10:
        expiry_score = 5.0
    else:
        expiry_score = 2.0
    score += expiry_score
    breakdown["near_expiry"] = round(expiry_score, 1)

    # 5. RSI extreme (0-10)
    if above_pain and rsi >= 70:
        rsi_score = 10.0
    elif above_pain and rsi >= 65:
        rsi_score = 7.0
    elif not above_pain and rsi <= 30:
        rsi_score = 10.0
    elif not above_pain and rsi <= 35:
        rsi_score = 7.0
    else:
        rsi_score = 2.0
    score += rsi_score
    breakdown["rsi_extreme"] = round(rsi_score, 1)

    # 6. Volume expansion (0-10)
    vol_score = min(10.0, (volume_ratio - 1.0) * 10.0) if volume_ratio > 1 else 0.0
    score += vol_score
    breakdown["volume_expansion"] = round(vol_score, 1)

    # 7. VWAP deviation (0-10)
    if vwap > 0 and spot_price > 0:
        vwap_dev = abs(spot_price - vwap) / spot_price * 100
        vwap_score = min(10.0, vwap_dev * 2.0)
        # Reward when VWAP deviation aligns with max pain reversal direction
        vwap_above = spot_price > vwap
        if (above_pain and vwap_above) or (not above_pain and not vwap_above):
            vwap_score = vwap_score
        else:
            vwap_score *= 0.5
    else:
        vwap_score = 0.0
    score += vwap_score
    breakdown["vwap_deviation"] = round(vwap_score, 1)

    final_score = min(100, round(score, 1))
    category, color = _categorize(final_score)
    direction = "bearish" if above_pain else "bullish"

    return {
        "score": final_score,
        "category": category,
        "color": color,
        "direction": direction,
        "breakdown": breakdown,
    }


def _categorize(score: float) -> tuple:
    for threshold, label, color in SCORE_CATEGORIES:
        if score >= threshold:
            return label, color
    return "Weak", "#6b7280"


def days_until_expiry(expiry_str: str) -> int:
    """
    Parse an expiry date string and return days to expiry.
    Supports NSE format ('25-Jul-2024') and Dhan format ('2024-07-25').
    """
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            expiry_dt = datetime.strptime(expiry_str, fmt)
            delta = expiry_dt.date() - datetime.now().date()
            return max(0, delta.days)
        except (ValueError, TypeError):
            continue
    return 30
