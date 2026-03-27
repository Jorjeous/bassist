from __future__ import annotations

import json
import urllib.request
import urllib.error


class WeatherTool:
    def __init__(self, region: str = "wt-wt") -> None:
        self._region = region

    def lookup(self, city: str) -> str:
        encoded = urllib.request.quote(city)
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return f"Could not retrieve weather for {city}."

        try:
            return self._format_report(data, city)
        except (KeyError, IndexError, TypeError):
            return f"Could not parse weather data for {city}."

    def _format_report(self, data: dict, city: str) -> str:
        cur = data["current_condition"][0]
        today = data["weather"][0]
        astro = today["astronomy"][0]
        hourly = {int(h["time"]): h for h in today["hourly"]}

        cur_temp = cur["temp_C"]
        cur_feels = cur["FeelsLikeC"]
        cur_desc = cur["weatherDesc"][0]["value"].strip()
        cur_wind = f"{cur['windspeedKmph']} km/h {cur['winddir16Point']}"
        cur_humidity = cur["humidity"]

        def _hour_line(time_key: int, label: str) -> str:
            h = hourly.get(time_key)
            if not h:
                return f"  {label:>7}: n/a"
            desc = h["weatherDesc"][0]["value"].strip()
            return f"  {label:>7}: {h['tempC']:>3}°C (feels {h['FeelsLikeC']:>3}°C)  {desc}"

        conditions = self._build_conditions_alert(hourly)

        lines = [
            f"Weather for {city} — {today['date']}",
            "",
            f"Conditions: {cur_desc}",
        ]
        if conditions:
            lines.append(f"Day forecast: {conditions}")
        lines += [
            "",
            "Temperature:",
            f"  Current: {cur_temp:>3}°C (feels {cur_feels:>3}°C)  {cur_desc}",
            _hour_line(900, "09:00"),
            _hour_line(1200, "12:00"),
            _hour_line(2100, "21:00"),
            "",
            f"Humidity: {cur_humidity}%",
            f"Wind: {cur_wind}",
            f"Sunrise: {astro['sunrise']}  Sunset: {astro['sunset']}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _build_conditions_alert(hourly: dict) -> str:
        alerts = []
        dominated_by = set()
        for hour_data in hourly.values():
            rain = int(hour_data.get("chanceofrain", 0))
            snow = int(hour_data.get("chanceofsnow", 0))
            fog = int(hour_data.get("chanceoffog", 0))
            thunder = int(hour_data.get("chanceofthunder", 0))
            if rain > 40:
                dominated_by.add("rain")
            if snow > 40:
                dominated_by.add("snow")
            if fog > 40:
                dominated_by.add("fog")
            if thunder > 30:
                dominated_by.add("thunderstorm")

        if not dominated_by:
            max_rain = max((int(h.get("chanceofrain", 0)) for h in hourly.values()), default=0)
            max_snow = max((int(h.get("chanceofsnow", 0)) for h in hourly.values()), default=0)
            if max_rain > 20:
                alerts.append(f"slight chance of rain ({max_rain}%)")
            if max_snow > 20:
                alerts.append(f"slight chance of snow ({max_snow}%)")
            if not alerts:
                return "No significant conditions expected"
            return ", ".join(alerts)

        return "Expect: " + ", ".join(sorted(dominated_by))
