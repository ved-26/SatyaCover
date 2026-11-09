
import ee
import math
import requests
from datetime import datetime, timedelta


PROJECT_ID = "satyacover"
COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"


def initialize_earth_engine():
    """Initialize Earth Engine with the registered SatyaCover project."""
    ee.Initialize(project=PROJECT_ID)


NDVI_VISUALIZATION = {
    "min": -0.2,
    "max": 0.9,
    "palette": ["8c510a", "d8b365", "f6e8c3", "a6d96a", "1a9850", "006837"],
}
THUMBNAIL_DIMENSION = 512
MAX_THUMBNAIL_BYTES = 1_500_000


def _validated_period(start_date: str, end_date: str):
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end < start:
        raise ValueError("End date must be on or after start date.")
    if (end - start).days > 400:
        raise ValueError("Choose dates no more than 400 days apart.")
    return start, end, (end + timedelta(days=1)).isoformat()


def _build_region(latitude, longitude, buffer_meters, field_boundary):
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    if not 1 <= buffer_meters <= 5000:
        raise ValueError("Buffer must be between 1 and 5000 metres.")

    if field_boundary is None:
        return ee.Geometry.Point([longitude, latitude]).buffer(buffer_meters), "Point buffer"

    if not isinstance(field_boundary, dict) or field_boundary.get("type") != "Polygon":
        raise ValueError("field_boundary must be a GeoJSON Polygon")
    coordinates = field_boundary.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 1:
        raise ValueError("Provide one polygon ring in field_boundary.coordinates")
    ring = coordinates[0]
    if not isinstance(ring, list) or len(ring) < 4:
        raise ValueError("A polygon ring must contain at least four coordinates")

    validated_ring = []
    for point in ring:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("Each polygon coordinate must be [longitude, latitude]")
        lon, lat = point
        if (
            not isinstance(lon, (int, float))
            or not isinstance(lat, (int, float))
            or not math.isfinite(lon)
            or not math.isfinite(lat)
            or not -180 <= lon <= 180
            or not -90 <= lat <= 90
        ):
            raise ValueError("Polygon coordinates are outside valid geographic ranges")
        validated_ring.append([float(lon), float(lat)])

    if validated_ring[0] != validated_ring[-1]:
        raise ValueError("The polygon ring must be closed")
    vertices = validated_ring[:-1]
    if len(set(map(tuple, vertices))) < 3:
        raise ValueError("The polygon must have at least three distinct vertices")
    if any(vertices[index] == vertices[(index + 1) % len(vertices)] for index in range(len(vertices))):
        raise ValueError("The polygon cannot contain consecutive duplicate vertices")
    ring_area = abs(sum(
        vertices[index][0] * vertices[(index + 1) % len(vertices)][1]
        - vertices[(index + 1) % len(vertices)][0] * vertices[index][1]
        for index in range(len(vertices))
    )) / 2
    if ring_area <= 1e-12:
        raise ValueError("The polygon must enclose a non-zero area")

    return ee.Geometry.Polygon([validated_ring]), "Polygon"


def _cloud_masked_sentinel2_collection(region, start_date, exclusive_end):
    # Remove defective pixels, cloud shadows, clouds, cirrus and snow.
    def mask_clouds(image):
        scl = image.select("SCL")
        clear_mask = (
            scl.neq(1)
            .And(scl.neq(3))
            .And(scl.neq(7))
            .And(scl.neq(8))
            .And(scl.neq(9))
            .And(scl.neq(10))
            .And(scl.neq(11))
        )
        return image.updateMask(clear_mask)

    return (
        ee.ImageCollection(COLLECTION_ID)
        .filterBounds(region)
        .filterDate(start_date, exclusive_end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
        .map(mask_clouds)
    )


def _download_png(image, region):
    url = image.getThumbURL({
        "region": region,
        "dimensions": THUMBNAIL_DIMENSION,
        "format": "png",
    })
    response = requests.get(url, timeout=(10, 45))
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type != "image/png" or not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Earth Engine did not return a PNG thumbnail")
    if len(response.content) > MAX_THUMBNAIL_BYTES:
        raise RuntimeError("Earth Engine thumbnail exceeded the image size limit")
    return response.content


def get_satellite_visualizations(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    field_boundary: dict,
):
    """Generate field-clipped true-colour and NDVI PNG previews."""
    start, end, exclusive_end = _validated_period(start_date, end_date)
    region, geometry_type = _build_region(latitude, longitude, 100, field_boundary)
    if geometry_type != "Polygon":
        raise ValueError("A selected farm polygon is required for satellite previews")

    collection = _cloud_masked_sentinel2_collection(
        region, start.isoformat(), exclusive_end
    )
    image_count = collection.size().getInfo()
    metadata = {
        "source": COLLECTION_ID,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "image_count": image_count,
        "geometry_type": geometry_type,
        "thumbnail_dimension": THUMBNAIL_DIMENSION,
        "ndvi_legend": NDVI_VISUALIZATION,
    }
    if image_count == 0:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "No Sentinel-2 scenes were available for this field and date range.",
            **metadata,
        }

    composite = collection.median().clip(region)
    rgb = composite.select(["B4", "B3", "B2"]).visualize(
        min=0, max=3000, gamma=1.2
    ).clip(region)
    ndvi = composite.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndvi_visual = ndvi.visualize(**NDVI_VISUALIZATION).clip(region)

    return {
        "status": "SUCCESS",
        "true_colour_png": _download_png(rgb, region),
        "ndvi_png": _download_png(ndvi_visual, region),
        **metadata,
    }



def get_ndvi_summary(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    buffer_meters: int = 100,
    field_boundary: dict | None = None,
):

    """
    Calculate mean NDVI for a small area around a farm location.

    Dates must use YYYY-MM-DD format.
    The end date is included in the search.
    """
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")

    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")

    start, end, exclusive_end = _validated_period(start_date, end_date)
    region, geometry_type = _build_region(
        latitude, longitude, buffer_meters, field_boundary
    )
    collection = _cloud_masked_sentinel2_collection(
        region, start.isoformat(), exclusive_end
    )

    image_count = collection.size().getInfo()

    if image_count == 0:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "No Sentinel-2 scenes found for this location and date range.",
            "image_count": 0,
            "ndvi_mean": None,
        }

    # Median composite reduces the influence of remaining noisy observations.
    composite = collection.median()

    ndvi = composite.normalizedDifference(["B8", "B4"]).rename("NDVI")

    stats = ndvi.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=10,
        maxPixels=1000000,
        bestEffort=True,
    ).getInfo()

    mean_ndvi = stats.get("NDVI")

    if mean_ndvi is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "No valid cloud-masked NDVI pixels were available.",
            "image_count": image_count,
            "ndvi_mean": None,
        }

    return {
        "status": "SUCCESS",
        "source": COLLECTION_ID,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "latitude": latitude,
        "longitude": longitude,
        "geometry_type": geometry_type,
        "buffer_meters": (
        buffer_meters if field_boundary is None else None
        ),
        "image_count": image_count,
        "ndvi_mean": round(float(mean_ndvi), 4),
        "interpretation": (
            "Vegetation index only; not standalone proof of crop loss."
        ),
    }




SENTINEL1_COLLECTION_ID = "COPERNICUS/S1_GRD"


def get_sentinel1_summary(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    buffer_meters: int = 100,
    field_boundary: dict | None = None,
):
    """Return descriptive Sentinel-1 VV/VH backscatter for one orbit pass.

    The pass with the most usable scenes is selected to avoid mixing
    ascending and descending viewing geometry. Values are mean sigma-naught
    backscatter in dB, not crop-loss estimates.
    """
    start, end, exclusive_end = _validated_period(start_date, end_date)
    region, geometry_type = _build_region(
        latitude, longitude, buffer_meters, field_boundary
    )
    collection = (
        ee.ImageCollection(SENTINEL1_COLLECTION_ID)
        .filterBounds(region)
        .filterDate(start.isoformat(), exclusive_end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("resolution_meters", 10))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )
    counts = {
        orbit_pass: collection.filter(
            ee.Filter.eq("orbitProperties_pass", orbit_pass)
        ).size().getInfo()
        for orbit_pass in ("ASCENDING", "DESCENDING")
    }
    selected_pass = max(counts, key=counts.get)
    image_count = counts[selected_pass]
    metadata = {
        "source": SENTINEL1_COLLECTION_ID,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "image_count": image_count,
        "geometry_type": geometry_type,
        "instrument_mode": "IW",
        "polarizations": ["VV", "VH"],
        "orbit_pass": selected_pass if image_count else None,
        "orbit_pass_scene_counts": counts,
    }
    if image_count == 0:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "No Sentinel-1 IW VV/VH scenes were available for this area and period.",
            "vv_mean_db": None,
            "vh_mean_db": None,
            **metadata,
        }

    composite = (
        collection
        .filter(ee.Filter.eq("orbitProperties_pass", selected_pass))
        .median()
    )
    statistics = composite.select(["VV", "VH"]).reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=10,
        maxPixels=1000000,
        bestEffort=True,
    ).getInfo()
    vv = statistics.get("VV")
    vh = statistics.get("VH")
    if vv is None and vh is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "Sentinel-1 scenes were found, but no valid VV/VH pixels were available for this area.",
            "vv_mean_db": None,
            "vh_mean_db": None,
            **metadata,
        }

    return {
        "status": "SUCCESS",
        "message": "Descriptive radar backscatter only; not a crop-loss or damage assessment.",
        "vv_mean_db": round(float(vv), 2) if vv is not None else None,
        "vh_mean_db": round(float(vh), 2) if vh is not None else None,
        **metadata,
    }


def compare_with_historical_baseline(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    buffer_meters: int = 100,
    baseline_years: int = 3,
    field_boundary: dict | None = None,
):

    """
    Compare current-period NDVI with the average of matching
    calendar periods from previous years with usable observations.

    This is an evidence indicator, not a validated crop-loss model.
    """
    if not 1 <= baseline_years <= 10:
        raise ValueError("baseline_years must be between 1 and 10.")

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    if end < start:
        raise ValueError("End date must be on or after start date.")

    current = get_ndvi_summary(
    latitude,
    longitude,
    start_date,
    end_date,
    buffer_meters,
    field_boundary,
    )

    historical_periods = []

    for years_back in range(1, baseline_years + 1):
        try:
            historical_start = start.replace(year=start.year - years_back)
        except ValueError:
            from calendar import monthrange

            historical_start = start.replace(
                year=start.year - years_back,
                day=min(
                    start.day,
                    monthrange(start.year - years_back, start.month)[1],
                ),
            )

        try:
            historical_end = end.replace(year=end.year - years_back)
        except ValueError:
            from calendar import monthrange

            historical_end = end.replace(
                year=end.year - years_back,
                day=min(
                    end.day,
                    monthrange(end.year - years_back, end.month)[1],
                ),
            )

        historical = get_ndvi_summary(
        latitude,
        longitude,
        historical_start.isoformat(),
        historical_end.isoformat(),
        buffer_meters,
        field_boundary,
        )

        historical_periods.append({
            "year": historical_start.year,
            "start_date": historical_start.isoformat(),
            "end_date": historical_end.isoformat(),
            "status": historical.get("status"),
            "image_count": historical.get("image_count", 0),
            "ndvi_mean": historical.get("ndvi_mean"),
        })

    valid_periods = [
        period for period in historical_periods
        if period["status"] == "SUCCESS"
        and period["ndvi_mean"] is not None
    ]

    current_ndvi = current.get("ndvi_mean")

    historical_average = None
    ndvi_change = None

    if valid_periods:
        historical_average = round(
            sum(period["ndvi_mean"] for period in valid_periods)
            / len(valid_periods),
            4,
        )

    if current_ndvi is not None and historical_average is not None:
        ndvi_change = round(current_ndvi - historical_average, 4)

    comparison_success = (
        current_ndvi is not None
        and historical_average is not None
    )

    return {
        "status": "SUCCESS" if comparison_success else "INSUFFICIENT_DATA",
        "current_period": current,
        "historical_periods": historical_periods,
        "historical_years_requested": baseline_years,
        "historical_years_available": len(valid_periods),
        "historical_average_ndvi": historical_average,
        "ndvi_change": ndvi_change,
        "message": (
            "Current NDVI is compared with the average of available "
            "matching calendar periods from previous years. Differences "
            "in crop stage, weather, and observation conditions matter. "
            "NDVI change alone does not prove crop loss."
            if comparison_success
            else
            "A comparison could not be calculated because current or "
            "historical NDVI data was unavailable."
        ),
    }
