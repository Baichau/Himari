from unittest.mock import Mock

import pytest

from himari.applications import weather


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, params=None):
        self.requests.append((url, params))
        response = Mock(status_code=200)
        response.json.return_value = self._responses.pop(0)
        return response


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    weather._CACHE.clear()
    monkeypatch.setattr(weather, "load", lambda: {"location": {}})
    yield
    weather._CACHE.clear()


def test_geocode_resolves_the_first_result(monkeypatch):
    client = FakeClient([
        {
            "results": [
                {
                    "name": "Berlin",
                    "latitude": 52.52,
                    "longitude": 13.41,
                    "timezone": "Europe/Berlin",
                    "country": "Germany",
                }
            ]
        }
    ])
    monkeypatch.setattr(weather.httpx, "Client", Mock(return_value=client))

    place = weather.geocode("Berlin")

    assert place.name == "Berlin"
    assert place.latitude == pytest.approx(52.52)
    assert place.country == "Germany"


def test_geocode_rejects_unknown_places(monkeypatch):
    client = FakeClient([{"results": []}])
    monkeypatch.setattr(weather.httpx, "Client", Mock(return_value=client))
    with pytest.raises(weather.WeatherError):
        weather.geocode("Nowhereland")


def test_forecast_uses_configured_location_and_formats_days(monkeypatch):
    monkeypatch.setattr(
        weather,
        "load",
        lambda: {
            "location": {
                "city": "Berlin",
                "latitude": 52.52,
                "longitude": 13.41,
                "units": "metric",
            }
        },
    )
    client = FakeClient([
        {
            "timezone": "Europe/Berlin",
            "current": {
                "time": "2026-11-13T12:00",
                "temperature_2m": 8.4,
                "relative_humidity_2m": 70,
                "apparent_temperature": 6.1,
                "precipitation": 0,
                "weather_code": 3,
                "wind_speed_10m": 12.5,
                "is_day": 1,
            },
            "daily": {
                "time": ["2026-11-13", "2026-11-14"],
                "weather_code": [3, 61],
                "temperature_2m_max": [10.2, 9.0],
                "temperature_2m_min": [4.1, 3.2],
                "precipitation_probability_max": [20, 80],
                "sunrise": ["2026-11-13T07:20", "2026-11-14T07:22"],
                "sunset": ["2026-11-13T16:20", "2026-11-14T16:18"],
            },
        }
    ])
    monkeypatch.setattr(weather.httpx, "Client", Mock(return_value=client))

    data = weather.forecast(days=2)

    assert data["ok"] is True
    assert data["location"]["name"] == "Berlin"
    assert data["temperature_unit"] == "°C"
    assert data["current"]["temperature"] == pytest.approx(8.4)
    assert data["daily"][0]["condition"] == "Overcast"
    assert data["daily"][1]["rain_probability"] == 80
    assert data["fetched_at"]


def test_forecast_refuses_to_detect_when_disabled(monkeypatch):
    monkeypatch.setattr(
        weather, "load", lambda: {"location": {"auto_detect": False}}
    )
    with pytest.raises(weather.WeatherError, match="automatic detection"):
        weather.resolve_location()


def test_forecast_cache_avoids_a_second_request(monkeypatch):
    monkeypatch.setattr(
        weather,
        "load",
        lambda: {"location": {"latitude": 1.0, "longitude": 2.0, "units": "metric"}},
    )
    client = FakeClient([
        {"timezone": "UTC", "current": {}, "daily": {"time": []}},
        {"timezone": "UTC", "current": {}, "daily": {"time": []}},
    ])
    monkeypatch.setattr(weather.httpx, "Client", Mock(return_value=client))

    weather.forecast(days=1)
    weather.forecast(days=1)

    assert len(client.requests) == 1


def test_imperial_units_are_applied(monkeypatch):
    monkeypatch.setattr(
        weather,
        "load",
        lambda: {
            "location": {
                "latitude": 1.0,
                "longitude": 2.0,
                "units": "imperial",
                "city": "Test",
            }
        },
    )
    client = FakeClient([{"timezone": "UTC", "current": {}, "daily": {"time": []}}])
    monkeypatch.setattr(weather.httpx, "Client", Mock(return_value=client))

    data = weather.forecast(days=1)

    assert data["temperature_unit"] == "°F"
    assert data["wind_unit"] == "mph"
    assert client.requests[0][1]["temperature_unit"] == "fahrenheit"


def test_forecast_formatting_includes_source_and_rain():
    text = weather.format_forecast({
        "location": {"name": "Berlin", "country": "Germany"},
        "timezone": "Europe/Berlin",
        "temperature_unit": "°C",
        "wind_unit": "km/h",
        "current": {
            "condition": "Overcast", "temperature": 8.4, "feels_like": 6.1,
            "humidity": 70, "wind_speed": 12.5,
        },
        "daily": [{
            "weekday": "Friday", "date": "2026-11-13", "condition": "Overcast",
            "high": 10.2, "low": 4.1, "rain_probability": 20,
        }],
        "source": "Open-Meteo",
        "fetched_at": "2026-11-13T12:00:00+01:00",
    })
    assert "Berlin" in text
    assert "rain chance 20%" in text
    assert "Open-Meteo" in text
