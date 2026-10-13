# SatyaCover MVP

A local-first prototype for explainable satellite-assisted crop-loss assessment.

## Current capabilities
- React dashboard for field coordinates, crop, and analysis dates.
- FastAPI backend.
- Historical weather retrieval from Open-Meteo.
- Clearly labelled demo analysis until satellite data is connected.
- API documentation at http://127.0.0.1:8000/docs

## Important
The current demo analysis is **not an insurance decision** and does not establish actual crop loss. Satellite indicators and validated ground truth must be integrated before making real assessments. Weather data is modelled/reanalysis data and may not represent conditions at the exact field.

## Requirements
- Python 3.11 recommended
- Node.js 20+ recommended
- Internet access for weather API

## 1. Start backend (Windows PowerShell)
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If PowerShell blocks activation, use:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## 2. Start frontend in a second terminal
```powershell
cd frontend
npm install
npm run dev
```
Open the URL printed by Vite (usually http://localhost:5173).

## 3. Test
- Backend health: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs
- In the frontend, enter field coordinates and choose a date range, then click **Run assessment**.

## Suggested test coordinates
Use a field you have permission to analyze. For a quick smoke test only, you can try a location near Pune:
- Latitude: 18.5204
- Longitude: 73.8567

These are city coordinates, not a verified farm boundary.

## Next development milestones
1. Draw/select a field polygon on Leaflet and store its coordinates.
2. Integrate Sentinel-2 surface reflectance in Google Earth Engine; calculate cloud-masked NDVI time series.
3. Add historical baseline and anomaly detection, with transparent thresholds.
4. Integrate Sentinel-1 SAR as a complementary signal where useful.
5. Add evidence timeline, downloadable report, tests, and model validation.
6. Only estimate payout ranges after obtaining official policy/claim rules and validated loss calibration.

## Data-source notes
- Open-Meteo Historical Weather API: https://open-meteo.com/en/docs/historical-weather-api
- Google Earth Engine authentication: https://developers.google.com/earth-engine/guides/auth
- Earth Engine data catalog: https://developers.google.com/earth-engine/datasets
