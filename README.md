# SatyaCover MVP

SatyaCover is a local prototype that combines farm location, weather and satellite vegetation evidence for review. It does not make insurance or crop-loss decisions.

## Current features

- React/Vite dashboard with a Leaflet map, coordinate entry and farm-polygon drawing; assessments without a polygon use a 100-metre point buffer.
- FastAPI assessment API with current and historical rainfall comparisons from the Open-Meteo archive API.
- Google Earth Engine Sentinel-2 surface-reflectance assessment using `COPERNICUS/S2_SR_HARMONIZED`, including cloud-masked NDVI and historical NDVI comparison.
- Farm-polygon-clipped Sentinel-2 true-colour and NDVI previews, with observation metadata and an NDVI legend when usable imagery is available.
- Explainable crop-stress screening based on vegetation and rainfall evidence.
- Provisional LOW/MODERATE/HIGH crop-stress concern labels and a user-entered illustrative loss/payout range calculator. Calculator results are hypothetical arithmetic only and are not derived from satellite evidence or official insurance rules.
- Downloadable farmer evidence PDF with available metrics, comparisons, satellite images and limitations.
- Optional historical district/crop yield benchmark when the local model artifact is present.
- FastAPI interactive documentation at `http://127.0.0.1:8000/docs`.

## Important interpretation limits

Crop-stress screening categories use provisional thresholds and require field verification. They are not a validated crop-loss assessment and do not establish actual crop loss, insurance eligibility or payout.

NDVI is vegetation evidence derived from reflected light; it is not direct proof of crop loss or a direct measurement of production. Cloud cover, observation quality, crop stage, planting dates and field conditions can affect interpretation. Rainfall variation alone does not prove crop damage.

Historical yield is a district/crop benchmark, not measured farm-level yield or confirmed loss. Weather values come from reanalysis data and may not match conditions at a specific field. Missing weather or satellite evidence is reported as unavailable; it is not treated as zero.

## Future scope

- Validated farm-level yield-loss prediction.
- Sentinel-1 synthetic aperture radar (SAR) evidence.
- Actual PMFBY integration and official payout calculation.
- Database-backed operation and production deployment.

These are not implemented features. The current illustrative calculator does not verify insurance coverage, eligibility, or payout.

## Requirements

- Python 3.11 recommended.
- Node.js 20 or later recommended.
- Internet access for Open-Meteo and Google Earth Engine requests.
- A Google Cloud project registered for Earth Engine and an account with access to that project for live satellite analysis.

## Backend setup (Windows PowerShell)

In the first terminal, from the project root:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The requirements install the Earth Engine Python client (`earthengine-api`) and the backend/model runtime dependencies.

### Earth Engine setup

The backend currently initializes Earth Engine with project ID `satyacover`, configured in `backend/app/earth_engine.py`. The Google Cloud project must be registered for Earth Engine, and the Google account used locally must have permission to use it.

Authenticate once from the activated backend environment:

```powershell
earthengine authenticate
```

Complete the browser authentication flow. The Earth Engine client stores credentials in the user profile outside this repository. Do not copy credentials, service-account keys or tokens into the project or commit them. If you use a different authorized Cloud project, update `PROJECT_ID` in `backend/app/earth_engine.py` to that project's ID.

Verify authentication and the configured project without printing credentials:

```powershell
python -c "import ee; ee.Initialize(project='satyacover'); print('Earth Engine initialized')"
```

Start the API:

```powershell
uvicorn app.main:app --reload
```

If PowerShell blocks virtual-environment activation, run these from `backend` instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The core API can start without working Earth Engine access; satellite evidence and imagery will be marked unavailable until authentication, project access and usable scenes are available.

## Frontend setup

In a second terminal, from the project root:

```powershell
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite, usually `http://localhost:5173`.

Create a production build with:

```powershell
npm run build
```

## Smoke checks

- Backend health: `http://127.0.0.1:8000/health`
- API documentation: `http://127.0.0.1:8000/docs`
- In the dashboard, enter a location, select dates and crop, optionally draw the farm polygon, then choose **Run assessment**.
- Satellite thumbnails require a submitted polygon and usable Sentinel-2 scenes for the selected observation period.

For a smoke-test location only, Pune coordinates are latitude `18.5204`, longitude `73.8567`. These are city coordinates, not a verified farm boundary; use a field you have permission to analyze.

## Optional historical yield benchmark

The optional benchmark endpoint loads `models/crop_yield_xgboost_no_area_candidate.joblib`. That model artifact is not included in Git. Without the local artifact, the assessment still runs and reports the benchmark as unavailable. Any returned value is a historical district/crop benchmark, not farm yield or loss.

## Data sources and further reading

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [Google Earth Engine authentication](https://developers.google.com/earth-engine/guides/auth)
- [Earth Engine data catalog](https://developers.google.com/earth-engine/datasets)
