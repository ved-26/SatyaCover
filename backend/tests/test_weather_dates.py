from datetime import date, timedelta
import unittest
from unittest.mock import patch

import requests
from fastapi import HTTPException
from pydantic import ValidationError

from app.main import (
    AssessmentRequest,
    _current_india_date,
    _validate_observation_dates,
    compare_rainfall_with_historical_baseline,
    get_weather,
    get_ndvi,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class WeatherAndDateTests(unittest.TestCase):
    def test_valid_cross_year_observation_dates(self):
        request = AssessmentRequest(
            latitude=18.5204,
            longitude=73.8567,
            start_date=date(2025, 12, 4),
            end_date=date(2026, 11, 6),
        )
        self.assertEqual(request.start_date, date(2025, 12, 4))
        self.assertEqual(request.end_date, date(2026, 11, 6))

    def test_future_end_date_rejected_by_request_and_date_guard(self):
        future = _current_india_date() + timedelta(days=1)
        with self.assertRaises(ValidationError) as request_error:
            AssessmentRequest(
                latitude=18.5,
                longitude=73.8,
                start_date=_current_india_date(),
                end_date=future,
            )
        self.assertIn("cannot be in the future", str(request_error.exception))
        with self.assertRaises(HTTPException) as guard_error:
            _validate_observation_dates(_current_india_date(), future)
        self.assertEqual(guard_error.exception.status_code, 400)
        self.assertIn("cannot be in the future", guard_error.exception.detail)
        with self.assertRaises(HTTPException) as weather_error:
            get_weather(18.5, 73.8, _current_india_date(), future)
        self.assertEqual(weather_error.exception.status_code, 400)
        with self.assertRaises(HTTPException) as satellite_error:
            get_ndvi(18.5, 73.8, _current_india_date(), future)
        self.assertEqual(satellite_error.exception.status_code, 400)

    def test_start_after_end_rejected(self):
        today = _current_india_date()
        with self.assertRaises(ValidationError):
            AssessmentRequest(
                latitude=18.5,
                longitude=73.8,
                start_date=today,
                end_date=today - timedelta(days=1),
            )

    def test_400_day_difference_allowed_and_401_rejected(self):
        today = _current_india_date()
        _validate_observation_dates(today - timedelta(days=400), today)
        with self.assertRaises(HTTPException) as error:
            _validate_observation_dates(today - timedelta(days=401), today)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("400 days", error.exception.detail)

    @patch("app.main.requests.get")
    def test_weather_success_parses_daily_precipitation_and_parameters(self, get):
        get.return_value = FakeResponse({
            "daily": {
                "time": ["2025-10-01", "2025-10-02"],
                "precipitation_sum": [0, 4.25],
                "temperature_2m_max": [30, 31],
                "temperature_2m_min": [20, 21],
            }
        })
        response = get_weather(
            18.5, 73.8, date(2025, 10, 1), date(2025, 10, 2)
        )
        self.assertEqual(response["status"], "SUCCESS")
        self.assertEqual(response["precipitation_days_available"], 2)
        self.assertEqual(response["daily"][1]["precipitation_mm"], 4.25)
        self.assertEqual(get.call_args.kwargs["params"]["start_date"], "2025-10-01")
        self.assertEqual(get.call_args.kwargs["params"]["end_date"], "2025-10-02")
        self.assertEqual(
            get.call_args.kwargs["params"]["daily"],
            "precipitation_sum,temperature_2m_max,temperature_2m_min",
        )

    @patch("app.main.requests.get")
    def test_partial_precipitation_is_not_marked_complete(self, get):
        get.return_value = FakeResponse({
            "daily": {
                "time": ["2025-10-01", "2025-10-02"],
                "precipitation_sum": [0, None],
            }
        })
        response = get_weather(
            18.5, 73.8, date(2025, 10, 1), date(2025, 10, 2)
        )
        self.assertEqual(response["status"], "PARTIAL")
        self.assertEqual(response["precipitation_days_available"], 1)

    @patch("app.main.requests.get", side_effect=requests.Timeout("offline"))
    def test_provider_failure_is_reported_as_unavailable_gateway_error(self, _get):
        with self.assertRaises(HTTPException) as error:
            get_weather(18.5, 73.8, date(2025, 10, 1), date(2025, 10, 2))
        self.assertEqual(error.exception.status_code, 502)

    @patch("app.main.get_weather")
    def test_cross_year_historical_periods_keep_matching_dates(self, get):
        def complete_weather(*, start_date, end_date, **_kwargs):
            days = (end_date - start_date).days + 1
            return {
                "status": "SUCCESS",
                "daily": [
                    {
                        "date": (start_date + timedelta(days=index)).isoformat(),
                        "precipitation_mm": 1.0,
                    }
                    for index in range(days)
                ],
            }

        get.side_effect = complete_weather
        result = compare_rainfall_with_historical_baseline(
            18.5,
            73.8,
            date(2025, 12, 4),
            date(2026, 11, 6),
            years=3,
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["years_available"], 3)
        self.assertEqual(result["periods"][0]["start_date"], "2024-12-04")
        self.assertEqual(result["periods"][0]["end_date"], "2025-11-06")


if __name__ == "__main__":
    unittest.main()
