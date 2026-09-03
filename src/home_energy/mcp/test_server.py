"""Unit tests for Home Energy MCP server data normalization."""

from datetime import date, datetime, timezone

from home_energy.mcp.server import (
    _normalize_appliance_period,
    _normalize_appliance_usage,
    _serialize,
)


def test_serialize_date() -> None:
    """Serialize a date to an ISO-formatted string."""
    value = date(2026, 9, 2)

    assert _serialize(value) == "2026-09-02"


def test_serialize_datetime() -> None:
    """Serialize a datetime to an ISO-formatted string."""
    value = datetime(
        2026,
        9,
        2,
        14,
        30,
        tzinfo=timezone.utc,
    )

    assert _serialize(value) == "2026-09-02T14:30:00+00:00"


def test_serialize_nested_values() -> None:
    """Serialize dates and datetimes inside nested structures."""
    value = {
        "date": date(2026, 9, 2),
        "nested": {
            "timestamp": datetime(
                2026,
                9,
                2,
                14,
                30,
                tzinfo=timezone.utc,
            ),
        },
        "items": [
            date(2026, 9, 1),
            {
                "value": datetime(
                    2026,
                    9,
                    1,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            },
        ],
    }

    assert _serialize(value) == {
        "date": "2026-09-02",
        "nested": {
            "timestamp": "2026-09-02T14:30:00+00:00",
        },
        "items": [
            "2026-09-01",
            {
                "value": "2026-09-01T12:00:00+00:00",
            },
        ],
    }


def test_serialize_preserves_other_values() -> None:
    """Serialize should leave ordinary JSON-compatible values unchanged."""
    value = {
        "string": "hello",
        "integer": 42,
        "float": 3.14,
        "boolean": True,
        "none": None,
    }

    assert _serialize(value) == value


def test_normalize_appliance_period() -> None:
    """Normalize one FPL appliance billing period."""
    period = {
        "startDate": "2026-07-16",
        "endDate": "2026-08-17",
        "billingDays": 30,
        "kwh": 1639,
        "dollars": 262.54,
        "categories": [
            {
                "category": "cooling",
                "kwh": 810,
                "kwh2": 809.77,
                "cost": 129.71,
                "percentage": 49,
                "percentage2": 49.41,
            },
        ],
    }

    result = _normalize_appliance_period(period)

    assert result == {
        "start_date": "2026-07-16",
        "end_date": "2026-08-17",
        "billing_days": 30,
        "kwh": 1639.0,
        "cost": 262.54,
        "categories": [
            {
                "category": "cooling",
                "kwh": 810,
                "kwh2": 809.77,
                "cost": 129.71,
                "percentage": 49,
                "percentage2": 49.41,
            },
        ],
    }


def test_normalize_appliance_period_handles_missing_optional_values() -> None:
    """Normalize a period when optional values are missing."""
    period = {
        "startDate": "2026-07-16",
        "endDate": "2026-08-17",
        "categories": [],
    }

    result = _normalize_appliance_period(period)

    assert result == {
        "start_date": "2026-07-16",
        "end_date": "2026-08-17",
        "billing_days": None,
        "kwh": None,
        "cost": None,
        "categories": [],
    }


def test_normalize_appliance_usage_selects_bill_period_one() -> None:
    """Select billPeriod 1 as the latest billing period."""
    data = {
        "billPeriods": [
            {
                "billPeriod": "3",
                "startDate": "2026-05-15",
                "endDate": "2026-06-16",
                "billingDays": 30,
                "kwh": 1463,
                "dollars": 233.23,
                "categories": [],
            },
            {
                "billPeriod": "2",
                "startDate": "2026-06-16",
                "endDate": "2026-07-16",
                "billingDays": 30,
                "kwh": 1534,
                "dollars": 245.06,
                "categories": [],
            },
            {
                "billPeriod": "1",
                "startDate": "2026-07-16",
                "endDate": "2026-08-17",
                "billingDays": 30,
                "kwh": 1639,
                "dollars": 262.54,
                "categories": [],
            },
        ],
    }

    result = _normalize_appliance_usage(data)

    assert result["latest_period"] == {
        "start_date": "2026-07-16",
        "end_date": "2026-08-17",
        "billing_days": 30,
        "kwh": 1639.0,
        "cost": 262.54,
        "categories": [],
    }

    assert len(result["historical_periods"]) == 2

    assert result["historical_periods"][0]["start_date"] == (
        "2026-05-15"
    )
    assert result["historical_periods"][1]["start_date"] == (
        "2026-06-16"
    )


def test_normalize_appliance_usage_accepts_numeric_bill_period() -> None:
    """Accept numeric billPeriod values as well as strings."""
    data = {
        "billPeriods": [
            {
                "billPeriod": 1,
                "startDate": "2026-07-16",
                "endDate": "2026-08-17",
                "billingDays": 30,
                "kwh": 1639,
                "dollars": 262.54,
                "categories": [],
            },
        ],
    }

    result = _normalize_appliance_usage(data)

    assert result["latest_period"]["kwh"] == 1639.0
    assert result["historical_periods"] == []


def test_normalize_appliance_usage_falls_back_to_first_period() -> None:
    """Use the first period when FPL does not identify billPeriod 1."""
    data = {
        "billPeriods": [
            {
                "billPeriod": "2",
                "startDate": "2026-06-16",
                "endDate": "2026-07-16",
                "billingDays": 30,
                "kwh": 1534,
                "dollars": 245.06,
                "categories": [],
            },
            {
                "billPeriod": "3",
                "startDate": "2026-05-15",
                "endDate": "2026-06-16",
                "billingDays": 30,
                "kwh": 1463,
                "dollars": 233.23,
                "categories": [],
            },
        ],
    }

    result = _normalize_appliance_usage(data)

    assert result["latest_period"]["start_date"] == (
        "2026-06-16"
    )
    assert len(result["historical_periods"]) == 1
    assert result["historical_periods"][0]["start_date"] == (
        "2026-05-15"
    )


def test_normalize_appliance_usage_handles_empty_periods() -> None:
    """Return empty results when FPL provides no billing periods."""
    result = _normalize_appliance_usage(
        {
            "billPeriods": [],
        }
    )

    assert result == {
        "latest_period": None,
        "historical_periods": [],
    }


def test_normalize_appliance_usage_handles_missing_periods() -> None:
    """Return empty results when billPeriods is absent."""
    result = _normalize_appliance_usage({})

    assert result == {
        "latest_period": None,
        "historical_periods": [],
    }


def test_normalize_appliance_usage_preserves_secondary_values() -> None:
    """Preserve FPL's kwh2 and percentage2 values."""
    data = {
        "billPeriods": [
            {
                "billPeriod": "1",
                "startDate": "2026-07-16",
                "endDate": "2026-08-17",
                "billingDays": 30,
                "kwh": 1639,
                "dollars": 262.54,
                "categories": [
                    {
                        "category": "cooling",
                        "kwh": 810,
                        "kwh2": 809.77,
                        "cost": 129.71,
                        "percentage": 49,
                        "percentage2": 49.41,
                    },
                ],
            },
        ],
    }

    result = _normalize_appliance_usage(data)

    category = result["latest_period"]["categories"][0]

    assert category["kwh"] == 810
    assert category["kwh2"] == 809.77
    assert category["percentage"] == 49
    assert category["percentage2"] == 49.41


def test_normalize_appliance_usage_preserves_fpl_category_data() -> None:
    """Preserve FPL categories without merging or interpreting them."""
    data = {
        "billPeriods": [
            {
                "billPeriod": "1",
                "startDate": "2026-07-16",
                "endDate": "2026-08-17",
                "billingDays": 30,
                "kwh": 1639,
                "dollars": 262.54,
                "categories": [
                    {
                        "category": "other",
                        "kwh": 91,
                        "kwh2": 90.84,
                        "cost": 14.48,
                        "percentage": 6,
                        "percentage2": 6.21,
                    },
                    {
                        "category": "misc",
                        "kwh": 91,
                        "kwh2": 90.84,
                        "cost": 14.48,
                        "percentage": 6,
                        "percentage2": 6.21,
                    },
                ],
            },
        ],
    }

    result = _normalize_appliance_usage(data)

    categories = result["latest_period"]["categories"]

    assert len(categories) == 2
    assert categories[0]["category"] == "other"
    assert categories[1]["category"] == "misc"
    assert categories[0]["kwh"] == categories[1]["kwh"]
    assert categories[0]["kwh2"] == categories[1]["kwh2"]