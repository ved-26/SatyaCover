import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import {
  MapContainer,
  TileLayer,
  Marker,
  useMapEvents,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import L from "leaflet";
import "leaflet-draw";
import "leaflet-draw/dist/leaflet.draw.css";

const API = "http://127.0.0.1:8000";

function MapPicker({ position, onLocationSelect }) {
  useMapEvents({
    click(event) {
      onLocationSelect({
        latitude: event.latlng.lat.toFixed(6),
        longitude: event.latlng.lng.toFixed(6),
      });
    },
  });

  return <Marker position={position} />;
}

function MapUpdater({ position }) {
  const map = useMap();

  React.useEffect(() => {
    map.setView(position);
  }, [map, position[0], position[1]]);

  return null;
}


function FieldBoundaryDrawer({ onBoundaryChange }) {
  const map = useMap();

  React.useEffect(() => {
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    const drawControl = new L.Control.Draw({
      draw: {
        polygon: {
          allowIntersection: false,
          showArea: true,
        },
        rectangle: false,
        polyline: false,
        circle: false,
        circlemarker: false,
        marker: false,
      },
      edit: {
      featureGroup: drawnItems,
      edit: {},
      remove: true,
    },
    });

    map.addControl(drawControl);

    function updateBoundary() {
      const layers = drawnItems.getLayers();

      if (layers.length === 0) {
        onBoundaryChange(null);
        return;
      }

      const geoJson = layers[0].toGeoJSON();
      onBoundaryChange(geoJson.geometry);
    }

    function handleCreated(event) {
      drawnItems.clearLayers();
      drawnItems.addLayer(event.layer);
      updateBoundary();
    }

    map.on(L.Draw.Event.CREATED, handleCreated);
    map.on(L.Draw.Event.EDITED, updateBoundary);
    map.on(L.Draw.Event.DELETED, updateBoundary);

    return () => {
      map.off(L.Draw.Event.CREATED, handleCreated);
      map.off(L.Draw.Event.EDITED, updateBoundary);
      map.off(L.Draw.Event.DELETED, updateBoundary);
      map.removeControl(drawControl);
      map.removeLayer(drawnItems);
    };
  }, [map, onBoundaryChange]);

  return null;
}


function App() {
  const [form, setForm] = useState({
    latitude: "18.5204",
    longitude: "73.8567",
    crop: "soybean",
    start_date: "2026-06-01",
    end_date: "2026-09-30",
  });

  const [fieldBoundary, setFieldBoundary] = useState(null);

  const position = [
    Number(form.latitude) || 0,
    Number(form.longitude) || 0,
  ];

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ndviResult, setNdviResult] = useState(null);

  
function validateAssessmentDates(startDate, endDate) {
  if (!startDate || !endDate) {
    return "Please select both observation dates.";
  }

  if (endDate < startDate) {
    return "End date must be on or after the start date.";
  }

  const start = new Date(`${startDate}T00:00:00`);
  const end = new Date(`${endDate}T00:00:00`);
  const days = Math.round((end - start) / (1000 * 60 * 60 * 24)) + 1;

  if (days > 366) {
    return "Please select a period of 366 days or less.";
  }

  return "";
}

  function update(event) {
    setForm({
      ...form,
      [event.target.name]: event.target.value,
    });
  }


  async function runAssessment(event) {
    event.preventDefault();
    const dateError = validateAssessmentDates(
  form.start_date,
  form.end_date
);

if (dateError) {
  setResult(null);
  setError(dateError);
  return;
}

if (!fieldBoundary) {
  setResult(null);
  setError(
    "Please draw and save the farm boundary on the map before running the assessment."
  );
  return;
}

    setLoading(true);
    setError("");
    setResult(null);
    setNdviResult(null);


    try {
      const response = await fetch(`${API}/api/assess`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
  ...form,
  latitude: Number(form.latitude),
  longitude: Number(form.longitude),
  field_boundary: fieldBoundary,
}),
      });

      const body = await response.json();

      if (!response.ok) {
        throw new Error(
          body.detail || "Assessment request failed"
        );
      }

      setResult(body);
      
    } catch (err) {
      setError(
        `${err.message}. Check that the FastAPI backend is running at ${API}.`
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        async function runAssessment(event)<div className="brand-mark">SC</div>

        <div>
          <div className="brand-name">SatyaCover</div>
          <div className="brand-caption">
            Evidence for crop-loss assessment
          </div>
        </div>

        <span className="top-pill">MVP · Prototype</span>
      </header>

      <main>
        <section className="hero">
          <div className="eyebrow">
            AI + SATELLITE + WEATHER
          </div>

          <h1>
            Understand what happened
            <br />
            to your crop.
          </h1>

          <p>
            Analyze a field location and time period to prepare
            an evidence-led crop-health assessment.
          </p>
        </section>

        <div className="content-grid">
          <section className="panel">
            <div className="section-kicker">
              01 / FIELD DETAILS
            </div>

            <h2>Start an assessment</h2>

            <p className="muted">
              Enter coordinates for a field you have permission
              to analyze.
            </p>

            <form onSubmit={runAssessment}>
              <label>
                Crop type

                <select
                  name="crop"
                  value={form.crop}
                  onChange={update}
                >
                  <option value="rice">Rice</option>
                  <option value="wheat">Wheat</option>
                  <option value="cotton">Cotton</option>
                  <option value="soybean">Soybean</option>
                  <option value="sugarcane">Sugarcane</option>
                  <option value="other">Other / not specified</option>
                </select>
              </label>

              <div className="two-cols">
                <label>
                  Latitude

                  <input
                    name="latitude"
                    type="number"
                    step="any"
                    min="-90"
                    max="90"
                    required
                    value={form.latitude}
                    onChange={update}
                  />
                </label>

                <label>
                  Longitude

                  <input
                    name="longitude"
                    type="number"
                    step="any"
                    min="-180"
                    max="180"
                    required
                    value={form.longitude}
                    onChange={update}
                  />
                </label>
              </div>

              {/* Interactive field location map */}
              <div className="map-section">
                <label>Select field location on map</label>

                <p className="map-help">
                  Click on the map to update the field coordinates.
                </p>

                <MapContainer
                  center={position}
                  zoom={12}
                  scrollWheelZoom={true}
                  className="field-map"
                >
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />

                  
<MapUpdater position={position} />

<MapPicker
  position={position}
  onLocationSelect={(coords) =>
    setForm((previous) => ({
      ...previous,
      ...coords,
    }))
  }
/>

<FieldBoundaryDrawer
  onBoundaryChange={setFieldBoundary}
/>

                </MapContainer>
                
<div className="boundary-status">
  {fieldBoundary ? (
    <p>
      <strong>Farm boundary selected.</strong>{" "}
      Polygon coordinates are ready for assessment.
    </p>
  ) : (
    <p>
      No farm boundary selected. Use the polygon tool on the map
      to outline the field you have permission to analyze.
    </p>
  )}
</div>

              </div>

              <div className="two-cols">
                <label>
                  Start date

                  <input
                    name="start_date"
                    type="date"
                    required
                    value={form.start_date}
                    onChange={update}
                  />
                </label>

                <label>
                  End date

                  <input
                    name="end_date"
                    type="date"
                    required
                    value={form.end_date}
                    onChange={update}
                  />
                </label>
              </div>

              
<div className="coordinate-note">
  <strong>Field boundary not verified</strong>
  <p>
    The map currently selects a point, not the outline of the
    farm. Satellite analysis uses a 100-metre buffer around that
    point, which may include roads, nearby fields, buildings,
    or other land.
  </p>
  <p>
    For a field-specific assessment, provide the actual field
    boundary and ensure the satellite analysis uses that geometry.
  </p>
</div>


<div className="evidence-note">
  <strong>Crop-season validation required</strong>
  <p>
    Confirm that the observation dates match the selected crop's
    actual growing season in the field's location. Matching
    calendar dates across years does not guarantee matching crop
    growth stages.
  </p>
</div>


              <button disabled={loading} type="submit">
                {loading ? "Analyzing…" : "Run assessment"}
                <span>→</span>
              </button>
            </form>
          </section>

          <section className="panel result-panel">
            <div className="section-kicker">
              02 / EVIDENCE REPORT
            </div>

            <h2>Assessment results</h2>

            {!result && !error && (
              <div className="empty-state">
                <div className="empty-icon">⌁</div>

                <h3>Your report will appear here</h3>

                <p>
                  Run an assessment to retrieve historical
                  weather data and see the current prototype status.
                </p>

                <div className="mini-steps">
                  <span>01 Weather</span>
                  <span>02 Satellite</span>
                  <span>03 Explanation</span>
                </div>
              </div>
            )}

            {error && (
              <div className="error-box">
                <strong>Could not run assessment</strong>
                <p>{error}</p>
              </div>
            )}

            {result && (
              <div className="report">
                <div className="warning-banner">
                  PROTOTYPE · EVIDENCE REQUIRES VALIDATION
                </div>

                <div className="status-row">
                  <span className="status-dot"></span>

                  <div>
                    <strong>{result.assessment.status}</strong>
                    <small>Current evidence status</small>
                  </div>
                </div>

                
<div className="metric-grid">
  <div className="metric">
    <small>Total rainfall in period</small>
    <strong>
      {result.weather_summary.total_precipitation_mm == null
        ? "Unavailable"
        : `${Number(
            result.weather_summary.total_precipitation_mm
          ).toFixed(1)} mm`}
    </strong>
  </div>

  <div className="metric">
    <small>Weather records</small>
    <strong>
      {result.weather_summary.days_returned ?? "Unavailable"}
    </strong>
  </div>
</div>

<div className="evidence-note">
  <strong>How to interpret rainfall</strong>
  <p>
    Rainfall provides supporting weather evidence for the selected
    observation period. Its effect on a crop depends on rainfall
    timing, soil drainage, crop growth stage, and local conditions.
    Total rainfall alone does not establish flooding, crop damage,
    or crop loss.
  </p>
  <p className="muted">
    Weather source:{" "}
    {result.weather_summary.source || "Source not specified"}.
    Values represent the returned weather data for the selected period.
  </p>
</div>


                

<h3>Satellite evidence · Sentinel-2</h3>

{!result?.satellite_evidence ? (
  <p className="muted">
    Satellite evidence is unavailable for this assessment.
  </p>
) : (
  <>
    <div className="metric-grid">
      <div className="metric">
        <small>Current mean NDVI</small>
        <strong>
          {result.satellite_evidence.ndvi_mean == null
            ? "Unavailable"
            : Number(result.satellite_evidence.ndvi_mean).toFixed(4)}
        </strong>
      </div>

      <div className="metric">
        <small>Satellite scenes</small>
        <strong>{result.satellite_evidence.image_count ?? 0}</strong>
      </div>

      <div className="metric">
        <small>Satellite status</small>
        <strong>{result.satellite_evidence.status ?? "Unknown"}</strong>
      </div>
    </div>

    <p className="muted">
      Source: {result.satellite_evidence.source ?? "Sentinel-2"}
    </p>

    <p className="muted">
      Observation period:{" "}
      {result.satellite_evidence.start_date ?? result.field?.start_date}
      {" to "}
      {result.satellite_evidence.end_date ?? result.field?.end_date}
    </p>


<h3>Historical vegetation comparison</h3>

{!result.historical_comparison ||
result.historical_comparison.status !== "SUCCESS" ? (
  <p className="muted">
    Historical comparison is unavailable. Usable current and
    historical satellite observations are required.
  </p>
) : (
  <>
    <div className="metric-grid">
      <div className="metric">
        <small>Current NDVI</small>
        <strong>
          {Number(
            result.historical_comparison.current_period.ndvi_mean
          ).toFixed(4)}
        </strong>
      </div>

      <div className="metric">
        <small>Multi-year baseline</small>
        <strong>
          {Number(
            result.historical_comparison.historical_average_ndvi
          ).toFixed(4)}
        </strong>
      </div>

      <div className="metric">
        <small>NDVI change</small>
        <strong>
          {result.historical_comparison.ndvi_change > 0 ? "+" : ""}
          {Number(
            result.historical_comparison.ndvi_change
          ).toFixed(4)}
        </strong>
      </div>
    </div>

    <p className="muted">
      Historical years available:{" "}
      {result.historical_comparison.historical_years_available}
      {" / "}
      {result.historical_comparison.historical_years_requested}
    </p>

    {result.historical_comparison.historical_periods.map((period) => (
      <p className="muted" key={period.year}>
        {period.year}:{" "}
        {period.ndvi_mean == null
          ? "NDVI unavailable"
          : `NDVI ${Number(period.ndvi_mean).toFixed(4)}`}
        {" · "}
        {period.image_count} satellite scenes
      </p>
    ))}

    <p className="muted">
      {result.historical_comparison.message}
    </p>
  </>
)}

<h3>NDVI trend by year</h3>

{result.historical_comparison?.status === "SUCCESS" && (
  <div className="ndvi-chart">
    {[
      ...result.historical_comparison.historical_periods,
      {
        year: Number(
          result.historical_comparison.current_period.start_date.slice(0, 4)
        ),
        ndvi:
          result.historical_comparison.current_period.ndvi_mean,
        image_count:
          result.historical_comparison.current_period.image_count,
      },
    ]
      .sort((a, b) => a.year - b.year)
      .map((period) => {
        const value = period.ndvi_mean ?? period.ndvi;

        return (
          <div className="ndvi-bar-item" key={period.year}>
            <strong>{value == null ? "N/A" : value.toFixed(4)}</strong>

            <div className="ndvi-bar-track">
              <div
                className="ndvi-bar"
                style={{
                  height: `${Math.max(0, Math.min(100, (value ?? 0) * 100))}%`,
                }}
              />
            </div>

            <span>{period.year}</span>
          </div>
        );
      })}
  </div>
)}

<p className="muted">
  The chart compares mean NDVI for matching calendar periods.
  Differences may reflect crop stage, weather, or observation conditions;
  they do not independently establish crop loss.
</p>


    <p className="muted">
      NDVI differences indicate vegetation changes and do not independently
      prove crop loss.
    </p>
  </>
)}

                
<h3>What this means</h3>

{result.historical_comparison?.status === "SUCCESS" ? (
  <div className="evidence-note">
    <p>
      The current mean NDVI is{" "}
      <strong>
        {Number(
          result.historical_comparison.current_period.ndvi_mean
        ).toFixed(4)}
      </strong>
      , compared with a historical average of{" "}
      <strong>
        {Number(
          result.historical_comparison.historical_average_ndvi
        ).toFixed(4)}
      </strong>
      .
    </p>

    <p>
      The difference is{" "}
      <strong>
        {result.historical_comparison.ndvi_change > 0 ? "+" : ""}
        {Number(
          result.historical_comparison.ndvi_change
        ).toFixed(4)}
      </strong>
      . This indicates that the observed vegetation index is
      {result.historical_comparison.ndvi_change < 0
        ? " lower "
        : result.historical_comparison.ndvi_change > 0
          ? " higher "
          : " equal to "}
      the historical average for the selected calendar period.
    </p>

    <p>
      Rainfall during the period was{" "}
      <strong>
        {result.weather_summary.total_precipitation_mm == null
          ? "unavailable"
          : `${Number(
              result.weather_summary.total_precipitation_mm
            ).toFixed(1)} mm`}
      </strong>
      . This is supporting weather evidence, not proof of crop damage.
    </p>

    <p>
      These observations do not independently confirm crop loss.
      Crop type, actual field boundaries, crop growth stage, and
      local conditions need to be checked before drawing conclusions.
    </p>
  </div>
) : (
  <p>{result.assessment.explanation}</p>
)}


                <h3>Next evidence needed</h3>
                <p>{result.next_step}</p>

                <div className="disclaimer">
                  {result.disclaimer}
                </div>

                <details>
                  <summary>Technical response</summary>
                  <pre>
                    {JSON.stringify(result, null, 2)}
                  </pre>
                </details>
              </div>
            )}
          </section>
        </div>

        <section className="workflow">
          <div>
            <span className="step-number">01</span>
            <strong>Field</strong>
            <small>Coordinates and crop</small>
          </div>

          <div>
            <span className="step-number">02</span>
            <strong>Observe</strong>
            <small>Satellite and weather</small>
          </div>

          <div>
            <span className="step-number">03</span>
            <strong>Compare</strong>
            <small>Historical baseline</small>
          </div>

          <div>
            <span className="step-number">04</span>
            <strong>Explain</strong>
            <small>Evidence and uncertainty</small>
          </div>
        </section>
      </main>

      <footer>
        SatyaCover · Prototype for hackathon demonstration ·
        Not an official insurance assessment
      </footer>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
