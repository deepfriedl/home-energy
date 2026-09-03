"""Unit tests for Home Energy MCP server data normalization."""

import asyncio
from types import SimpleNamespace

from datetime import date, datetime, timezone

from home_energy.mcp.server import (
    AppContext,
    _appliance_summary,
    _bill_summary,
    _comparison,
    _hourly_usage_summary,
    _normalize_appliance_period,
    _normalize_appliance_usage,
    _serialize,
    get_fpl_account_status,
    get_fpl_appliance_summary,
    get_fpl_bill_summary,
    get_fpl_daily_summary,
    get_fpl_peak_hours,
    get_fpl_usage_comparison,
    get_fpl_usage_for_date,
    get_fpl_usage_range,
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


class FakeFplClient:
    """In-memory FPL data source for MCP tool tests."""

    def __init__(self) -> None:
        self.hourly_usage = {
            date(2026, 9, 1): [
                {"hour": "01", "kwh": 1.0, "billing_charge": 0.15},
                {"hour": "02", "kwh": 4.0, "billing_charge": 0.60},
                {"hour": "03", "kwh": 2.0, "billing_charge": 0.30},
            ],
            date(2026, 9, 2): [
                {"hour": "01", "kwh": 3.0, "billing_charge": 0.45},
                {"hour": "02", "kwh": 2.0, "billing_charge": 0.30},
            ],
        }

    async def get_hourly_usage(
        self, account: str, usage_date: date
    ) -> list[dict[str, object]]:
        return self.hourly_usage[usage_date]

    async def get_current_usage(
        self, account: str
    ) -> dict[str, object]:
        return {
            "bill_to_date": 42.50,
            "projected_bill": 90.00,
            "bill_to_date_kwh": 250.0,
            "projected_kwh": 500,
            "daily_average_kwh": 5.0,
            "daily_average_cost": 1.50,
            "bill_start_date": date(2026, 8, 20),
            "bill_end_date": date(2026, 9, 20),
            "as_of_days": 13,
            "remaining_days": 18,
            "service_days": 31,
            "latest_daily_usage": {
                "kwh_actual": 5.0,
                "billing_charge": 0.75,
                "read_time": datetime(2026, 9, 2, 0, 0),
            },
        }

    async def get_account_info(self, account: str) -> dict[str, object]:
        return {
            "premise": "900000001",
            "current_bill_date": date(2026, 8, 20),
            "next_bill_date": date(2026, 9, 20),
        }

    async def get_appliance_usage(self, account: str) -> dict[str, object]:
        return {
            "billPeriods": [
                {
                    "billPeriod": "1",
                    "startDate": "2026-08-20",
                    "endDate": "2026-09-20",
                    "billingDays": 31,
                    "kwh": 250,
                    "dollars": 42.50,
                    "categories": [
                        {
                            "category": "cooling",
                            "kwh2": 100.5,
                            "cost": 17.09,
                            "percentage2": 40.2,
                        },
                    ],
                },
                {
                    "billPeriod": "2",
                    "startDate": "2026-07-20",
                    "endDate": "2026-08-20",
                    "billingDays": 31,
                    "kwh": 200,
                    "dollars": 36.00,
                    "categories": [],
                },
            ],
        }


def _tool_context() -> SimpleNamespace:
    """Create a minimal MCP context backed by the fake FPL client."""
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=AppContext(
                fpl_client=FakeFplClient(),
                account="9000000010",
            ),
        ),
    )


def test_hourly_usage_summary_calculates_extremes() -> None:
    """Summaries include totals, average, peak, and lowest hour."""
    result = _hourly_usage_summary(
        date(2026, 9, 1),
        [
            {"hour": "01", "kwh": 1.0},
            {"hour": "02", "kwh": 4.0},
            {"hour": "03", "kwh": 2.0},
        ],
    )

    assert result["total_kwh"] == 7.0
    assert result["average_hourly_kwh"] == 7 / 3
    assert result["peak_hour"] == {"hour": "02", "kwh": 4.0}
    assert result["lowest_use_hour"] == {"hour": "01", "kwh": 1.0}


def test_appliance_summary_flattens_the_latest_period() -> None:
    """Appliance summaries omit raw nesting and keep category essentials."""
    result = _appliance_summary(asyncio.run(FakeFplClient().get_appliance_usage("a")))

    assert result["period"]["kwh"] == 250.0
    assert result["appliances"] == [
        {"name": "cooling", "kwh": 100.5, "cost": 17.09, "percentage": 40.2},
    ]


def test_bill_summary_is_compact_and_serialized() -> None:
    """Bill summaries retain only the requested billing metrics."""
    result = _bill_summary(asyncio.run(FakeFplClient().get_current_usage("a")))

    assert result == {
        "bill_to_date": 42.50,
        "projected_bill": 90.00,
        "bill_to_date_kwh": 250.0,
        "projected_kwh": 500,
        "daily_average_kwh": 5.0,
        "daily_average_cost": 1.50,
        "bill_start_date": "2026-08-20",
        "bill_end_date": "2026-09-20",
        "remaining_days": 18,
        "service_days": 31,
        "days_elapsed": 13,
    }


def test_comparison_calculates_deltas_and_percentages() -> None:
    """Comparisons consistently measure changes from first to second."""
    result = _comparison(
        {"total_kwh": 10.0, "total_cost": 2.0},
        {"total_kwh": 15.0, "total_cost": 3.0},
        "dates",
    )

    assert result["kwh_delta"] == 5.0
    assert result["kwh_percent_change"] == 50.0
    assert result["cost_delta"] == 1.0
    assert result["cost_percent_change"] == 50.0


def test_usage_for_date_returns_normalized_readings() -> None:
    """The date tool returns normalized hourly readings and totals."""
    result = asyncio.run(get_fpl_usage_for_date("2026-09-01", _tool_context()))

    assert result["date"] == "2026-09-01"
    assert result["reading_count"] == 3
    assert result["total_kwh"] == 7.0


def test_usage_range_aggregates_each_inclusive_day() -> None:
    """The range tool fetches and aggregates each requested day."""
    result = asyncio.run(get_fpl_usage_range("2026-09-01", "2026-09-02", _tool_context()))

    assert result["day_count"] == 2
    assert result["total_kwh"] == 12.0
    assert result["total_cost"] == 1.8


def test_peak_hours_returns_the_requested_highest_hours() -> None:
    """The peak-hours tool orders readings by descending kWh."""
    result = asyncio.run(get_fpl_peak_hours("2026-09-01", 2, _tool_context()))

    assert [row["hour"] for row in result["peak_hours"]] == ["02", "03"]


def test_daily_summary_includes_billing_and_hourly_context() -> None:
    """The daily summary compares usage to the billing-cycle average."""
    result = asyncio.run(get_fpl_daily_summary(_tool_context()))

    assert result["date"] == "2026-09-02"
    assert result["kwh"] == 5.0
    assert result["kwh_vs_billing_cycle_daily_average"] == 0.0
    assert result["peak_hour"]["hour"] == "01"


def test_appliance_summary_tool_returns_compact_categories() -> None:
    """The appliance-summary tool exposes the flattened appliance list."""
    result = asyncio.run(get_fpl_appliance_summary(_tool_context()))

    assert result["appliances"][0]["name"] == "cooling"


def test_bill_summary_tool_returns_projected_bill_data() -> None:
    """The bill-summary tool delegates to the compact bill response."""
    result = asyncio.run(get_fpl_bill_summary(_tool_context()))

    assert result["projected_bill"] == 90.0
    assert result["days_elapsed"] == 13


def test_account_status_confirms_account_and_latest_data() -> None:
    """The status tool reports the selected account and data availability."""
    result = asyncio.run(get_fpl_account_status(_tool_context()))

    assert result["authentication"] == "authenticated"
    assert result["premise_available"] is True
    assert result["latest_data_date"] == "2026-09-02"


def test_usage_comparison_supports_dates_and_billing_periods() -> None:
    """The comparison tool supports both requested comparison modes."""
    date_result = asyncio.run(
        get_fpl_usage_comparison("2026-09-01", "2026-09-02", "dates", _tool_context())
    )
    period_result = asyncio.run(
        get_fpl_usage_comparison("2", "1", "billing_periods", _tool_context())
    )

    assert date_result["kwh_delta"] == -2.0
    assert period_result["kwh_delta"] == 50.0
    assert round(period_result["cost_percent_change"], 6) == 18.055556
