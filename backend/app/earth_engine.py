
import ee
from datetime import datetime, timedelta


PROJECT_ID = "satyacover"
COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"


def initialize_earth_engine():
    """Initialize Earth Engine with the registered SatyaCover project."""
    ee.Initialize(project=PROJECT_ID)


def get_ndvi_summary(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    buffer_meters: int = 100,
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

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    if end < start:
        raise ValueError("End date must be on or after start date.")

    if not 1 <= buffer_meters <= 5000:
        raise ValueError("Buffer must be between 1 and 5000 metres.")

    # Earth Engine's filterDate uses an exclusive end date.
    exclusive_end = (end + timedelta(days=1)).isoformat()

    point = ee.Geometry.Point([longitude, latitude])
    region = point.buffer(buffer_meters)

    # Sentinel-2 Scene Classification Layer:
    # remove defective pixels, cloud shadows, clouds, cirrus and snow.
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

    collection = (
        ee.ImageCollection(COLLECTION_ID)
        .filterBounds(region)
        .filterDate(start.isoformat(), exclusive_end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
        .map(mask_clouds)
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
        "buffer_meters": buffer_meters,
        "image_count": image_count,
        "ndvi_mean": round(float(mean_ndvi), 4),
        "interpretation": (
            "Vegetation index only; not standalone proof of crop loss."
        ),
    }


def compare_with_historical_baseline(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    buffer_meters: int = 100,
):
    """
    Compare current-period NDVI with the same calendar period
    one year earlier.

    This is an initial baseline, not a validated crop-loss model.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Construct the equivalent period from the previous year.
    try:
        historical_start = start.replace(year=start.year - 1)
        historical_end = end.replace(year=end.year - 1)
    except ValueError:
        # Handle February 29 when the previous year is not a leap year.
        from calendar import monthrange

        historical_start = start.replace(
            year=start.year - 1,
            day=min(start.day, monthrange(start.year - 1, start.month)[1]),
        )
        historical_end = end.replace(
            year=end.year - 1,
            day=min(end.day, monthrange(end.year - 1, end.month)[1]),
        )

    current = get_ndvi_summary(
        latitude,
        longitude,
        start_date,
        end_date,
        buffer_meters,
    )

    historical = get_ndvi_summary(
        latitude,
        longitude,
        historical_start.isoformat(),
        historical_end.isoformat(),
        buffer_meters,
    )

    current_ndvi = current.get("ndvi_mean")
    historical_ndvi = historical.get("ndvi_mean")

    if current_ndvi is None or historical_ndvi is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "current_period": current,
            "historical_baseline": historical,
            "ndvi_change": None,
            "message": (
                "A comparison could not be calculated because valid "
                "NDVI data was unavailable for one or both periods."
            ),
        }

    ndvi_change = round(current_ndvi - historical_ndvi, 4)

    return {
        "status": "SUCCESS",
        "current_period": current,
        "historical_baseline": historical,
        "ndvi_change": ndvi_change,
        "message": (
            "NDVI change is a vegetation indicator, not standalone "
            "proof of crop loss. Differences in crop stage, weather, "
            "and observation conditions must be considered."
        ),
    }
