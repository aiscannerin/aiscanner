"""
Option Chain Payload Validator
================================
Validates raw NSE API responses and parsed OptionChainResult objects
before analytics consume the data.

Public API:
    validate_raw_response(raw_body, content_type) -> ValidationResult
    validate_parsed_chain(result)                 -> ValidationResult
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_IV               = 300.0    # % — above this is impossible
_MAX_SPOT_PRICE       = 1_000_000
_MIN_SPOT_PRICE       = 1.0
_MAX_OI_DOMINANCE     = 0.50     # single strike > 50% of total OI => warning
_MAX_STALENESS_SECS   = 120      # data older than 2 min during market hours
_MIN_STRIKES          = 3
_MAX_STRIKES          = 400

# NSE date pattern: "25-Jul-2024"
_NSE_DATE_RE = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$")

# HTML detection heuristics
_HTML_MARKERS = ["<!DOCTYPE", "<html", "<body", "captcha", "verify you are human"]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    code:    str
    message: str
    field:   str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "field": self.field}


@dataclass
class ValidationResult:
    is_valid:         bool              = True
    warnings:         list[ValidationIssue] = field(default_factory=list)
    errors:           list[ValidationIssue] = field(default_factory=list)
    corruption_score: float             = 0.0  # 0.0 = clean, 1.0 = fully corrupt

    # ---- helpers ----

    def add_error(self, code: str, message: str, field: str = "") -> None:
        self.errors.append(ValidationIssue(code, message, field))
        self.is_valid = False

    def add_warning(self, code: str, message: str, field: str = "") -> None:
        self.warnings.append(ValidationIssue(code, message, field))

    def to_dict(self) -> dict:
        return {
            "is_valid":         self.is_valid,
            "warnings":         [w.to_dict() for w in self.warnings],
            "errors":           [e.to_dict() for e in self.errors],
            "corruption_score": round(self.corruption_score, 3),
        }

    def _compute_corruption_score(self) -> None:
        """
        Heuristic score: each error adds 0.25, each warning adds 0.05,
        capped at 1.0.
        """
        score = min(1.0, len(self.errors) * 0.25 + len(self.warnings) * 0.05)
        self.corruption_score = round(score, 3)


# ---------------------------------------------------------------------------
# Raw response validation (before JSON parse)
# ---------------------------------------------------------------------------

def validate_raw_response(
    raw_body: str,
    content_type: str = "",
    symbol: str = "",
) -> ValidationResult:
    """
    Validate the raw HTTP response body before attempting JSON parsing.
    Detects HTML, captcha pages, and obviously empty payloads.
    """
    vr = ValidationResult()
    ct_lower = content_type.lower()

    # 1. Content-type must be JSON
    if content_type and "application/json" not in ct_lower:
        vr.add_error(
            "WRONG_CONTENT_TYPE",
            f"Expected application/json, got '{content_type}'",
            "Content-Type",
        )
        logger.error(
            "NSE payload content-type mismatch symbol=%s content_type=%s",
            symbol, content_type,
        )

    # 2. HTML / captcha detection
    body_lower = raw_body[:4096].lower()
    for marker in _HTML_MARKERS:
        if marker.lower() in body_lower:
            vr.add_error(
                "HTML_OR_CAPTCHA",
                f"Response contains HTML/captcha marker: '{marker}'",
                "body",
            )
            logger.error(
                "NSE returned HTML/captcha for symbol=%s marker='%s'",
                symbol, marker,
            )
            break

    # 3. Empty body
    if not raw_body or not raw_body.strip():
        vr.add_error("EMPTY_BODY", "Response body is empty", "body")

    vr._compute_corruption_score()
    return vr


# ---------------------------------------------------------------------------
# Parsed-chain validation (after JSON parse, before analytics)
# ---------------------------------------------------------------------------

def validate_parsed_chain(result: Any, symbol: str = "") -> ValidationResult:
    """
    Validate an OptionChainResult (or its dict representation).
    Accepts either the dataclass or a plain dict with equivalent keys.
    """
    vr = ValidationResult()

    # Normalise to dict access
    if hasattr(result, "to_dict"):
        data = result.to_dict()
        strikes_raw = result.strikes  # list[StrikeRow]
    else:
        data = result
        strikes_raw = data.get("strikes", [])

    # ---- 1. Required top-level fields ----
    required = ["symbol", "expiry", "all_expiries", "spot_price", "timestamp"]
    for f_name in required:
        val = data.get(f_name)
        if val is None or val == "" or val == []:
            vr.add_error(
                "MISSING_REQUIRED_FIELD",
                f"Required field '{f_name}' is absent or empty",
                f_name,
            )

    # ---- 2. Spot price sanity ----
    spot = data.get("spot_price", 0) or 0
    if not (_MIN_SPOT_PRICE <= spot <= _MAX_SPOT_PRICE):
        vr.add_error(
            "INVALID_SPOT_PRICE",
            f"spot_price={spot} is outside plausible range "
            f"[{_MIN_SPOT_PRICE}, {_MAX_SPOT_PRICE}]",
            "spot_price",
        )

    # ---- 3. Expiry format ----
    expiry = data.get("expiry", "")
    if expiry and not _NSE_DATE_RE.match(str(expiry)):
        vr.add_warning(
            "EXPIRY_FORMAT",
            f"expiry='{expiry}' does not match expected NSE date format DD-Mon-YYYY",
            "expiry",
        )

    all_expiries = data.get("all_expiries") or []
    if not all_expiries:
        vr.add_error("NO_EXPIRIES", "all_expiries list is empty", "all_expiries")
    else:
        for i, exp in enumerate(all_expiries):
            if not _NSE_DATE_RE.match(str(exp)):
                vr.add_warning(
                    "EXPIRY_FORMAT",
                    f"all_expiries[{i}]='{exp}' has unexpected format",
                    f"all_expiries[{i}]",
                )
                break  # one warning is enough

    # ---- 4. Timestamp freshness ----
    ts = data.get("timestamp", "")
    if ts:
        try:
            parsed_ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age_secs = (datetime.now(timezone.utc) - parsed_ts).total_seconds()
            if age_secs > _MAX_STALENESS_SECS:
                vr.add_warning(
                    "STALE_DATA",
                    f"Data is {int(age_secs)}s old (threshold={_MAX_STALENESS_SECS}s)",
                    "timestamp",
                )
                logger.warning(
                    "Stale NSE data symbol=%s age_secs=%.0f",
                    symbol or data.get("symbol"), age_secs,
                )
        except (ValueError, TypeError):
            vr.add_warning(
                "UNPARSEABLE_TIMESTAMP",
                f"Cannot parse timestamp: '{ts}'",
                "timestamp",
            )

    # ---- 5. Strike list checks ----
    _validate_strikes(vr, strikes_raw, data, symbol)

    # ---- 6. Aggregate OI sanity ----
    total_ce_oi = data.get("total_ce_oi", 0) or 0
    total_pe_oi = data.get("total_pe_oi", 0) or 0
    if total_ce_oi == 0 and total_pe_oi == 0:
        vr.add_error(
            "EMPTY_CHAIN",
            "Both total_ce_oi and total_pe_oi are zero — chain appears empty",
            "total_ce_oi",
        )
        logger.error("Empty option chain detected symbol=%s", symbol or data.get("symbol"))

    vr._compute_corruption_score()
    return vr


def _validate_strikes(
    vr: ValidationResult,
    strikes_raw: list,
    data: dict,
    symbol: str,
) -> None:
    """Inner helper — validates the strikes list in-place on vr."""
    total_ce_oi = data.get("total_ce_oi", 0) or 0
    total_pe_oi = data.get("total_pe_oi", 0) or 0
    total_oi    = total_ce_oi + total_pe_oi

    if not strikes_raw:
        vr.add_error("NO_STRIKES", "strikes list is empty", "strikes")
        return

    # Normalise to dict for uniform access
    def to_d(s: Any) -> dict:
        return s.to_dict() if hasattr(s, "to_dict") else s

    strike_dicts = [to_d(s) for s in strikes_raw]
    strike_vals  = [float(s.get("strike", 0)) for s in strike_dicts]

    # Count
    if len(strike_vals) < _MIN_STRIKES:
        vr.add_error(
            "TOO_FEW_STRIKES",
            f"Only {len(strike_vals)} strikes (minimum {_MIN_STRIKES})",
            "strikes",
        )
    if len(strike_vals) > _MAX_STRIKES:
        vr.add_warning(
            "TOO_MANY_STRIKES",
            f"{len(strike_vals)} strikes exceeds expected max {_MAX_STRIKES}",
            "strikes",
        )

    # Ascending order
    for i in range(1, len(strike_vals)):
        if strike_vals[i] <= strike_vals[i - 1]:
            vr.add_error(
                "STRIKE_ORDER",
                f"strikes not in ascending order at index {i}: "
                f"{strike_vals[i-1]} >= {strike_vals[i]}",
                f"strikes[{i}].strike",
            )
            break  # one error is enough

    # Duplicates
    seen: set[float] = set()
    for v in strike_vals:
        if v in seen:
            vr.add_error(
                "DUPLICATE_STRIKE",
                f"Duplicate strike value: {v}",
                "strikes[*].strike",
            )
            logger.error(
                "Duplicate strike %s in chain symbol=%s",
                v, symbol or data.get("symbol"),
            )
            break
        seen.add(v)

    # Per-strike validation
    for i, s in enumerate(strike_dicts):
        strike = s.get("strike", 0)
        for side in ("ce", "pe"):
            leg = s.get(side, {}) or {}
            _validate_leg(vr, leg, strike, side, i, total_oi, symbol or data.get("symbol", ""))


def _validate_leg(
    vr: ValidationResult,
    leg: dict,
    strike: float,
    side: str,
    idx: int,
    total_oi: int,
    symbol: str,
) -> None:
    """Validate one CE or PE leg."""
    iv  = float(leg.get("iv",  0) or 0)
    oi  = int(leg.get("oi",   0) or 0)
    bid = float(leg.get("bid", 0) or 0)
    ask = float(leg.get("ask", 0) or 0)

    # Impossible IV
    if iv > _MAX_IV:
        vr.add_warning(
            "IMPOSSIBLE_IV",
            f"IV={iv}% at strike={strike} {side.upper()} exceeds {_MAX_IV}%",
            f"strikes[{idx}].{side}.iv",
        )
        logger.warning(
            "Impossible IV detected symbol=%s strike=%s side=%s iv=%.1f",
            symbol, strike, side, iv,
        )

    # OI must be non-negative
    if oi < 0:
        vr.add_error(
            "NEGATIVE_OI",
            f"OI={oi} is negative at strike={strike} {side.upper()}",
            f"strikes[{idx}].{side}.oi",
        )

    # Single-strike OI dominance
    if total_oi > 0 and oi > 0 and (oi / total_oi) > _MAX_OI_DOMINANCE:
        vr.add_warning(
            "OI_DOMINANCE",
            f"Strike={strike} {side.upper()} OI={oi} is "
            f"{oi/total_oi*100:.1f}% of total OI (threshold {_MAX_OI_DOMINANCE*100:.0f}%)",
            f"strikes[{idx}].{side}.oi",
        )
        logger.warning(
            "OI dominance anomaly symbol=%s strike=%s side=%s share=%.2f",
            symbol, strike, side, oi / total_oi,
        )

    # bid <= ask
    if bid > 0 and ask > 0 and bid > ask:
        vr.add_warning(
            "BID_ASK_CROSSED",
            f"bid={bid} > ask={ask} at strike={strike} {side.upper()}",
            f"strikes[{idx}].{side}",
        )


# ---------------------------------------------------------------------------
# Convenience: validate a raw JSON dict from NSE (pre-parse check)
# ---------------------------------------------------------------------------

def validate_nse_json_structure(raw_json: dict, symbol: str = "") -> ValidationResult:
    """
    Relaxed structural check on the raw NSE JSON dict (before _parse_raw_chain).

    Accepts all four NSE payload shapes:
      1. Standard:        {"records": {"data": [...], "underlyingValue": X, "expiryDates": [...]}}
      2. Filtered-only:   {"filtered": {"data": [...], "underlyingValue": X}}
      3. Top-level data:  {"data": [...]}  (rare alternate format)
      4. Partial records: {"records": {"data": [...]}}  (underlyingValue / expiryDates derivable)

    Only errors when NO data rows can be located anywhere in the payload.
    Missing optional fields (underlyingValue, expiryDates) become warnings — they
    can be derived from the row data by _extract_nse_payload().
    """
    vr = ValidationResult()

    if not isinstance(raw_json, dict):
        vr.add_error("NOT_A_DICT", "NSE response is not a JSON object", "root")
        vr._compute_corruption_score()
        return vr

    records  = raw_json.get("records")  or {}
    filtered = raw_json.get("filtered") or {}

    # ── Locate data rows ──────────────────────────────────────────────────────
    data_rows = (
        records.get("data")
        or filtered.get("data")
        or (raw_json.get("data") if isinstance(raw_json.get("data"), list) else None)
        or []
    )

    if not data_rows:
        vr.add_error(
            "NO_DATA_ROWS",
            "Cannot locate option-chain data rows in any known payload shape "
            "(tried records.data, filtered.data, root.data)",
            "data",
        )
        logger.error(
            "NSE response has no data rows — top-level keys=%s symbol=%s",
            list(raw_json.keys()), symbol,
        )
        vr._compute_corruption_score()
        return vr

    # ── Warn about missing optional fields (derivable) ─────────────────────
    has_underlying = (
        records.get("underlyingValue") is not None
        or filtered.get("underlyingValue") is not None
        or raw_json.get("underlyingValue") is not None
    )
    if not has_underlying:
        vr.add_warning(
            "MISSING_UNDERLYING_VALUE",
            "underlyingValue absent — will attempt to derive from CE/PE LTP",
            "records.underlyingValue",
        )
        logger.warning("NSE response missing underlyingValue for symbol=%s — will derive", symbol)

    has_expiries = bool(
        records.get("expiryDates")
        or filtered.get("expiryDates")
        or raw_json.get("expiryDates")
    )
    if not has_expiries:
        vr.add_warning(
            "MISSING_EXPIRY_DATES",
            "expiryDates absent — will derive from expiryDate field in data rows",
            "records.expiryDates",
        )
        logger.warning("NSE response missing expiryDates for symbol=%s — will derive", symbol)

    # ── Warn if standard records envelope is absent ───────────────────────
    if "records" not in raw_json:
        vr.add_warning(
            "NON_STANDARD_ENVELOPE",
            f"Top-level 'records' key absent; using fallback shape "
            f"(top-level keys: {list(raw_json.keys())})",
            "records",
        )
        logger.warning(
            "NSE non-standard envelope for symbol=%s keys=%s",
            symbol, list(raw_json.keys()),
        )

    vr._compute_corruption_score()
    return vr
