"""Multi-modal travel search: Travelpayouts API for flights, web search for ground transport."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

LOGGER = logging.getLogger(__name__)

_AVIASALES_BASE = "https://api.travelpayouts.com"
_AVIASALES_SEARCH = "https://www.aviasales.com/search"

IATA_MAP: dict[str, str] = {
    "yerevan": "EVN", "geneva": "GVA", "istanbul": "IST", "tbilisi": "TBS",
    "moscow": "MOW", "saint petersburg": "LED", "dubai": "DXB", "vienna": "VIE",
    "athens": "ATH", "warsaw": "WAW", "paris": "CDG", "london": "LON",
    "berlin": "BER", "rome": "ROM", "barcelona": "BCN", "madrid": "MAD",
    "amsterdam": "AMS", "prague": "PRG", "budapest": "BUD", "sofia": "SOF",
    "bucharest": "BUH", "belgrade": "BEG", "zagreb": "ZAG", "milan": "MIL",
    "munich": "MUC", "zurich": "ZRH", "antalya": "AYT", "batumi": "BUS",
    "kutaisi": "KUT", "baku": "GYD", "cairo": "CAI", "tel aviv": "TLV",
    "new york": "NYC", "los angeles": "LAX", "chicago": "ORD", "tokyo": "TYO",
    "bangkok": "BKK", "singapore": "SIN", "hong kong": "HKG", "beijing": "BJS",
    "shanghai": "SHA", "delhi": "DEL", "mumbai": "BOM", "doha": "DOH",
    "riyadh": "RUH", "minsk": "MSQ", "kyiv": "IEV", "riga": "RIX",
    "tallinn": "TLL", "vilnius": "VNO", "helsinki": "HEL", "stockholm": "STO",
    "oslo": "OSL", "copenhagen": "CPH", "lisbon": "LIS", "porto": "OPO",
    "nice": "NCE", "lyon": "LYS", "frankfurt": "FRA", "dusseldorf": "DUS",
    "hamburg": "HAM", "larnaca": "LCA", "Tehran": "THR",
}


class TravelTool:
    """Searches flights via Travelpayouts (real cached prices, free API)."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    @property
    def available(self) -> bool:
        return bool(self._token)

    def resolve_iata(self, city: str) -> str | None:
        """Resolve a city name to IATA code. Returns None if unknown."""
        key = city.strip().lower()
        if key in IATA_MAP:
            return IATA_MAP[key]
        if len(key) == 3 and key.isalpha():
            return key.upper()
        return None

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str | None = None,
        currency: str = "USD",
        limit: int = 5,
        one_way: bool = True,
    ) -> list[dict]:
        """Search flights via /aviasales/v3/prices_for_dates.

        Returns list of dicts with: price, airline, duration_min, transfers,
        departure_at, link, origin, destination.
        """
        if not self._token:
            return []

        origin_iata = self.resolve_iata(origin)
        dest_iata = self.resolve_iata(destination)
        if not origin_iata or not dest_iata:
            LOGGER.warning("Cannot resolve IATA: %s -> %s", origin, destination)
            return []

        params: dict[str, str] = {
            "origin": origin_iata,
            "destination": dest_iata,
            "sorting": "price",
            "direct": "false",
            "cy": currency.lower(),
            "currency": currency.lower(),
            "limit": str(limit),
            "page": "1",
            "one_way": "true" if one_way else "false",
            "token": self._token,
        }
        if departure_date:
            params["departure_at"] = self._normalize_date(departure_date)

        url = f"{_AVIASALES_BASE}/aviasales/v3/prices_for_dates?{urllib.parse.urlencode(params)}"

        data = self._get_json(url)
        if not data or not data.get("success"):
            return []

        results: list[dict] = []
        for ticket in data.get("data", [])[:limit]:
            dur = ticket.get("duration") or ticket.get("duration_to") or 0
            booking_link = ""
            if ticket.get("link"):
                raw_link = ticket["link"].lstrip("/")
                booking_link = f"https://www.aviasales.com/{raw_link}"

            results.append({
                "price": ticket.get("price", 0),
                "currency": data.get("currency", currency).upper(),
                "airline": ticket.get("airline", ""),
                "flight_number": ticket.get("flight_number", ""),
                "transfers": ticket.get("transfers", 0),
                "duration_min": dur,
                "departure_at": ticket.get("departure_at", ""),
                "origin": ticket.get("origin", origin_iata),
                "origin_airport": ticket.get("origin_airport", origin_iata),
                "destination": ticket.get("destination", dest_iata),
                "destination_airport": ticket.get("destination_airport", dest_iata),
                "link": booking_link,
            })
        return results

    def format_flight_results(self, results: list[dict]) -> str:
        if not results:
            return "No flights found."
        lines: list[str] = []
        for i, r in enumerate(results, 1):
            dur_h = r["duration_min"] // 60 if r["duration_min"] else 0
            dur_m = r["duration_min"] % 60 if r["duration_min"] else 0
            stops = "direct" if r["transfers"] == 0 else f"{r['transfers']} stop(s)"
            dep = r.get("departure_at", "")
            if dep:
                try:
                    dt = datetime.fromisoformat(dep.replace("Z", "+00:00"))
                    dep = dt.strftime("%b %d, %H:%M")
                except ValueError:
                    pass

            line = (
                f"{i}. {r['origin_airport']}->{r['destination_airport']}  "
                f"{r['currency']} {r['price']}  |  "
                f"{dur_h}h {dur_m:02d}m  |  {stops}  |  "
                f"{r['airline']} {r.get('flight_number', '')}"
            )
            if dep:
                line += f"  |  {dep}"
            lines.append(line)
            if r.get("link"):
                lines.append(f"   Book: {r['link']}")
        return "\n".join(lines)

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """Convert various date formats to YYYY-MM or YYYY-MM-DD."""
        cleaned = date_str.strip()
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return cleaned

    def _get_json(self, url: str) -> dict[str, Any] | None:
        req = urllib.request.Request(url, headers={
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                import gzip
                try:
                    raw = gzip.decompress(raw)
                except (gzip.BadGzipFile, OSError):
                    pass
                return json.loads(raw)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Travelpayouts API failed: %s", exc)
            return None


def google_flights_url(origin: str, destination: str, date: str | None = None) -> str:
    base = "https://www.google.com/travel/flights"
    q_parts = [origin.strip(), destination.strip()]
    if date:
        q_parts.append(date.strip())
    return f"{base}?q={urllib.parse.quote(' '.join(q_parts))}"


def omio_url(origin: str, destination: str) -> str:
    o = urllib.parse.quote(origin.strip())
    d = urllib.parse.quote(destination.strip())
    return f"https://www.omio.com/search?from={o}&to={d}"


def format_verified_routes(routes: list[dict]) -> str:
    if not routes:
        return "No verified routes found."
    parts: list[str] = []
    for i, route in enumerate(routes, 1):
        lines = [f"Route {i}: {route['summary']}"]
        if route.get("total_estimate"):
            lines[0] += f"  [{route['total_estimate']}]"
        for j, leg in enumerate(route["legs"], 1):
            line = f"  Leg {j}: {leg['from']} -> {leg['to']}  |  {leg['transport']}"
            if leg.get("details"):
                line += f"  |  {leg['details']}"
            lines.append(line)
            if leg.get("link"):
                lines.append(f"         {leg['link']}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
