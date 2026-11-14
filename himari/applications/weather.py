"""Live weather through Open-Meteo (no API key required).

The model never answers weather from memory: this module resolves a location,
fetches current conditions and a daily forecast, and returns data with its
timestamp and timezone. A configured location wins; otherwise Himari detects
one from the network only when the user enabled that.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from ..config import load

log = logging.getLogger("himari.applications.weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IP_LOOKUP_URLS = ("https://ipapi.co/json/", "https://ipwho.is/")
HTTP_TIMEOUT_SECONDS = 10.0
CACHE_TTL_SECONDS = 600

# WMO weather interpretation codes used by Open-Meteo.
WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherError(RuntimeError):
    pass


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float
    timezone: str = "auto"
    country: str = ""

    def to_dict(self):
        return {
            "name": self.name,
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "timezone": self.timezone,
            "country": self.country,
        }


_CACHE = {}


def _config():
    config = load()
    return config.get("location", {}) if isinstance(config, dict) else {}


def _units():
    units = str(_config().get("units") or "metric").casefold()
    return units if units in {"metric", "imperial"} else "metric"


def _format_number(value, digits=1):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _at(values, index):
    try:
        return values[index]
    except (IndexError, TypeError, KeyError):
        return None


def geocode(name):
    """Resolve a place name through Open-Meteo's geocoder."""
    query = str(name or "").strip()
    if not query:
        raise WeatherError("Tell me which city or place to use.")
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(
                GEOCODE_URL,
                params={"name": query, "count": 1, "language": "en", "format": "json"},
            )
    except httpx.HTTPError as exc:
        raise WeatherError(f"Could not reach the weather geocoder: {exc}") from exc
    if response.status_code != 200:
        raise WeatherError(f"The weather geocoder returned HTTP {response.status_code}.")
    try:
        results = response.json().get("results") or []
    except ValueError as exc:
        raise WeatherError("The weather geocoder returned unreadable data.") from exc
    if not results:
        raise WeatherError(f"Could not find a place named '{query}'.")
    first = results[0]
    return Location(
        name=str(first.get("name") or query),
        latitude=float(first["latitude"]),
        longitude=float(first["longitude"]),
        timezone=str(first.get("timezone") or "auto"),
        country=str(first.get("country") or ""),
    )


def detect_location():
    """Best-effort network location used only when the user allows it."""
    if not _config().get("auto_detect", True):
        raise WeatherError(
            "No location is configured and automatic detection is turned off. "
            "Tell me a city, or set one in Settings."
        )
    for url in IP_LOOKUP_URLS:
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = client.get(url)
            if response.status_code != 200:
                continue
            data = response.json()
        except (httpx.HTTPError, ValueError):
            continue
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        if latitude is None or longitude is None:
            continue
        city = str(data.get("city") or data.get("region") or "your location")
        return Location(
            name=city,
            latitude=float(latitude),
            longitude=float(longitude),
            timezone=str(data.get("timezone") or "auto"),
            country=str(data.get("country_name") or data.get("country") or ""),
        )
    raise WeatherError(
        "Could not detect a location from the network. Tell me a city, or set "
        "one in Settings."
    )


def resolve_location(name=None):
    """Pick the location to use: explicit name, configured, then detected."""
    explicit = str(name or "").strip()
    if explicit:
        return geocode(explicit)
    cfg = _config()
    if cfg.get("latitude") is not None and cfg.get("longitude") is not None:
        return Location(
            name=str(cfg.get("city") or "your location"),
            latitude=float(cfg["latitude"]),
            longitude=float(cfg["longitude"]),
            timezone=str(cfg.get("timezone") or "auto"),
            country="",
        )
    city = str(cfg.get("city") or "").strip()
    if city:
        return geocode(city)
    return detect_location()


def _describe(code):
    try:
        return WMO_CODES.get(int(code), f"Weather code {code}")
    except (TypeError, ValueError):
        return "Unknown conditions"


def forecast(days=3, location=None):
    """Return current conditions plus a daily forecast."""
    try:
        days = max(1, min(int(days), 14))
    except (TypeError, ValueError):
        days = 3
    units = _units()
    place = resolve_location(location)
    cache_key = (
        round(place.latitude, 3),
        round(place.longitude, 3),
        days,
        units,
    )
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    params = {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "current": ",".join(
            (
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation",
                "weather_code",
                "wind_speed_10m",
                "is_day",
            )
        ),
        "daily": ",".join(
            (
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "sunrise",
                "sunset",
            )
        ),
        "timezone": "auto",
        "forecast_days": days,
    }
    if units == "imperial":
        params.update(
            {
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
            }
        )
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(FORECAST_URL, params=params)
    except httpx.HTTPError as exc:
        raise WeatherError(f"Could not reach the weather service: {exc}") from exc
    if response.status_code != 200:
        raise WeatherError(f"The weather service returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise WeatherError("The weather service returned unreadable data.") from exc

    current_raw = payload.get("current") or {}
    daily_raw = payload.get("daily") or {}
    times = daily_raw.get("time") or []
    daily = []
    for index, date_text in enumerate(times):
        code = _at(daily_raw.get("weather_code"), index)
        daily.append(
            {
                "date": date_text,
                "weekday": _weekday(date_text),
                "condition": _describe(code),
                "code": code,
                "high": _format_number(_at(daily_raw.get("temperature_2m_max"), index)),
                "low": _format_number(_at(daily_raw.get("temperature_2m_min"), index)),
                "rain_probability": _at(daily_raw.get("precipitation_probability_max"), index),
                "sunrise": _at(daily_raw.get("sunrise"), index),
                "sunset": _at(daily_raw.get("sunset"), index),
            }
        )
    current = {
        "condition": _describe(current_raw.get("weather_code")),
        "code": current_raw.get("weather_code"),
        "temperature": _format_number(current_raw.get("temperature_2m")),
        "feels_like": _format_number(current_raw.get("apparent_temperature")),
        "humidity": current_raw.get("relative_humidity_2m"),
        "precipitation": _format_number(current_raw.get("precipitation"), 2),
        "wind_speed": _format_number(current_raw.get("wind_speed_10m")),
        "is_day": bool(current_raw.get("is_day")),
        "time": current_raw.get("time"),
    }
    result = {
        "ok": True,
        "location": place.to_dict(),
        "timezone": str(payload.get("timezone") or place.timezone),
        "units": units,
        "temperature_unit": "°F" if units == "imperial" else "°C",
        "wind_unit": "mph" if units == "imperial" else "km/h",
        "current": current,
        "daily": daily,
        "source": "Open-Meteo",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _CACHE[cache_key] = (time.time(), result)
    return result


def _weekday(date_text):
    try:
        return datetime.fromisoformat(str(date_text)).strftime("%A")
    except (TypeError, ValueError):
        return ""


def format_forecast(data, days=None):
    """Render a compact, model-friendly summary of forecast data."""
    location = data.get("location") or {}
    unit = data.get("temperature_unit") or "°C"
    wind_unit = data.get("wind_unit") or "km/h"
    current = data.get("current") or {}
    lines = [
        f"Location: {location.get('name')}"
        + (f", {location.get('country')}" if location.get("country") else "")
        + f" (timezone: {data.get('timezone') or location.get('timezone') or 'auto'})",
        (
            f"Now: {current.get('condition')}, {current.get('temperature')}{unit}"
            f" (feels like {current.get('feels_like')}{unit}), "
            f"humidity {current.get('humidity')}%, wind {current.get('wind_speed')} {wind_unit}"
        ),
    ]
    daily = data.get("daily") or []
    if days:
        daily = daily[: max(1, int(days))]
    for day in daily:
        lines.append(
            f"{day.get('weekday')} {day.get('date')}: {day.get('condition')}, "
            f"high {day.get('high')}{unit}, low {day.get('low')}{unit}, "
            f"rain chance {day.get('rain_probability')}%"
        )
    lines.append(f"Source: {data.get('source')} (fetched {data.get('fetched_at')})")
    return "\n".join(lines)
