from pathlib import Path
import joblib
import pandas as pd
from datetime import date
from typing import Any,Literal
from app.earth_engine import (
    initialize_earth_engine,
    get_ndvi_summary,
    compare_with_historical_baseline,
)
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

app = FastAPI(
    title="SatyaCover API",
    description="Prototype API for explainable crop-loss assessment. Demo outputs are not insurance decisions.",
    version="0.1.0",
)

# --------------------------------------------------
# CROP YIELD ML MODEL
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

YIELD_MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "crop_yield_xgboost_no_area_candidate.joblib"
)

_yield_artifact = None


def get_yield_model():
    global _yield_artifact

    if _yield_artifact is None:
        if not YIELD_MODEL_PATH.exists():
            raise HTTPException(
                status_code=503,
                detail="Crop yield model file not found."
            )

        try:
            _yield_artifact = joblib.load(YIELD_MODEL_PATH)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Could not load crop yield model: {exc}"
            ) from exc

    return _yield_artifact

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class AssessmentRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    crop: Literal[
        "rice", "wheat", "cotton", "soybean", "sugarcane", "other"
    ] = "other"
    start_date: date
    end_date: date
    field_boundary: dict[str, Any] | None = None
        # Optional historical yield benchmark inputs
    state_name: str | None = None
    district_name: str | None = None
    crop_name: str | None = None
    season: str | None = None
    benchmark_year: int | None = Field(
        default=None,
        ge=1997,
        le=2022
    )

    @model_validator(mode="after")
    def validate_dates_and_boundary(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")

        if (self.end_date - self.start_date).days > 400:
            raise ValueError("Choose a period of 400 days or less for the MVP")

        if self.field_boundary is not None:
            if self.field_boundary.get("type") != "Polygon":
                raise ValueError(
                    "field_boundary must be a GeoJSON Polygon"
                )

            coordinates = self.field_boundary.get("coordinates")

            if not isinstance(coordinates, list) or len(coordinates) != 1:
                raise ValueError(
                    "Provide one polygon ring in field_boundary.coordinates"
                )

            ring = coordinates[0]

            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError(
                    "A polygon ring must contain at least four coordinates"
                )

            for point in ring:
                if (
                    not isinstance(point, (list, tuple))
                    or len(point) != 2
                ):
                    raise ValueError(
                        "Each polygon coordinate must be [longitude, latitude]"
                    )

                longitude, latitude = point

                if not (
                    isinstance(longitude, (int, float))
                    and isinstance(latitude, (int, float))
                    and -180 <= longitude <= 180
                    and -90 <= latitude <= 90
                ):
                    raise ValueError(
                        "Polygon coordinates are outside valid geographic ranges"
                    )

            if ring[0] != ring[-1]:
                raise ValueError(
                    "The polygon ring must be closed"
                )

        return self

class YieldPredictionRequest(BaseModel):
    year_start: int = Field(ge=1997, le=2022)
    state_name: str = Field(min_length=1)
    district_name: str = Field(min_length=1)
    crop_name: str = Field(min_length=1)
    season: str = Field(min_length=1)

@app.get("/")
def root():
    return {"app": "SatyaCover", "status": "running", "mode": "MVP"}


@app.get("/health")
def health():
    return {"status": "ok"}

# --------------------------------------------------
# CROP YIELD PREDICTION API
# --------------------------------------------------

@app.post("/api/yield/predict")
def predict_crop_yield(request: YieldPredictionRequest):

    artifact = get_yield_model()

    preprocessor = artifact["preprocessor"]
    model = artifact["model"]
    features = artifact["features"]

    input_data = pd.DataFrame([{
        "year_start": request.year_start,
        "state_name": request.state_name.strip(),
        "district_name": request.district_name.strip(),
        "crop_name": request.crop_name.strip(),
        "season": request.season.strip(),
    }])

    try:
        X = preprocessor.transform(input_data[features])
        prediction = float(model.predict(X)[0])

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Yield prediction failed: {exc}"
        ) from exc

    return {
        "status": "SUCCESS",
        "predicted_yield": round(prediction, 4),
        "unit": "tonnes/hectare",
        "model": "xgboost_no_area",
        "prediction_type": "historical_crop_yield_benchmark",
        "disclaimer": (
            "This is a historical crop-yield benchmark, "
            "not a farm-level crop-loss estimate."
        )
    }

@app.get("/api/weather")
def get_weather(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    start_date: date = Query(),
    end_date: date = Query(),
):
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    }
    try:
        response = requests.get(url, params=params, timeout=25)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Weather provider request failed: {exc}") from exc

    daily = payload.get("daily", {})
    times = daily.get("time", [])
    rows = []
    for i, day in enumerate(times):
        rows.append({
            "date": day,
            "precipitation_mm": _at(daily.get("precipitation_sum", []), i),
            "temperature_max_c": _at(daily.get("temperature_2m_max", []), i),
            "temperature_min_c": _at(daily.get("temperature_2m_min", []), i),
        })

    return {
        "source": "Open-Meteo Historical Weather API (reanalysis)",
        "latitude": latitude,
        "longitude": longitude,
        "daily": rows,
        "note": "Weather reanalysis is an estimate for the area, not a field-level sensor reading.",
    }





@app.post("/api/assess")
def assess(request: AssessmentRequest):

    # --------------------------------------------------
    # 1. RETRIEVE HISTORICAL WEATHER
    # --------------------------------------------------

    try:
        weather = get_weather(
            latitude=request.latitude,
            longitude=request.longitude,
            start_date=request.start_date,
            end_date=request.end_date,
        )

    except HTTPException:
        weather = {
            "daily": [],
            "source": "Unavailable"
        }

    daily = weather.get("daily", [])

    rainfall = [
        row["precipitation_mm"]
        for row in daily
        if isinstance(row.get("precipitation_mm"), (int, float))
    ]

    total_rainfall = (
        round(sum(rainfall), 2)
        if rainfall else None
    )

    historical_rainfall_comparison = (
    compare_rainfall_with_historical_baseline(
        latitude=request.latitude,
        longitude=request.longitude,
        start_date=request.start_date,
        end_date=request.end_date,
        years=3,
    )
)

    # --------------------------------------------------
    # 2. RETRIEVE SATELLITE VEGETATION EVIDENCE
    # --------------------------------------------------

    try:
        initialize_earth_engine()

        satellite = get_ndvi_summary(
            latitude=request.latitude,
            longitude=request.longitude,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            field_boundary=request.field_boundary,
        )

    except Exception:
        satellite = {
            "status": "UNAVAILABLE",
            "message": "Satellite data could not be retrieved.",
            "image_count": 0,
            "ndvi_mean": None,
        }

    satellite_available = (
        satellite.get("status") == "SUCCESS"
        and satellite.get("ndvi_mean") is not None
    )

    # --------------------------------------------------
    # 3. HISTORICAL NDVI COMPARISON
    # --------------------------------------------------

    try:
        historical_comparison = compare_with_historical_baseline(
            latitude=request.latitude,
            longitude=request.longitude,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            field_boundary=request.field_boundary,
        )

    except Exception:
        historical_comparison = {
            "status": "UNAVAILABLE",
            "ndvi_change": None,
            "message": (
                "Historical vegetation comparison "
                "could not be retrieved."
            ),
        }

    crop_stress_assessment = build_crop_stress_assessment(
    satellite=satellite,
    historical_comparison=historical_comparison,
    current_rainfall=total_rainfall,
    rainfall_comparison=historical_rainfall_comparison,
)
    # --------------------------------------------------
    # 4. HISTORICAL CROP YIELD BENCHMARK
    # --------------------------------------------------

    yield_benchmark = {
        "status": "NOT_REQUESTED",
        "message": "Historical yield benchmark was not requested."
    }

    yield_fields = [
        request.state_name,
        request.district_name,
        request.crop_name,
        request.season,
    ]

    if any(yield_fields) or request.benchmark_year is not None:

        if not all(yield_fields) or request.benchmark_year is None:

            yield_benchmark = {
                "status": "INCOMPLETE_INPUT",
                "message": (
                    "Provide state, district, crop, season and "
                    "benchmark year to generate a yield prediction."
                )
            }

        else:
            try:
                yield_benchmark = predict_crop_yield(
                    YieldPredictionRequest(
                        year_start=request.benchmark_year,
                        state_name=request.state_name,
                        district_name=request.district_name,
                        crop_name=request.crop_name,
                        season=request.season
                    )
                )

            except HTTPException as exc:
                yield_benchmark = {
                    "status": "UNAVAILABLE",
                    "message": str(exc.detail)
                }

    # --------------------------------------------------
    # 5. DETERMINE EVIDENCE STATUS
    # --------------------------------------------------

    if satellite_available:
        assessment_status = (
            "EVIDENCE AVAILABLE — LOSS ASSESSMENT PENDING"
        )

        explanation = (
            "Satellite vegetation evidence is available. "
            "Weather evidence and historical crop-yield "
            "benchmarks are provided separately. A validated "
            "farm-level crop-loss model is still required. "
            "NDVI alone does not prove crop loss."
        )

    else:
        assessment_status = "INSUFFICIENT DATA"

        explanation = (
            "Usable satellite vegetation evidence is unavailable. "
            "Weather and historical yield information alone "
            "cannot establish farm-level crop damage."
        )

    # --------------------------------------------------
    # 6. FINAL ASSESSMENT RESPONSE
    # --------------------------------------------------

    return {
        "project": "SatyaCover",

        "mode": (
            "PROTOTYPE — satellite, weather and yield evidence"
        ),

        "field": {
            "latitude": request.latitude,
            "longitude": request.longitude,
            "crop": request.crop,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
        },

        "weather_summary": {
            "source": weather.get("source", "Unavailable"),
            "days_returned": len(daily),
            "total_precipitation_mm": total_rainfall,
        },

        "satellite_evidence": satellite,

        "historical_comparison": historical_comparison,

        "historical_rainfall_comparison": historical_rainfall_comparison,

        "crop_stress_assessment": crop_stress_assessment,

        "historical_yield_benchmark": yield_benchmark,

        "assessment": {
            "status": assessment_status,
            "loss_severity": None,
            "confidence": None,
            "payout_estimate": None,
            "explanation": explanation,
        },

        "next_step": (
            "Combine historical yield benchmarks with "
            "satellite and weather anomalies to develop "
            "a validated crop-loss assessment."
        ),

        "disclaimer": (
            "Prototype only. Historical yield is not measured "
            "farm yield. This is not an official crop-loss "
            "assessment, insurance decision, or payout guarantee."
        ),
    }

@app.get("/api/ndvi")
def get_ndvi(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    start_date: date = Query(),
    end_date: date = Query(),
):
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    if (end_date - start_date).days > 400:
        raise HTTPException(
            status_code=400,
            detail="Choose a period of 400 days or less for the MVP",
        )

    try:
        initialize_earth_engine()

        return get_ndvi_summary(
            latitude=latitude,
            longitude=longitude,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Satellite data request failed. Check Earth Engine connectivity and try again.",
        ) from exc



def _at(values, index):
    return values[index] if index < len(values) else None


def compare_rainfall_with_historical_baseline(
    latitude,
    longitude,
    start_date,
    end_date,
    years=3,
):
    """Compare rainfall with matching calendar periods in previous years."""

    historical_periods = []

    for offset in range(1, years + 1):
        target_year = start_date.year - offset

        try:
            historical_start = start_date.replace(
                year=target_year
            )
            historical_end = end_date.replace(
                year=target_year
            )
        except ValueError:
            # Handles dates such as February 29.
            import calendar

            start_day = min(
                start_date.day,
                calendar.monthrange(
                    target_year, start_date.month
                )[1],
            )
            end_day = min(
                end_date.day,
                calendar.monthrange(
                    target_year, end_date.month
                )[1],
            )

            historical_start = start_date.replace(
                year=target_year, day=start_day
            )
            historical_end = end_date.replace(
                year=target_year, day=end_day
            )

        try:
            historical_weather = get_weather(
                latitude=latitude,
                longitude=longitude,
                start_date=historical_start,
                end_date=historical_end,
            )

            values = [
                row["precipitation_mm"]
                for row in historical_weather.get("daily", [])
                if isinstance(
                    row.get("precipitation_mm"), (int, float)
                )
            ]

            if values:
                historical_periods.append({
                    "year": target_year,
                    "total_rainfall_mm": round(sum(values), 2),
                    "days_returned": len(values),
                })

        except Exception:
            continue

    if not historical_periods:
        return {
            "status": "UNAVAILABLE",
            "historical_average_mm": None,
            "years_available": 0,
            "periods": [],
        }

    average = sum(
        period["total_rainfall_mm"]
        for period in historical_periods
    ) / len(historical_periods)

    return {
        "status": "SUCCESS",
        "historical_average_mm": round(average, 2),
        "years_available": len(historical_periods),
        "periods": historical_periods,
    }


def build_crop_stress_assessment(
    satellite,
    historical_comparison,
    current_rainfall,
    rainfall_comparison,
):
    """Produce explainable evidence categories, not a loss percentage."""

    current_ndvi = satellite.get("ndvi_mean")
    baseline_ndvi = historical_comparison.get(
        "historical_average_ndvi"
    )

    image_count = satellite.get("image_count", 0) or 0
    historical_years = historical_comparison.get(
        "historical_years_available", 0
    ) or 0

    rainfall_baseline = rainfall_comparison.get(
        "historical_average_mm"
    )

    rainfall_years = rainfall_comparison.get(
        "years_available", 0
    ) or 0

    ndvi_change_percent = None
    rainfall_change_percent = None

    if (
        isinstance(current_ndvi, (int, float))
        and isinstance(baseline_ndvi, (int, float))
        and baseline_ndvi > 0.05
    ):
        ndvi_change_percent = round(
            ((current_ndvi - baseline_ndvi) / baseline_ndvi) * 100,
            2,
        )

    if (
        isinstance(current_rainfall, (int, float))
        and isinstance(rainfall_baseline, (int, float))
        and rainfall_baseline > 1
    ):
        rainfall_change_percent = round(
            (
                (current_rainfall - rainfall_baseline)
                / rainfall_baseline
            ) * 100,
            2,
        )

    satellite_usable = (
        satellite.get("status") == "SUCCESS"
        and isinstance(current_ndvi, (int, float))
        and image_count >= 3
    )

    historical_usable = (
        ndvi_change_percent is not None
        and historical_years >= 2
    )

    if image_count >= 5 and historical_years >= 3:
        evidence_quality = "GOOD"
    elif image_count >= 3 and historical_years >= 2:
        evidence_quality = "MODERATE"
    else:
        evidence_quality = "LIMITED"

    if not satellite_usable or not historical_usable:
        return {
            "status": "INSUFFICIENT_DATA",
            "category": "INSUFFICIENT_DATA",
            "evidence_quality": evidence_quality,
            "ndvi_change_percent": ndvi_change_percent,
            "rainfall_change_percent": rainfall_change_percent,
            "interpretation": (
                "There is not enough usable satellite or historical "
                "vegetation evidence to assess a possible stress signal."
            ),
            "recommended_action": (
                "Collect more usable satellite observations and "
                "check the field directly."
            ),
        }

    # These are initial screening thresholds for the prototype,
    # not scientifically validated crop-loss thresholds.
    if ndvi_change_percent <= -15:
        category = "POSSIBLE_CROP_STRESS"
        status = "REQUIRES_FIELD_VERIFICATION"
        interpretation = (
            "The current vegetation reading is substantially lower "
            "than the available historical average. This may indicate "
            "vegetation stress, but it does not confirm crop damage."
        )

    elif (
        ndvi_change_percent <= -10
        or (
            rainfall_change_percent is not None
            and abs(rainfall_change_percent) >= 30
        )
    ):
        category = "REQUIRES_FIELD_VERIFICATION"
        status = "REQUIRES_FIELD_VERIFICATION"
        interpretation = (
            "One or more observations differ from their historical "
            "levels. Check crop growth stage, planting dates, rainfall "
            "timing and actual field conditions."
        )

    else:
        category = "NO_CLEAR_STRESS_SIGNAL"
        status = "EVIDENCE_REVIEWED"
        interpretation = (
            "The available observations do not show a strong "
            "vegetation decline against the historical baseline. "
            "This does not guarantee that the crop is healthy."
        )

    if rainfall_years < 2 or rainfall_change_percent is None:
        evidence_quality = (
            "MODERATE" if evidence_quality == "GOOD"
            else "LIMITED"
        )

    return {
        "status": status,
        "category": category,
        "evidence_quality": evidence_quality,
        "indicators": {
            "current_ndvi": round(current_ndvi, 4),
            "historical_average_ndvi": round(baseline_ndvi, 4),
            "ndvi_change_percent": ndvi_change_percent,
            "current_rainfall_mm": current_rainfall,
            "historical_average_rainfall_mm": rainfall_baseline,
            "rainfall_change_percent": rainfall_change_percent,
            "satellite_images": image_count,
            "historical_ndvi_years": historical_years,
            "historical_rainfall_years": rainfall_years,
        },
        "interpretation": interpretation,
        "recommended_action": (
            "Inspect the field, photograph any visible damage, "
            "and consult an agricultural expert before making "
            "a crop-loss or insurance decision."
        ),
        "limitations": [
            "Screening thresholds are provisional and not validated.",
            "Calendar-period comparisons may not match crop growth stages.",
            "Rainfall totals do not establish flooding or drought damage.",
            "NDVI does not directly measure crop yield or crop loss.",
            "No farm-level crop-loss percentage or payout is calculated.",
        ],
    }
