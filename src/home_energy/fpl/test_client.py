"""Unit tests for the FPL client."""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from home_energy.fpl.client import (
    FplClient,
    FplClientError,
)


def make_response(
    payload: dict,
    status: int = 200,
) -> MagicMock:
    """Create a mocked aiohttp response."""
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=payload)
    response.text = AsyncMock(return_value="")
    return response


def make_session(
    responses: list[MagicMock],
) -> MagicMock:
    """Create a mocked aiohttp session with a shared response queue."""
    session = MagicMock()

    context_managers = []

    for response in responses:
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(
            return_value=response
        )
        context_manager.__aexit__ = AsyncMock(
            return_value=None
        )
        context_managers.append(context_manager)

    response_queue = iter(context_managers)

    def next_response(*args, **kwargs):
        return next(response_queue)

    session.get.side_effect = next_response
    session.post.side_effect = next_response

    session.closed = False

    return session


@pytest.fixture
def client() -> FplClient:
    """Create an FPL client with test credentials."""
    return FplClient(
        username="test@example.com",
        password="test-password",
    )


@pytest.mark.anyio
async def test_get_current_usage_parses_complete_response(
    client: FplClient,
) -> None:
    """Parse a complete current-usage response."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "meterSerialNo": "87654321",
            "meterNo": "TEST-METER-01",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    energy_usage_payload = {
        "data": {
            "CurrentUsage": {
                "projectedKWH": "1414",
                "dailyAverageKWH": "47.0",
                "billToDate": "98.87",
                "projectedBill": "195.59",
                "dailyAvg": "6.18",
                "avgHighTemp": "96",
                "billToDateKWH": "754.0",
                "recMtrReading": "0",
                "delMtrReading": "33174",
                "billStartDate": "08-17-2026",
                "billEndDate": "09-16-2026",
            },
            "DailyUsage": {
                "endDate": "09-01-2026",
                "data": [
                    {
                        "date": "08-31-2026",
                        "readTime": "2026-08-31T00:00:00-04:00",
                        "kwhActual": "41.25",
                        "billingCharge": "5.48",
                        "reading": "33851.1157",
                        "netDeliveredKwh": "0.0",
                        "netDeliveredReading": "0.0",
                    },
                    {
                        "date": "09-01-2026",
                        "readTime": "2026-09-01T00:00:00-04:00",
                        "kwhActual": "38.92",
                        "billingCharge": "5.17",
                        "reading": "33890.0357",
                        "netDeliveredKwh": "0.0",
                        "netDeliveredReading": "0.0",
                    },
                ],
            },
        },
    }

    account_response = make_response(account_info_payload)
    energy_response = make_response(energy_usage_payload)

    client.session = make_session(
        [
            account_response,
            energy_response,
        ]
    )
    client.jwt_token = "test-jwt"

    result = await client.get_current_usage(
        "900000001"
    )

    assert result["premise"] == "000555001"
    assert result["meter_serial_number"] == "87654321"
    assert result["meter_number"] == "TEST-METER-01"

    assert result["current_bill_date"] == date(
        2026,
        8,
        17,
    )
    assert result["next_bill_date"] == date(
        2026,
        9,
        16,
    )

    assert result["service_days"] == 30
    assert result["as_of_days"] >= 0
    assert result["remaining_days"] >= 0

    assert result["projected_kwh"] == 1414
    assert result["daily_average_kwh"] == 47.0
    assert result["bill_to_date"] == 98.87
    assert result["projected_bill"] == 195.59
    assert result["daily_average_cost"] == 6.18
    assert result["average_high_temperature"] == 96
    assert result["bill_to_date_kwh"] == 754.0

    assert result["received_meter_reading"] == 0
    assert result["delivered_meter_reading"] == 33174

    assert result["bill_start_date"] == date(
        2026,
        8,
        17,
    )
    assert result["bill_end_date"] == date(
        2026,
        9,
        16,
    )

    assert result["latest_daily_usage"] == {
        "kwh_actual": 38.92,
        "billing_charge": 5.17,
        "read_time": datetime.fromisoformat(
            "2026-09-01T00:00:00-04:00"
        ),
        "reading": 33890.0357,
        "net_delivered_kwh": 0.0,
        "net_delivered_reading": 0.0,
    }


@pytest.mark.anyio
async def test_get_current_usage_selects_end_date_reading(
    client: FplClient,
) -> None:
    """Select the daily reading matching DailyUsage.endDate."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "meterNo": "TEST-METER-01",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    energy_usage_payload = {
        "data": {
            "CurrentUsage": {},
            "DailyUsage": {
                "endDate": "09-01-2026",
                "data": [
                    {
                        "date": "08-30-2026",
                        "readTime": "2026-08-30T00:00:00-04:00",
                        "kwhActual": "35.00",
                        "billingCharge": "4.50",
                        "reading": "33810.0",
                    },
                    {
                        "date": "09-01-2026",
                        "readTime": "2026-09-01T00:00:00-04:00",
                        "kwhActual": "38.92",
                        "billingCharge": "5.17",
                        "reading": "33890.0357",
                    },
                    {
                        "date": "08-31-2026",
                        "readTime": "2026-08-31T00:00:00-04:00",
                        "kwhActual": "41.25",
                        "billingCharge": "5.48",
                        "reading": "33851.1157",
                    },
                ],
            },
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
            make_response(energy_usage_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    result = await client.get_current_usage(
        "900000001"
    )

    assert result["latest_daily_usage"]["kwh_actual"] == 38.92
    assert result["latest_daily_usage"]["read_time"] == (
        datetime.fromisoformat(
            "2026-09-01T00:00:00-04:00"
        )
    )


@pytest.mark.anyio
async def test_get_current_usage_falls_back_to_last_daily_reading(
    client: FplClient,
) -> None:
    """Use the final daily reading when endDate is unavailable."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "meterNo": "TEST-METER-01",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    energy_usage_payload = {
        "data": {
            "CurrentUsage": {},
            "DailyUsage": {
                "data": [
                    {
                        "date": "08-31-2026",
                        "readTime": "2026-08-31T00:00:00-04:00",
                        "kwhActual": "41.25",
                        "billingCharge": "5.48",
                        "reading": "33851.1157",
                    },
                    {
                        "date": "09-01-2026",
                        "readTime": "2026-09-01T00:00:00-04:00",
                        "kwhActual": "38.92",
                        "billingCharge": "5.17",
                        "reading": "33890.0357",
                    },
                ],
            },
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
            make_response(energy_usage_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    result = await client.get_current_usage(
        "900000001"
    )

    assert result["latest_daily_usage"]["kwh_actual"] == 38.92


@pytest.mark.anyio
async def test_get_current_usage_ignores_failed_current_usage(
    client: FplClient,
) -> None:
    """Ignore CurrentUsage when FPL reports a failed request."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "meterNo": "TEST-METER-01",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    energy_usage_payload = {
        "data": {
            "CurrentUsage": {
                "exceptionDetails": {
                    "requestStatus": "Failed",
                },
                "projectedKWH": "9999",
                "billToDateKWH": "9999",
            },
            "DailyUsage": {},
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
            make_response(energy_usage_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    result = await client.get_current_usage(
        "900000001"
    )

    assert "projected_kwh" not in result
    assert "bill_to_date_kwh" not in result
    assert "latest_daily_usage" not in result


@pytest.mark.anyio
async def test_get_current_usage_ignores_failed_daily_usage(
    client: FplClient,
) -> None:
    """Ignore DailyUsage when FPL reports a failed request."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "meterNo": "TEST-METER-01",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    energy_usage_payload = {
        "data": {
            "CurrentUsage": {
                "projectedKWH": "1414",
            },
            "DailyUsage": {
                "exceptionDetails": {
                    "requestStatus": "Failed",
                },
                "endDate": "09-01-2026",
                "data": [
                    {
                        "date": "09-01-2026",
                        "readTime": "2026-09-01T00:00:00-04:00",
                        "kwhActual": "38.92",
                        "billingCharge": "5.17",
                        "reading": "33890.0357",
                    },
                ],
            },
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
            make_response(energy_usage_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    result = await client.get_current_usage(
        "900000001"
    )

    assert result["projected_kwh"] == 1414
    assert "latest_daily_usage" not in result


@pytest.mark.anyio
async def test_get_current_usage_requires_premise(
    client: FplClient,
) -> None:
    """Raise an error when FPL does not provide a premise."""
    account_info_payload = {
        "data": {
            "meterNo": "TEST-METER-01",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    with pytest.raises(
        FplClientError,
        match="premise number",
    ):
        await client.get_current_usage(
            "900000001"
        )


@pytest.mark.anyio
async def test_get_current_usage_requires_meter_number(
    client: FplClient,
) -> None:
    """Raise an error when FPL does not provide a meter number."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    with pytest.raises(
        FplClientError,
        match="meter number",
    ):
        await client.get_current_usage(
            "900000001"
        )


@pytest.mark.anyio
async def test_get_current_usage_requires_bill_date(
    client: FplClient,
) -> None:
    """Raise an error when FPL does not provide the current bill date."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "meterNo": "TEST-METER-01",
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    with pytest.raises(
        FplClientError,
        match="current bill date",
    ):
        await client.get_current_usage(
            "900000001"
        )


@pytest.mark.anyio
async def test_get_current_usage_handles_missing_optional_values(
    client: FplClient,
) -> None:
    """Handle a response containing only required current-usage data."""
    account_info_payload = {
        "data": {
            "premiseNumber": "555001",
            "meterNo": "TEST-METER-01",
            "currentBillDate": "2026-08-17T00:00:00",
            "nextBillDate": "2026-09-16T00:00:00",
        },
    }

    energy_usage_payload = {
        "data": {
            "CurrentUsage": {
                "projectedKWH": "1414",
            },
            "DailyUsage": {},
        },
    }

    client.session = make_session(
        [
            make_response(account_info_payload),
            make_response(energy_usage_payload),
        ]
    )
    client.jwt_token = "test-jwt"

    result = await client.get_current_usage(
        "900000001"
    )

    assert result["projected_kwh"] == 1414
    assert "daily_average_kwh" not in result
    assert "projected_bill" not in result
    assert "latest_daily_usage" not in result