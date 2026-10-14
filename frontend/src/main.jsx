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

function App() {
  const [form, setForm] = useState({
    latitude: "18.5204",
    longitude: "73.8567",
    crop: "soybean",
    start_date: "2026-06-01",
    end_date: "2026-09-30",
  });

  const position = [
    Number(form.latitude) || 0,
    Number(form.longitude) || 0,
  ];

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ndviResult, setNdviResult] = useState(null);

  function update(event) {
    setForm({
      ...form,
      [event.target.name]: event.target.value,
    });
  }

  async function runAssessment(event) {
    event.preventDefault();
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
        }),
      });

      const body = await response.json();

      if (!response.ok) {
        throw new Error(
          body.detail || "Assessment request failed"
        );
      }

      setResult(body);
      // Retrieve satellite evidence for the selected field and dates.
const ndviResponse = await fetch(
  `${API}/api/ndvi?${new URLSearchParams({
    latitude: String(form.latitude),
    longitude: String(form.longitude),
    start_date: form.start_date,
    end_date: form.end_date,
  })}`
);

const ndviBody = await ndviResponse.json();

if (!ndviResponse.ok) {
  throw new Error(ndviBody.detail || "Satellite request failed");
}

setNdviResult(ndviBody);
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
        <div className="brand-mark">SC</div>

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
                </MapContainer>
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
                Example coordinates are near Pune city, not a
                verified farm boundary. Replace them with your
                selected field.
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
                    <small>Rainfall in period</small>
                    <strong>
                      {result.weather_summary.total_precipitation_mm == null
                        ? "Unavailable"
                        : `${result.weather_summary.total_precipitation_mm} mm`}
                    </strong>
                  </div>

                  <div className="metric">
                    <small>Weather records</small>
                    <strong>
                      {result.weather_summary.days_returned}
                    </strong>
                  </div>
                </div>

                
<h3>Satellite evidence · Sentinel-2</h3>

{!ndviResult ? (
  <p className="muted">
    Satellite evidence has not been loaded yet.
  </p>
) : (
  <div className="metric-grid">
    <div className="metric">
      <small>Mean NDVI</small>
      <strong>
        {ndviResult.ndvi_mean == null
          ? "Unavailable"
          : ndviResult.ndvi_mean.toFixed(4)}
      </strong>
    </div>

    <div className="metric">
      <small>Satellite scenes</small>
      <strong>{ndviResult.image_count ?? 0}</strong>
    </div>

    <div className="metric">
      <small>Satellite status</small>
      <strong>{ndviResult.status}</strong>
    </div>
  </div>
)}

{ndviResult?.message && (
  <p className="muted">{ndviResult.message}</p>
)}

{ndviResult && (
  <p className="muted">
    Source: {ndviResult.source || "Sentinel-2"}
    <br />
    Period: {ndviResult.start_date} to {ndviResult.end_date}
    <br />
    NDVI indicates vegetation conditions; it does not independently
    establish crop loss.
  </p>
)}

                <h3>What this means</h3>
                <p>{result.assessment.explanation}</p>

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
