
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
    baseline_years: int = 3,
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
