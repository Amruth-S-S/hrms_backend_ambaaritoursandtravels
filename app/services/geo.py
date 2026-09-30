import httpx

from app.core.config import settings
from app.utils import haversine_m


async def reverse_geocode(lat: float, lng: float) -> str | None:
    """Best-effort address lookup via OpenStreetMap Nominatim. Never raises."""
    if not settings.REVERSE_GEOCODE:
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json", "zoom": 18},
                headers={"User-Agent": "HRMS-Attendance/1.0"},
            )
            if r.status_code == 200:
                return r.json().get("display_name")
    except Exception:
        pass
    return None


async def build_location(lat: float, lng: float, accuracy: float | None, company: dict) -> dict:
    distance = within = None
    if company.get("office_lat") is not None and company.get("office_lng") is not None:
        distance = round(haversine_m(lat, lng, company["office_lat"], company["office_lng"]))
        within = distance <= company.get("office_radius_m", 200)
    return {
        "latitude": lat,
        "longitude": lng,
        "accuracy_m": round(accuracy) if accuracy is not None else None,
        "address": await reverse_geocode(lat, lng),
        "distance_from_office_m": distance,
        "within_geofence": within,
    }
