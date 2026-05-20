"""
Unit tests for the NSE fetch / parser layer.

Covers:
  - _detect_response_type()           : captcha, blocked, HTML, json, empty, unknown
  - _extract_nse_payload()            : all 4 NSE JSON shapes + derivation fallbacks
  - validate_nse_json_structure()     : relaxed validator — warnings vs errors
  - _parse_raw_chain()                : end-to-end parse from raw dict
  - NSEMalformedPayloadError          : no data rows at all
  - Retry escalation behaviour        : mocked via NSEOptionChainService

All tests are pure computation — no real HTTP calls, no database.
"""

from __future__ import annotations

import importlib.util
import sys
import os
import types
import json
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Stub heavy dependencies so modules can be imported without a Flask app
# ---------------------------------------------------------------------------

def _stub(name: str, **attrs):
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = []
        m.__package__ = name
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]

# Flask / SQLAlchemy stubs
_stub("flask")
_stub("flask_jwt_extended")
_stub("flask_bcrypt")
_stub("flask_sqlalchemy")
_stub("sqlalchemy")
_stub("sqlalchemy.orm")
_stub("app")
_stub("app.extensions")

# Monitor stub
_monitor_stub = MagicMock()
_stub("app.services.option_chain_monitor", monitor=_monitor_stub)

# ---------------------------------------------------------------------------
# Now import the modules under test
# ---------------------------------------------------------------------------

import importlib.util as _ilu

def _load(rel_path: str):
    base    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path    = os.path.join(base, *rel_path.split("/"))
    mod_name = rel_path.replace("/", ".").replace(".py", "")
    spec    = _ilu.spec_from_file_location(mod_name, path)
    mod     = _ilu.module_from_spec(spec)
    mod.__name__    = mod_name
    mod.__package__ = mod_name.rsplit(".", 1)[0]
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod

_validator = _load("app/services/option_chain_validator.py")
validate_raw_response     = _validator.validate_raw_response
validate_nse_json_structure = _validator.validate_nse_json_structure
validate_parsed_chain     = _validator.validate_parsed_chain

_svc = _load("app/services/nse_option_chain_service.py")
_detect_response_type   = _svc._detect_response_type
_extract_nse_payload    = _svc._extract_nse_payload
_parse_raw_chain        = _svc._parse_raw_chain
NSEMalformedPayloadError = _svc.NSEMalformedPayloadError
NSERetryExhaustedError  = _svc.NSERetryExhaustedError
NSECaptchaError         = _svc.NSECaptchaError
NSEDataError            = _svc.NSEDataError
NSEFetchError           = _svc.NSEFetchError
OptionChainResult       = _svc.OptionChainResult
NSEOptionChainService   = _svc.NSEOptionChainService


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_row(strike: float, expiry: str = "29-May-2025",
              ce_oi: int = 1000, pe_oi: int = 800,
              ce_ltp: float = 50.0, pe_ltp: float = 45.0) -> dict:
    return {
        "strikePrice": strike,
        "expiryDate":  expiry,
        "CE": {
            "openInterest":        ce_oi,
            "changeinOpenInterest": 100,
            "totalTradedVolume":    500,
            "impliedVolatility":    18.5,
            "lastPrice":            ce_ltp,
            "bidprice":             49.5,
            "askPrice":             50.5,
        },
        "PE": {
            "openInterest":        pe_oi,
            "changeinOpenInterest": -50,
            "totalTradedVolume":    400,
            "impliedVolatility":    20.0,
            "lastPrice":            pe_ltp,
            "bidprice":             44.5,
            "askPrice":             45.5,
        },
    }


def _standard_payload(expiry: str = "29-May-2025") -> dict:
    """Shape 1 — standard NSE response with records envelope."""
    rows = [_make_row(s, expiry) for s in [22000, 22100, 22200, 22300, 22400]]
    return {
        "records": {
            "underlyingValue": 22250.0,
            "expiryDates":     [expiry, "26-Jun-2025"],
            "data":            rows,
        },
        "filtered": {
            "underlyingValue": 22250.0,
            "data":            rows[1:4],
        },
    }


def _filtered_only_payload(expiry: str = "29-May-2025") -> dict:
    """Shape 2 — only filtered key, no records envelope."""
    rows = [_make_row(s, expiry) for s in [22100, 22200, 22300]]
    return {
        "filtered": {
            "underlyingValue": 22200.0,
            "expiryDates":     [expiry],
            "data":            rows,
        }
    }


def _toplevel_data_payload(expiry: str = "29-May-2025") -> dict:
    """Shape 3 — data at top level (rare alternate format)."""
    rows = [_make_row(s, expiry) for s in [22000, 22100, 22200, 22300, 22400]]
    return {
        "underlyingValue": 22250.0,
        "expiryDates":     [expiry],
        "data":            rows,
    }


def _partial_records_payload(expiry: str = "29-May-2025") -> dict:
    """Shape 4 — records.data present but underlyingValue / expiryDates absent."""
    rows = [_make_row(s, expiry) for s in [22000, 22100, 22200, 22300, 22400]]
    return {
        "records": {
            "data": rows,
            # underlyingValue and expiryDates deliberately absent
        }
    }


# ===========================================================================
# Tests: _detect_response_type
# ===========================================================================

class TestDetectResponseType:

    def test_json_brace(self):
        assert _detect_response_type('{"records": {}}', "application/json") == "json"

    def test_json_by_content_type(self):
        assert _detect_response_type('{"x": 1}', "application/json; charset=utf-8") == "json"

    def test_captcha_keyword(self):
        body = "<html><body>Please verify you are human</body></html>"
        assert _detect_response_type(body, "text/html") == "captcha"

    def test_captcha_keyword_case_insensitive(self):
        body = "<html>CAPTCHA required</html>"
        assert _detect_response_type(body, "text/html") == "captcha"

    def test_blocked_cloudflare(self):
        body = "<html><body>cloudflare protection active</body></html>"
        assert _detect_response_type(body, "text/html") == "blocked"

    def test_blocked_403(self):
        body = "<html>403 Forbidden</html>"
        assert _detect_response_type(body, "text/html") == "blocked"

    def test_html_page(self):
        body = "<!DOCTYPE html><html><head></head><body>NSE Down</body></html>"
        assert _detect_response_type(body, "text/html") == "html"

    def test_empty_body(self):
        assert _detect_response_type("", "application/json") == "empty"
        assert _detect_response_type("   \n\t  ", "application/json") == "empty"

    def test_unknown_body(self):
        assert _detect_response_type("random text here", "text/plain") == "unknown"


# ===========================================================================
# Tests: _extract_nse_payload
# ===========================================================================

class TestExtractNsePayload:

    def test_shape1_standard(self):
        raw = _standard_payload()
        payload = _extract_nse_payload(raw, "NIFTY")
        assert len(payload["data"]) == 5
        assert payload["underlyingValue"] == 22250.0
        assert "29-May-2025" in payload["expiryDates"]

    def test_shape2_filtered_only(self):
        raw = _filtered_only_payload()
        payload = _extract_nse_payload(raw, "NIFTY")
        assert len(payload["data"]) == 3
        assert payload["underlyingValue"] == 22200.0
        assert "29-May-2025" in payload["expiryDates"]

    def test_shape3_toplevel_data(self):
        raw = _toplevel_data_payload()
        payload = _extract_nse_payload(raw, "RELIANCE")
        assert len(payload["data"]) == 5
        assert payload["underlyingValue"] == 22250.0

    def test_shape4_partial_records_derives_expiry_dates(self):
        raw = _partial_records_payload()
        payload = _extract_nse_payload(raw, "NIFTY")
        assert len(payload["data"]) == 5
        # expiryDates should be derived from row expiryDate fields
        assert "29-May-2025" in payload["expiryDates"]

    def test_shape4_partial_records_derives_underlying_value(self):
        raw = _partial_records_payload()
        payload = _extract_nse_payload(raw, "NIFTY")
        # underlying should be non-zero (derived from CE/PE LTP)
        assert payload["underlyingValue"] != 0.0

    def test_raises_when_no_data_rows(self):
        raw = {"records": {"underlyingValue": 100.0, "expiryDates": ["29-May-2025"]}}
        try:
            _extract_nse_payload(raw, "TEST")
            assert False, "should have raised"
        except NSEMalformedPayloadError as exc:
            assert "TEST" in str(exc) or "no usable" in str(exc).lower()

    def test_raises_on_empty_dict(self):
        try:
            _extract_nse_payload({}, "EMPTY")
            assert False, "should have raised"
        except NSEMalformedPayloadError:
            pass

    def test_raises_on_captcha_html_parsed_as_dict(self):
        # If somehow a dict with no data rows slips through (edge case)
        raw = {"status": "captcha", "message": "blocked"}
        try:
            _extract_nse_payload(raw, "NIFTY")
            assert False, "should have raised"
        except NSEMalformedPayloadError:
            pass

    def test_derives_expiry_from_multiple_rows(self):
        rows = [
            _make_row(22000, "29-May-2025"),
            _make_row(22000, "26-Jun-2025"),
            _make_row(22100, "29-May-2025"),
        ]
        raw = {"records": {"data": rows}}
        payload = _extract_nse_payload(raw, "NIFTY")
        assert "29-May-2025" in payload["expiryDates"]
        assert "26-Jun-2025" in payload["expiryDates"]
        # Order should be insertion order (first seen)
        assert payload["expiryDates"][0] == "29-May-2025"


# ===========================================================================
# Tests: validate_nse_json_structure (relaxed)
# ===========================================================================

class TestValidateNseJsonStructure:

    def test_standard_payload_is_valid(self):
        vr = validate_nse_json_structure(_standard_payload(), "NIFTY")
        assert vr.is_valid

    def test_filtered_only_is_valid_with_warning(self):
        vr = validate_nse_json_structure(_filtered_only_payload(), "NIFTY")
        assert vr.is_valid
        # Should warn about non-standard envelope
        warning_codes = [w.code for w in vr.warnings]
        assert "NON_STANDARD_ENVELOPE" in warning_codes

    def test_toplevel_data_is_valid_with_warning(self):
        vr = validate_nse_json_structure(_toplevel_data_payload(), "RELIANCE")
        assert vr.is_valid

    def test_partial_records_warns_about_missing_fields(self):
        vr = validate_nse_json_structure(_partial_records_payload(), "NIFTY")
        assert vr.is_valid  # data rows are present — not an error
        warning_codes = [w.code for w in vr.warnings]
        assert "MISSING_UNDERLYING_VALUE" in warning_codes
        assert "MISSING_EXPIRY_DATES" in warning_codes

    def test_no_data_rows_anywhere_is_error(self):
        raw = {"records": {"underlyingValue": 100.0, "expiryDates": ["29-May-2025"]}}
        vr = validate_nse_json_structure(raw, "TEST")
        assert not vr.is_valid
        error_codes = [e.code for e in vr.errors]
        assert "NO_DATA_ROWS" in error_codes

    def test_empty_dict_is_error(self):
        vr = validate_nse_json_structure({}, "EMPTY")
        assert not vr.is_valid

    def test_non_dict_is_error(self):
        vr = validate_nse_json_structure([], "NIFTY")  # type: ignore
        assert not vr.is_valid

    def test_old_hard_error_key_absent_no_longer_blocks(self):
        """records key absent should NOT be a hard error if filtered.data is present."""
        raw = _filtered_only_payload()
        assert "records" not in raw
        vr = validate_nse_json_structure(raw, "NIFTY")
        assert vr.is_valid   # relaxed — filtered.data is present


# ===========================================================================
# Tests: _parse_raw_chain
# ===========================================================================

class TestParseRawChain:

    def test_standard_payload_parses_correctly(self):
        raw = _standard_payload("29-May-2025")
        result = _parse_raw_chain(raw, "NIFTY", None)
        assert isinstance(result, OptionChainResult)
        assert result.symbol == "NIFTY"
        assert result.expiry == "29-May-2025"
        assert len(result.strikes) == 5
        assert result.spot_price == 22250.0
        assert result.total_ce_oi > 0
        assert result.total_pe_oi > 0
        assert 0 < result.pcr < 10

    def test_filtered_only_payload_parses(self):
        raw = _filtered_only_payload("29-May-2025")
        result = _parse_raw_chain(raw, "NIFTY", None)
        assert len(result.strikes) == 3
        assert result.spot_price == 22200.0

    def test_partial_records_derives_expiry_and_spot(self):
        raw = _partial_records_payload("29-May-2025")
        result = _parse_raw_chain(raw, "NIFTY", None)
        assert result.expiry == "29-May-2025"
        assert result.spot_price > 0  # derived from CE/PE LTP

    def test_target_expiry_is_respected(self):
        rows_may = [_make_row(s, "29-May-2025") for s in [22000, 22100, 22200]]
        rows_jun = [_make_row(s, "26-Jun-2025") for s in [22000, 22100, 22200]]
        raw = {
            "records": {
                "underlyingValue": 22100.0,
                "expiryDates":     ["29-May-2025", "26-Jun-2025"],
                "data":            rows_may + rows_jun,
            }
        }
        result = _parse_raw_chain(raw, "NIFTY", "26-Jun-2025")
        assert result.expiry == "26-Jun-2025"
        assert len(result.strikes) == 3

    def test_invalid_target_expiry_falls_back_to_nearest(self):
        raw = _standard_payload("29-May-2025")
        result = _parse_raw_chain(raw, "NIFTY", "31-Dec-2099")  # invalid
        assert result.expiry == "29-May-2025"

    def test_raises_malformed_when_no_rows(self):
        raw = {"records": {"underlyingValue": 100.0, "expiryDates": ["29-May-2025"]}}
        try:
            _parse_raw_chain(raw, "TEST", None)
            assert False, "should have raised"
        except (NSEMalformedPayloadError, NSEDataError):
            pass

    def test_atm_strike_computed(self):
        raw = _standard_payload("29-May-2025")
        result = _parse_raw_chain(raw, "NIFTY", None)
        # spot is 22250; ATM should be 22200 or 22300 (closest)
        assert result.atm_strike in (22200, 22300)

    def test_pcr_computed(self):
        raw = _standard_payload("29-May-2025")
        result = _parse_raw_chain(raw, "NIFTY", None)
        expected_pcr = result.total_pe_oi / result.total_ce_oi
        assert abs(result.pcr - expected_pcr) < 0.01

    def test_strikes_sorted_ascending(self):
        rows = [_make_row(s, "29-May-2025") for s in [22400, 22000, 22200, 22100, 22300]]
        raw = {
            "records": {
                "underlyingValue": 22200.0,
                "expiryDates":     ["29-May-2025"],
                "data":            rows,
            }
        }
        result = _parse_raw_chain(raw, "NIFTY", None)
        vals = [r.strike for r in result.strikes]
        assert vals == sorted(vals)


# ===========================================================================
# Tests: malformed-but-recoverable payloads
# ===========================================================================

class TestMalformedButRecoverable:

    def test_missing_records_data_uses_filtered(self):
        """records key present but records.data absent — should use filtered.data."""
        expiry = "29-May-2025"
        rows = [_make_row(s, expiry) for s in [22100, 22200, 22300]]
        raw = {
            "records": {
                "underlyingValue": 22200.0,
                "expiryDates": [expiry],
                # data deliberately absent
            },
            "filtered": {
                "underlyingValue": 22200.0,
                "data": rows,
            },
        }
        result = _parse_raw_chain(raw, "NIFTY", None)
        assert len(result.strikes) == 3

    def test_underlying_value_zero_derives_from_legs(self):
        """underlyingValue=0 should trigger derivation from CE/PE LTP."""
        expiry = "29-May-2025"
        rows = [_make_row(22200, expiry, ce_ltp=100.0, pe_ltp=80.0)]
        raw = {
            "records": {
                "underlyingValue": 0,  # zero/absent
                "expiryDates": [expiry],
                "data": rows,
            }
        }
        payload = _extract_nse_payload(raw, "NIFTY")
        # Derived spot should be non-zero
        assert payload["underlyingValue"] != 0

    def test_rows_with_missing_ce_or_pe_are_skipped_gracefully(self):
        """Rows that have neither CE nor PE should not crash the parser."""
        expiry = "29-May-2025"
        rows = [
            _make_row(22000, expiry),
            {"strikePrice": 22050, "expiryDate": expiry},  # no CE or PE
            _make_row(22100, expiry),
            _make_row(22200, expiry),
        ]
        raw = {
            "records": {
                "underlyingValue": 22100.0,
                "expiryDates": [expiry],
                "data": rows,
            }
        }
        result = _parse_raw_chain(raw, "NIFTY", None)
        # Should parse 3 valid strikes (22050 row has strike=22050 but empty CE/PE)
        # The parser doesn't filter on CE/PE presence — it just uses 0 defaults
        assert len(result.strikes) >= 3

    def test_extra_unknown_top_level_keys_ignored(self):
        """Unknown envelope keys should not cause failures."""
        raw = _standard_payload()
        raw["someNewNSEKey"] = {"stuff": 123}
        raw["metadata"] = {"version": "2.1"}
        result = _parse_raw_chain(raw, "NIFTY", None)
        assert len(result.strikes) == 5


# ===========================================================================
# Tests: retry escalation (mocked service)
# ===========================================================================

class TestRetryEscalation:
    """
    Test that NSEOptionChainService.get_option_chain() correctly escalates
    through cookie-refresh → backoff → dump+raise on repeated malformed payloads.

    We mock _NSESession.get() to always return a no-data-rows payload.
    """

    def _make_service(self):
        svc = NSEOptionChainService.__new__(NSEOptionChainService)
        svc._http  = MagicMock()
        svc._cache = MagicMock()
        svc._cache.get.return_value = None  # always miss
        return svc

    def _malformed_raw(self):
        """Payload that passes JSON decode but has no data rows."""
        return {"records": {"underlyingValue": 100.0, "expiryDates": ["29-May-2025"]}}

    def test_retries_three_times_then_raises(self):
        svc = self._make_service()
        svc._http.get.return_value = self._malformed_raw()
        svc._http.force_cookie_refresh = MagicMock()

        try:
            with patch("time.sleep"):  # don't actually sleep
                svc.get_option_chain("NIFTY")
            assert False, "should have raised NSERetryExhaustedError"
        except (NSERetryExhaustedError, NSEMalformedPayloadError, NSEDataError):
            pass  # any of these is acceptable

        # HTTP get should have been called 3 times (one per parse attempt)
        assert svc._http.get.call_count == 3

    def test_cookie_refresh_called_on_first_failure(self):
        svc = self._make_service()
        svc._http.get.return_value = self._malformed_raw()
        svc._http.force_cookie_refresh = MagicMock()

        try:
            with patch("time.sleep"):
                svc.get_option_chain("NIFTY")
        except Exception:
            pass

        # force_cookie_refresh should be called at least once (after 1st failure)
        assert svc._http.force_cookie_refresh.call_count >= 1

    def test_succeeds_after_one_malformed_then_valid(self):
        """Second fetch returns valid data — should succeed without raising."""
        svc = self._make_service()
        malformed = self._malformed_raw()
        valid     = _standard_payload("29-May-2025")
        svc._http.get.side_effect = [malformed, valid]
        svc._http.force_cookie_refresh = MagicMock()
        svc._cache.set = MagicMock()

        with patch("time.sleep"):
            result = svc.get_option_chain("NIFTY")

        assert isinstance(result, OptionChainResult)
        assert len(result.strikes) == 5
        assert svc._http.get.call_count == 2

    def test_debug_dump_written_on_third_failure(self):
        """After 3 malformed payloads, _write_debug_dump should be called."""
        svc = self._make_service()
        svc._http.get.return_value = self._malformed_raw()
        svc._http.force_cookie_refresh = MagicMock()

        with patch("time.sleep"), \
             patch.object(_svc, "_write_debug_dump", return_value="/tmp/dump.txt") as mock_dump:
            try:
                svc.get_option_chain("NIFTY")
            except Exception:
                pass
            assert mock_dump.call_count >= 1


# ===========================================================================
# Tests: validate_raw_response (existing behaviour preserved)
# ===========================================================================

class TestValidateRawResponse:

    def test_valid_json_content_type(self):
        vr = validate_raw_response('{"records": {}}', "application/json")
        assert vr.is_valid

    def test_html_content_type_is_error(self):
        vr = validate_raw_response("<html>NSE Down</html>", "text/html")
        assert not vr.is_valid

    def test_captcha_body_is_error(self):
        vr = validate_raw_response(
            "<html>captcha required</html>", "text/html"
        )
        assert not vr.is_valid

    def test_empty_body_is_error(self):
        vr = validate_raw_response("", "application/json")
        assert not vr.is_valid
        codes = [e.code for e in vr.errors]
        assert "EMPTY_BODY" in codes

    def test_no_content_type_passes(self):
        """No content-type header should not trigger error."""
        vr = validate_raw_response('{"x": 1}', "")
        assert vr.is_valid
