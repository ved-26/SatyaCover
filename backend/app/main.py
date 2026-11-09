from pathlib import Path
import os
import re
import tempfile
import joblib
import pandas as pd
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from time import time
from typing import Any,Literal
from uuid import uuid4
from app.earth_engine import (
    initialize_earth_engine,
    get_ndvi_summary,
    get_satellite_visualizations,
    compare_with_historical_baseline,
    get_sentinel1_summary,
)
import requests
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

app = FastAPI(
    title="SatyaCover API",
    description="Prototype API for explainable crop-loss assessment. Demo outputs are not insurance decisions.",
    version="0.1.0",
)

_SATELLITE_IMAGE_CACHE_DIR = Path(tempfile.gettempdir()) / "satyacover-satellite-images"
_SATELLITE_IMAGE_CACHE_TTL_SECONDS = 30 * 60
_SATELLITE_IMAGE_CACHE_MAX_ENTRIES = 8
_SATELLITE_IMAGE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SATELLITE_IMAGE_SUFFIXES = {"true-colour": "rgb", "ndvi": "ndvi"}
_INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def _current_india_date():
    return datetime.now(_INDIA_TIMEZONE).date()


def _validate_observation_dates(start_date, end_date):
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )
    today = _current_india_date()
    if start_date > today or end_date > today:
        raise HTTPException(
            status_code=400,
            detail="Observation dates cannot be in the future.",
        )
    if (end_date - start_date).days > 400:
        raise HTTPException(
            status_code=400,
            detail="Choose a period of 400 days or less for the MVP",
        )


def _image_cache_path(image_id, image_kind):
    suffix = _SATELLITE_IMAGE_SUFFIXES.get(image_kind)
    if suffix is None or not _SATELLITE_IMAGE_ID_PATTERN.fullmatch(image_id):
        return None
    return _SATELLITE_IMAGE_CACHE_DIR / f"{image_id}-{suffix}.png"


def _prune_satellite_image_cache():
    _SATELLITE_IMAGE_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(_SATELLITE_IMAGE_CACHE_DIR, 0o700)
    now = time()
    for path in _SATELLITE_IMAGE_CACHE_DIR.glob("*.png.tmp"):
        if now - path.stat().st_mtime > _SATELLITE_IMAGE_CACHE_TTL_SECONDS:
            path.unlink(missing_ok=True)
    groups = {}
    for path in _SATELLITE_IMAGE_CACHE_DIR.glob("*.png"):
        image_id = path.name.split("-", 1)[0]
        if not _SATELLITE_IMAGE_ID_PATTERN.fullmatch(image_id):
            path.unlink(missing_ok=True)
            continue
        groups.setdefault(image_id, []).append(path)

    for image_id, paths in list(groups.items()):
        newest = max(path.stat().st_mtime for path in paths)
        if now - newest > _SATELLITE_IMAGE_CACHE_TTL_SECONDS:
            for path in paths:
                path.unlink(missing_ok=True)
            groups.pop(image_id, None)

    ordered = sorted(
        groups.items(),
        key=lambda item: max(path.stat().st_mtime for path in item[1]),
        reverse=True,
    )
    for _, paths in ordered[_SATELLITE_IMAGE_CACHE_MAX_ENTRIES:]:
        for path in paths:
            path.unlink(missing_ok=True)


def _store_satellite_images(visualizations):
    _prune_satellite_image_cache()
    image_id = uuid4().hex
    outputs = {
        _image_cache_path(image_id, "true-colour"): visualizations["true_colour_png"],
        _image_cache_path(image_id, "ndvi"): visualizations["ndvi_png"],
    }
    try:
        for path, content in outputs.items():
            temporary_path = path.with_suffix(".png.tmp")
            temporary_path.write_bytes(content)
            os.replace(temporary_path, path)
    except Exception:
        for path in outputs:
            path.unlink(missing_ok=True)
            path.with_suffix(".png.tmp").unlink(missing_ok=True)
        raise
    _prune_satellite_image_cache()
    return image_id


def _get_cached_satellite_image(image_id, image_kind):
    path = _image_cache_path(image_id, image_kind)
    if path is None:
        return None
    try:
        if time() - path.stat().st_mtime > _SATELLITE_IMAGE_CACHE_TTL_SECONDS:
            for kind in _SATELLITE_IMAGE_SUFFIXES:
                stale_path = _image_cache_path(image_id, kind)
                stale_path.unlink(missing_ok=True)
            return None
        return path.read_bytes()
    except FileNotFoundError:
        return None

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

        if self.start_date > _current_india_date() or self.end_date > _current_india_date():
            raise ValueError("Observation dates cannot be in the future.")

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

            vertices = ring[:-1]
            if len({(float(point[0]), float(point[1])) for point in vertices}) < 3:
                raise ValueError(
                    "The polygon must have at least three distinct vertices"
                )

            if any(
                vertices[index] == vertices[(index + 1) % len(vertices)]
                for index in range(len(vertices))
            ):
                raise ValueError(
                    "The polygon cannot contain consecutive duplicate vertices"
                )

            ring_area = abs(sum(
                vertices[index][0] * vertices[(index + 1) % len(vertices)][1]
                - vertices[(index + 1) % len(vertices)][0] * vertices[index][1]
                for index in range(len(vertices))
            )) / 2
            if ring_area <= 1e-12:
                raise ValueError(
                    "The polygon must enclose a non-zero area"
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


@app.get("/api/satellite/images/{image_id}/{image_kind}")
def get_satellite_image(image_id: str, image_kind: str):
    if image_kind not in {"true-colour", "ndvi"}:
        raise HTTPException(status_code=404, detail="Satellite image not found")

    image_bytes = _get_cached_satellite_image(image_id, image_kind)
    if image_bytes is None:
        raise HTTPException(
            status_code=404,
            detail="Satellite image is unavailable or has expired. Run the assessment again.",
        )

    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=600",
            "X-Content-Type-Options": "nosniff",
        },
    )

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
    _validate_observation_dates(start_date, end_date)

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
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Weather provider returned invalid JSON.",
        ) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Weather provider request failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail="Weather provider returned an unexpected response.",
        )
    if payload.get("error"):
        reason = payload.get("reason") or "Weather provider rejected the request."
        raise HTTPException(status_code=502, detail=str(reason))

    daily = payload.get("daily", {})
    if not isinstance(daily, dict):
        raise HTTPException(
            status_code=502,
            detail="Weather provider response did not include daily weather data.",
        )
    times = daily.get("time", [])
    if not isinstance(times, list):
        raise HTTPException(
            status_code=502,
            detail="Weather provider returned an invalid daily time series.",
        )
    rows = []
    for i, day in enumerate(times):
        rows.append({
            "date": day,
            "precipitation_mm": _at(daily.get("precipitation_sum", []), i),
            "temperature_max_c": _at(daily.get("temperature_2m_max", []), i),
            "temperature_min_c": _at(daily.get("temperature_2m_min", []), i),
        })

    precipitation_days = sum(
        1 for row in rows
        if isinstance(row["precipitation_mm"], (int, float))
        and not isinstance(row["precipitation_mm"], bool)
        and isfinite(float(row["precipitation_mm"]))
    )
    requested_days = (end_date - start_date).days + 1
    complete_precipitation = (
        len(rows) == requested_days
        and [row["date"] for row in rows] == [
            (start_date + timedelta(days=index)).isoformat()
            for index in range(requested_days)
        ]
        and precipitation_days == requested_days
    )

    return {
        "status": (
            "SUCCESS" if complete_precipitation
            else "PARTIAL" if precipitation_days
            else "UNAVAILABLE"
        ),
        "source": "Open-Meteo Historical Weather API (reanalysis)",
        "latitude": latitude,
        "longitude": longitude,
        "daily": rows,
        "precipitation_days_available": precipitation_days,
        "requested_days": requested_days,
        "message": (
            None if complete_precipitation
            else f"Rainfall coverage is incomplete: {precipitation_days} of {requested_days} requested days have valid precipitation data."
        ),
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

    except HTTPException as exc:
        weather = {
            "daily": [],
            "source": "Unavailable",
            "status": "UNAVAILABLE",
            "precipitation_days_available": 0,
            "message": str(exc.detail),
        }

    daily = weather.get("daily", [])

    rainfall = [
        row["precipitation_mm"]
        for row in daily
        if isinstance(row.get("precipitation_mm"), (int, float))
        and not isinstance(row.get("precipitation_mm"), bool)
        and isfinite(float(row["precipitation_mm"]))
    ]

    total_rainfall = (
        round(sum(rainfall), 2)
        if weather.get("status") == "SUCCESS" else None
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

    try:
        initialize_earth_engine()
        satellite_radar_evidence = get_sentinel1_summary(
            latitude=request.latitude,
            longitude=request.longitude,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            field_boundary=request.field_boundary,
        )
    except Exception:
        satellite_radar_evidence = {
            "status": "UNAVAILABLE",
            "message": "Sentinel-1 SAR evidence is unavailable. Check Earth Engine access and try again.",
            "source": "COPERNICUS/S1_GRD",
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "image_count": 0,
            "vv_mean_db": None,
            "vh_mean_db": None,
            "orbit_pass": None,
            "geometry_type": (
                "Polygon" if request.field_boundary is not None
                else "Point buffer (100 m)"
            ),
        }

    satellite_available = (
        satellite.get("status") == "SUCCESS"
        and satellite.get("ndvi_mean") is not None
    )

    satellite_visualizations = {
        "status": "UNAVAILABLE",
        "message": "Satellite visualizations could not be generated.",
        "source": "COPERNICUS/S2_SR_HARMONIZED",
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "image_count": satellite.get("image_count"),
    }

    if request.field_boundary is None:
        satellite_visualizations["message"] = (
            "Draw and submit the farm polygon to generate field-clipped imagery."
        )
    else:
        try:
            initialize_earth_engine()
            generated = get_satellite_visualizations(
                latitude=request.latitude,
                longitude=request.longitude,
                start_date=request.start_date.isoformat(),
                end_date=request.end_date.isoformat(),
                field_boundary=request.field_boundary,
            )
            if generated.get("status") == "SUCCESS":
                image_id = _store_satellite_images(generated)
                satellite_visualizations = {
                    "status": "SUCCESS",
                    "source": generated["source"],
                    "start_date": generated["start_date"],
                    "end_date": generated["end_date"],
                    "image_count": generated["image_count"],
                    "geometry_type": generated["geometry_type"],
                    "thumbnail_dimension": generated["thumbnail_dimension"],
                    "true_colour_url": (
                        f"/api/satellite/images/{image_id}/true-colour"
                    ),
                    "ndvi_url": f"/api/satellite/images/{image_id}/ndvi",
                    "ndvi_legend": generated["ndvi_legend"],
                }
                # Generate a same-length reference composite immediately before
                # the selected period so users can visually compare conditions.
                period_days = (request.end_date - request.start_date).days + 1
                before_end = request.start_date - timedelta(days=1)
                before_start = before_end - timedelta(days=period_days - 1)
                before_visualizations = {
                    "status": "UNAVAILABLE",
                    "message": "A pre-period Sentinel-2 comparison is unavailable.",
                    "start_date": before_start.isoformat(),
                    "end_date": before_end.isoformat(),
                    "source": generated["source"],
                }
                try:
                    before_generated = get_satellite_visualizations(
                        latitude=request.latitude,
                        longitude=request.longitude,
                        start_date=before_start.isoformat(),
                        end_date=before_end.isoformat(),
                        field_boundary=request.field_boundary,
                    )
                    if before_generated.get("status") == "SUCCESS":
                        before_image_id = _store_satellite_images(before_generated)
                        before_visualizations = {
                            "status": "SUCCESS",
                            "source": before_generated["source"],
                            "start_date": before_generated["start_date"],
                            "end_date": before_generated["end_date"],
                            "image_count": before_generated["image_count"],
                            "geometry_type": before_generated["geometry_type"],
                            "true_colour_url": f"/api/satellite/images/{before_image_id}/true-colour",
                            "ndvi_url": f"/api/satellite/images/{before_image_id}/ndvi",
                        }
                    else:
                        before_visualizations.update({
                            key: value for key, value in before_generated.items()
                            if key not in {"true_colour_png", "ndvi_png"}
                        })
                except Exception:
                    pass
                satellite_visualizations["before_period"] = before_visualizations
            else:
                satellite_visualizations = {
                    key: value for key, value in generated.items()
                    if key not in {"true_colour_png", "ndvi_png"}
                }
        except Exception:
            satellite_visualizations = {
                "status": "UNAVAILABLE",
                "message": (
                    "Satellite images are unavailable. Check Earth Engine access "
                    "and try running the assessment again."
                ),
                "source": "COPERNICUS/S2_SR_HARMONIZED",
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "image_count": satellite.get("image_count"),
            }

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

    # Keep one authoritative current-period NDVI: the primary assessment
    # observation also displayed in the satellite evidence card.
    authoritative_ndvi = satellite.get("ndvi_mean")
    current_period = historical_comparison.get("current_period")
    if isinstance(current_period, dict):
        current_period["ndvi_mean"] = authoritative_ndvi
        for key in ("status", "image_count", "start_date", "end_date", "source", "geometry_type"):
            if key in satellite:
                current_period[key] = satellite[key]
    historical_average_ndvi = historical_comparison.get("historical_average_ndvi")
    if (isinstance(authoritative_ndvi, (int, float))
            and isinstance(historical_average_ndvi, (int, float))):
        historical_comparison["ndvi_change"] = round(
            authoritative_ndvi - historical_average_ndvi, 4
        )
        historical_comparison["status"] = "SUCCESS"
    else:
        historical_comparison["ndvi_change"] = None
        historical_comparison["status"] = (
            "SUCCESS" if isinstance(historical_average_ndvi, (int, float))
            else "INSUFFICIENT_DATA"
        )
        if not isinstance(authoritative_ndvi, (int, float)):
            historical_comparison["message"] = (
                "Current NDVI is unavailable; available historical periods "
                "and their average are retained for reference."
            )

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
            "geometry_type": (
                "Polygon" if request.field_boundary is not None
                else "Point buffer (100 m)"
            ),
        },

        "weather_summary": {
            "source": weather.get("source", "Unavailable"),
            "status": weather.get("status", "UNAVAILABLE"),
            "days_returned": weather.get("precipitation_days_available", 0),
            "requested_days": weather.get("requested_days"),
            "total_precipitation_mm": total_rainfall,
            "message": weather.get("message"),
        },

        "satellite_evidence": satellite,

        "satellite_radar_evidence": satellite_radar_evidence,

        "satellite_visualizations": satellite_visualizations,

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
    _validate_observation_dates(start_date, end_date)

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
    if not isinstance(values, (list, tuple)):
        return None
    return values[index] if index < len(values) else None


def _date_in_year(value, year):
    try:
        return value.replace(year=year)
    except ValueError:
        import calendar

        day = min(value.day, calendar.monthrange(year, value.month)[1])
        return value.replace(year=year, day=day)


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
        historical_start = _date_in_year(start_date, target_year)
        historical_end = _date_in_year(end_date, end_date.year - offset)

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
                and not isinstance(row.get("precipitation_mm"), bool)
                and isfinite(float(row["precipitation_mm"]))
            ]

            expected_days = (historical_end - historical_start).days + 1
            expected_dates = [
                (historical_start + timedelta(days=index)).isoformat()
                for index in range(expected_days)
            ]
            if (
                len(values) == expected_days
                and len(historical_weather.get("daily", [])) == expected_days
                and [row.get("date") for row in historical_weather.get("daily", [])]
                == expected_dates
            ):
                historical_periods.append({
                    "year": target_year,
                    "total_rainfall_mm": round(sum(values), 2),
                    "days_returned": len(values),
                    "start_date": historical_start.isoformat(),
                    "end_date": historical_end.isoformat(),
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
        and rainfall_baseline > 0
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
            "indicators": {
                "current_ndvi": current_ndvi,
                "historical_average_ndvi": baseline_ndvi,
                "ndvi_change_percent": ndvi_change_percent,
                "current_rainfall_mm": current_rainfall,
                "historical_average_rainfall_mm": rainfall_baseline,
                "rainfall_change_percent": rainfall_change_percent,
                "satellite_images": image_count,
                "historical_ndvi_years": historical_years,
                "historical_rainfall_years": rainfall_years,
            },
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
