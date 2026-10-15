from datetime import date
from typing import Literal
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
    crop: Literal["rice", "wheat", "cotton", "soybean", "sugarcane", "other"] = "other"
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (self.end_date - self.start_date).days > 400:
            raise ValueError("Choose a period of 400 days or less for the MVP")
        return self


@app.get("/")
def root():
    return {"app": "SatyaCover", "status": "running", "mode": "MVP"}


@app.get("/health")
def health():
    return {"status": "ok"}


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
    # Retrieve historical weather.
    try:
        weather = get_weather(
            latitude=request.latitude,
            longitude=request.longitude,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except HTTPException:
        weather = {"daily": [], "source": "Unavailable"}

    daily = weather.get("daily", [])
    rainfall = [
        row["precipitation_mm"]
        for row in daily
        if isinstance(row.get("precipitation_mm"), (int, float))
    ]
    total_rainfall = round(sum(rainfall), 2) if rainfall else None

    # Retrieve satellite vegetation evidence.
    try:
        initialize_earth_engine()
        satellite = get_ndvi_summary(
            latitude=request.latitude,
            longitude=request.longitude,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
        )
    except Exception:
        satellite = {
            "status": "UNAVAILABLE",
            "message": "Satellite data could not be retrieved for this request.",
            "image_count": 0,
            "ndvi_mean": None,
        }

    satellite_available = (
        satellite.get("status") == "SUCCESS"
        and satellite.get("ndvi_mean") is not None
    )

    
    # Compare current vegetation with the same period last year.
    try:
        historical_comparison = compare_with_historical_baseline(
            latitude=request.latitude,
            longitude=request.longitude,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
        )
    except Exception:
        historical_comparison = {
            "status": "UNAVAILABLE",
            "ndvi_change": None,
            "message": (
                "Historical vegetation comparison could not be retrieved."
            ),
        }


    return {
        "project": "SatyaCover",
        "mode": "PROTOTYPE — satellite and weather evidence",
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
        "assessment": {
            "status": (
                "EVIDENCE AVAILABLE — LOSS ASSESSMENT PENDING"
                if satellite_available
                else "INSUFFICIENT DATA"
            ),
            "loss_severity": None,
            "confidence": None,
            "payout_estimate": None,
            "explanation": (
                "Sentinel-2 vegetation evidence is available for this "
                "location and period. Crop-loss assessment still requires "
                "a suitable historical vegetation baseline, crop and "
                "season context, and validation. NDVI alone does not "
                "prove crop loss."
                if satellite_available
                else
                "Usable satellite vegetation evidence is not available "
                "for this request. No crop-loss percentage or insurance "
                "payout is inferred from weather alone."
            ),
        },
        "next_step": (
            "Compare vegetation observations with a suitable historical "
            "baseline for the same field, crop, and growing season."
        ),
        "disclaimer": (
            "Prototype only. This is not an official crop-loss assessment, "
            "insurance decision, or payout guarantee."
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
