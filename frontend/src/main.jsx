import { jsPDF } from "jspdf";
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

  state_name: "Maharashtra",
  district_name: "Pune",
  crop_name: "Soybean",
  season: "Kharif",
  benchmark_year: 2022,
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
        benchmark_year: Number(form.benchmark_year),
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

function downloadFarmerReport() {
  if (!result) return;

  const pdf = new jsPDF("p", "mm", "a4");

  const W = 210;
  const H = 297;
  const M = 17;
  const CW = W - M * 2;
  const field = result.field || {};
  const weather = result.weather_summary || {};
  const satellite = result.satellite_evidence || {};
  const history = result.historical_comparison || {};
  const yieldData = result.historical_yield_benchmark || {};
  const assessment = result.assessment || {};

  let y = 20;

  const crop = String(field.crop || "Farm");
  const reportDate = new Date().toLocaleDateString("en-IN");
  const reportId =
    "SC-" + Date.now().toString().slice(-8);

  function text(value, x, yy, size = 10, style = "normal", color = [45, 55, 50]) {
    pdf.setFont("helvetica", style);
    pdf.setFontSize(size);
    pdf.setTextColor(...color);
    pdf.text(String(value ?? "Not available"), x, yy);
  }

  function paragraph(value, options = {}) {
    const size = options.size || 9.5;
    const lineHeight = options.lineHeight || 5;
    const indent = options.indent || 0;

    pdf.setFont("helvetica", "normal");
    pdf.setFontSize(size);

    const lines = pdf.splitTextToSize(
      String(value ?? "Not available"),
      CW - indent
    );

    if (y + lines.length * lineHeight + 5 > 275) {
      pdf.addPage();
      y = 22;
    }

    pdf.text(lines, M + indent, y);
    y += lines.length * lineHeight + 5;
  }

  function heading(number, title) {
    if (y + 17 > 270) {
      pdf.addPage();
      y = 22;
    }

    y += 4;

    pdf.setFillColor(226, 241, 231);
    pdf.roundedRect(M, y - 6, 8, 8, 2, 2, "F");

    text(number, M + 2.1, y, 8, "bold", [24, 105, 68]);
    text(title, M + 12, y, 12, "bold", [28, 65, 46]);

    y += 9;
  }

  function labelValue(label, value) {
    const val = String(value ?? "Not available");

    if (y + 12 > 275) {
      pdf.addPage();
      y = 22;
    }

    text(label, M, y, 8, "normal", [110, 120, 113]);
    text(val, M, y + 5, 10, "bold", [35, 48, 40]);
    y += 12;
  }

  function metricCard(x, yy, width, label, value, note) {
    pdf.setFillColor(242, 248, 243);
    pdf.roundedRect(x, yy, width, 27, 3, 3, "F");

    text(label, x + 4, yy + 7, 8, "normal", [90, 110, 95]);
    text(value, x + 4, yy + 16, 13, "bold", [25, 105, 65]);
    text(note, x + 4, yy + 22, 7, "normal", [105, 115, 108]);
  }

  function drawNDVIChart() {
    const periods = [];

    (history.historical_periods || []).forEach((p) => {
      if (p.ndvi_mean != null) {
        periods.push({
          year: String(p.year),
          value: Number(p.ndvi_mean),
        });
      }
    });

    const current = history.current_period?.ndvi_mean;

    if (current != null) {
      periods.push({
        year: String(
          history.current_period.start_date?.slice(0, 4) ||
          "Current"
        ),
        value: Number(current),
      });
    }

    if (!periods.length) {
      paragraph("No historical NDVI chart is available.");
      return;
    }

    if (y + 65 > 275) {
      pdf.addPage();
      y = 22;
    }

    const chartY = y;
    const chartH = 40;
    const chartW = CW;
    const maxValue = Math.max(
      1,
      ...periods.map((p) => p.value)
    );

    pdf.setFillColor(247, 249, 247);
    pdf.roundedRect(M, chartY, chartW, 55, 3, 3, "F");

    const gap = chartW / periods.length;
    const barWidth = Math.min(17, gap * 0.48);

    periods.forEach((p, i) => {
      const barHeight = Math.max(
        1,
        (p.value / maxValue) * chartH
      );

      const x = M + gap * i + (gap - barWidth) / 2;
      const barY = chartY + 42 - barHeight;

      pdf.setFillColor(45, 145, 91);
      pdf.roundedRect(
        x,
        barY,
        barWidth,
        barHeight,
        1.5,
        1.5,
        "F"
      );

      text(
        p.value.toFixed(3),
        x - 2,
        barY - 3,
        7,
        "bold",
        [35, 75, 48]
      );

      text(
        p.year,
        x - 2,
        chartY + 49,
        7,
        "normal",
        [75, 85, 78]
      );
    });

    y += 62;
  }

  // PAGE 1: COVER
  pdf.setFillColor(20, 83, 53);
  pdf.rect(0, 0, W, 100, "F");

  text("SATYACOVER", M, 24, 12, "bold", [255, 255, 255]);

  text(
    "FARM EVIDENCE",
    M,
    47,
    23,
    "bold",
    [255, 255, 255]
  );

  text(
    "REPORT",
    M,
    59,
    23,
    "bold",
    [255, 255, 255]
  );

  text(
    "Understanding your farm through satellite and weather data",
    M,
    72,
    9,
    "normal",
    [225, 242, 229]
  );

  y = 117;

  heading("01", "Your farm at a glance");

  labelValue("Crop", crop);
  labelValue(
    "Observation period",
    `${field.start_date || "N/A"} to ${field.end_date || "N/A"}`
  );

  labelValue(
    "Farm location",
    `${field.latitude ?? "N/A"}, ${field.longitude ?? "N/A"}`
  );

  labelValue(
    "Farm boundary",
    satellite.geometry_type === "Polygon"
      ? "Farm polygon analysed"
      : "Boundary not confirmed"
  );

  y += 3;

  const rainfall =
    weather.total_precipitation_mm != null
      ? `${Number(weather.total_precipitation_mm).toFixed(1)} mm`
      : "N/A";

  const ndvi =
    satellite.ndvi_mean != null
      ? Number(satellite.ndvi_mean).toFixed(4)
      : "N/A";

  metricCard(
    M,
    y,
    CW / 2 - 2,
    "TOTAL RAINFALL",
    rainfall,
    "During selected period"
  );

  metricCard(
    M + CW / 2 + 2,
    y,
    CW / 2 - 2,
    "VEGETATION READING",
    ndvi,
    "Satellite NDVI"
  );

  y += 38;

  pdf.setFillColor(255, 247, 225);
  pdf.roundedRect(M, y, CW, 29, 3, 3, "F");

  text(
    "IMPORTANT: THIS IS AN EVIDENCE REPORT",
    M + 5,
    y + 8,
    9,
    "bold",
    [130, 85, 20]
  );

  pdf.setFont("helvetica", "normal");
  pdf.setFontSize(8);
  pdf.setTextColor(105, 85, 55);

  pdf.text(
    pdf.splitTextToSize(
      "This report shares observations from satellite images, rainfall records and historical data. It does not confirm crop damage or insurance eligibility.",
      CW - 10
    ),
    M + 5,
    y + 15
  );

  text(
    `Report ID: ${reportId}`,
    M,
    270,
    8,
    "normal",
    [100, 110, 103]
  );

  text(
    `Generated: ${reportDate}`,
    M,
    277,
    8,
    "normal",
    [100, 110, 103]
  );

  // PAGE 2: WEATHER AND SATELLITE
  pdf.addPage();
  y = 22;

  heading("02", "Rainfall information");

  labelValue("Total rainfall", rainfall);
  labelValue("Weather records", weather.days_returned);
  labelValue("Data source", weather.source);

  paragraph(
    "What does this mean? This is the rainfall recorded during the selected dates. Rain can help crops grow, but too much or too little rain may affect them. The total rainfall alone cannot tell us whether your field was damaged."
  );

  heading("03", "What the satellite observed");

  labelValue("Vegetation reading (NDVI)", ndvi);
  labelValue("Satellite images", satellite.image_count);
  labelValue("Satellite data status", satellite.status);

  paragraph(
    "What is NDVI? Satellites use light reflected by plants to calculate this reading. It helps us understand how green the vegetation appears. It is not a direct measurement of crop production or crop loss."
  );

  heading("04", "Comparison with previous years");

  // Keep the complete historical comparison on one page.
if (y + 145 > 275) {
  pdf.addPage();
  y = 22;
}

  if (history.status === "SUCCESS") {
    labelValue(
      "Current vegetation reading",
      history.current_period?.ndvi_mean != null
        ? Number(history.current_period.ndvi_mean).toFixed(4)
        : "N/A"
    );

    labelValue(
      "Previous years' average",
      history.historical_average_ndvi != null
        ? Number(history.historical_average_ndvi).toFixed(4)
        : "N/A"
    );

    labelValue(
      "Difference from average",
      history.ndvi_change != null
        ? `${Number(history.ndvi_change) > 0 ? "+" : ""}${Number(history.ndvi_change).toFixed(4)}`
        : "N/A"
    );

    // Keep the NDVI chart and its explanation together.
if (y + 100 > 275) {
  pdf.addPage();
  y = 22;
}
    text("Vegetation reading by year", M, y, 9, "bold");
    y += 6;

    drawNDVIChart();

    const change = Number(history.ndvi_change);

    paragraph(
      change < 0
        ? "The current vegetation reading is lower than the available previous-years average for the same calendar period."
        : change > 0
          ? "The current vegetation reading is higher than the available previous-years average for the same calendar period."
          : "The current vegetation reading is equal to the available previous-years average."
    );

    paragraph(
      "Changes between years can happen because of planting dates, crop growth stage, rainfall and satellite observation conditions. A lower reading does not by itself prove crop loss."
    );
  } else {
    paragraph(
      "A comparison with previous years could not be completed because sufficient historical satellite observations were unavailable."
    );
  }

  // PAGE 3: AI AND RECOMMENDATIONS
  pdf.addPage();
  y = 22;

  heading("05", "AI historical yield information");

  if (yieldData.status === "SUCCESS") {
    metricCard(
      M,
      y,
      CW,
      "HISTORICAL YIELD BENCHMARK",
      `${Number(yieldData.predicted_yield).toFixed(4)} tonnes/ha`,
      "AI model: XGBoost"
    );

    y += 34;

    paragraph(
      "What does this number mean? The AI model estimates a historical yield benchmark using crop and district information. It is not the actual production or measured yield of your individual farm."
    );
  } else {
    paragraph(
      "The AI historical yield benchmark could not be generated for this assessment."
    );
  }

  heading("06", "What should you understand?");

  paragraph(
    "SatyaCover has collected rainfall information and satellite observations for your selected farm and dates. It has also compared vegetation readings with previous years and, where available, generated a historical yield benchmark."
  );

  paragraph(
    "These observations can help you investigate your field. However, they do not yet establish whether your farm suffered crop loss or how much production was lost."
  );

  heading("07", "What can you do next?");

  paragraph(
    "1. Visit your field and check the condition of your crops."
  );

  paragraph(
    "2. Take clear photographs of any visible crop damage."
  );

  paragraph(
    "3. Keep records of your sowing date, crop type and farming activities."
  );

  paragraph(
    "4. Discuss the observations with your local agricultural officer or relevant insurance authority."
  );

  heading("08", "Important notice");

  pdf.setFillColor(255, 247, 225);
  pdf.roundedRect(M, y - 4, CW, 16, 3, 3, "F");

  text(
    assessment.status || "LOSS ASSESSMENT PENDING",
    M + 4,
    y + 5,
    9,
    "bold",
    [135, 85, 20]
  );

  y += 19;

  paragraph(
    "This report is generated by the SatyaCover hackathon prototype for informational purposes. It is not an official crop-loss certificate, insurance approval, claim decision or payout guarantee. Satellite readings, rainfall and historical yield estimates require further verification."
  );

  // FOOTERS AND PAGE NUMBERS
  const totalPages = pdf.getNumberOfPages();

  for (let page = 1; page <= totalPages; page++) {
    pdf.setPage(page);

    pdf.setDrawColor(220, 228, 221);
    pdf.line(M, 284, W - M, 284);

    text(
      "SatyaCover | Farm Evidence Report",
      M,
      290,
      8,
      "normal",
      [100, 110, 103]
    );

    const pageText = `Page ${page} of ${totalPages}`;

    pdf.setFontSize(8);
    pdf.setFont("helvetica", "normal");

    pdf.text(
      pageText,
      W - M,
      290,
      { align: "right" }
    );
  }

  const safeCrop = crop.replace(/[^a-z0-9]/gi, "_");

  pdf.save(
    `SatyaCover_${safeCrop}_Farmer_Report.pdf`
  );
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
  <strong>Field boundary verification</strong>
  <p>
    Draw and save the actual farm boundary before running
    an assessment. The selected polygon is used for satellite
    analysis instead of a 100-metre point buffer.
  </p>
  <p>
    Ensure the boundary accurately represents the field you
    have permission to analyze. Satellite and weather evidence
    still requires validation before drawing conclusions about
    crop loss.
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

                <button
  type="button"
  onClick={downloadFarmerReport}
  className="download-report-btn"
>
  Download Farmer Report (PDF)
</button>

                
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

<h3>AI Crop Yield Benchmark · XGBoost</h3>

{result.historical_yield_benchmark?.status === "SUCCESS" ? (
  <div className="metric-grid">
    <div className="metric">
      <small>Predicted historical yield</small>
      <strong>
        {Number(
          result.historical_yield_benchmark.predicted_yield
        ).toFixed(4)} tonnes/ha
      </strong>
    </div>

    <div className="metric">
      <small>Model</small>
      <strong>XGBoost</strong>
    </div>
  </div>
) : (
  <p className="muted">
    Yield benchmark unavailable. Check the crop, district,
    season and benchmark year.
  </p>
)}

<p className="muted">
  This is a historical district/crop yield benchmark,
  not a farm-level yield or crop-loss prediction.
</p>

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
