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

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function formatNumber(value, digits = 2, suffix = "") {
  return isFiniteNumber(value)
    ? `${value.toFixed(digits)}${suffix}`
    : "Unavailable";
}

function currentAssessmentNdvi(result) {
  const value = result?.satellite_evidence?.ndvi_mean;
  return isFiniteNumber(value) ? value : null;
}

function rainfallChangePercent(current, average) {
  if (!isFiniteNumber(current) || !isFiniteNumber(average) || average <= 0) return null;
  return ((current - average) / average) * 100;
}

function currentRainfallChange(result) {
  const calculated = rainfallChangePercent(
    result?.weather_summary?.total_precipitation_mm,
    result?.historical_rainfall_comparison?.historical_average_mm,
  );
  if (isFiniteNumber(calculated)) return calculated;
  const existing = result?.crop_stress_assessment?.indicators?.rainfall_change_percent
    ?? result?.crop_stress_assessment?.rainfall_change_percent;
  if (isFiniteNumber(existing)) return existing;
  return null;
}

function ndviDifferenceFromBaseline(result, baseline) {
  const current = currentAssessmentNdvi(result);
  return isFiniteNumber(current) && isFiniteNumber(baseline) ? current - baseline : null;
}

function displayText(value, fallback = "Unavailable") {
  if (typeof value !== "string" || !value.trim()) return fallback;
  return ["undefined", "null", "nan"].includes(value.trim().toLowerCase())
    ? fallback
    : value;
}

function localISODate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function calculateIllustrativePayoutRange(insuredSum, minimumPercent, maximumPercent) {
  const values = [insuredSum, minimumPercent, maximumPercent].map((value) =>
    value === "" || value == null ? NaN : Number(value)
  );
  const [sum, minimum, maximum] = values;
  if (!values.every(Number.isFinite) || sum <= 0 || minimum < 0 || maximum > 100 || minimum > maximum) return null;
  const minimumAmount = sum * minimum / 100;
  const maximumAmount = sum * maximum / 100;
  if (!Number.isFinite(minimumAmount) || !Number.isFinite(maximumAmount)) return null;
  return { minimumAmount, maximumAmount, minimumPercent: minimum, maximumPercent: maximum };
}

function screeningConcern(category, status) {
  const normalized = String(category || "").trim().toUpperCase();
  if (!normalized || /UNAVAILABLE|INSUFFICIENT|NOT_ASSESSED/.test(normalized) || /UNAVAILABLE|INSUFFICIENT/.test(String(status || "").toUpperCase())) return "Unavailable";
  if (/HIGH|SEVERE|POSSIBLE_CROP_STRESS/.test(normalized)) return "HIGH";
  if (/MODERATE|REQUIRES_FIELD_VERIFICATION/.test(normalized)) return "MODERATE";
  if (/LOW|NO_CLEAR_STRESS_SIGNAL/.test(normalized)) return "LOW";
  return "Unavailable";
}

function screeningIndication(category) {
  const normalized = String(category || "").trim().toUpperCase();
  if (normalized === "POSSIBLE_CROP_STRESS") return "Potential crop-stress signal in available evidence";
  if (normalized === "REQUIRES_FIELD_VERIFICATION") return "Evidence requires field verification";
  if (normalized === "NO_CLEAR_STRESS_SIGNAL") return "No clear stress signal in available evidence";
  if (normalized === "INSUFFICIENT_DATA") return "Insufficient evidence to screen";
  return displayText(category);
}

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


function FieldBoundaryDrawer({ onBoundaryChange, boundary }) {
  const map = useMap();

  React.useEffect(() => {
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    if (boundary?.type === "Polygon") {
      L.geoJSON(boundary).eachLayer((layer) => drawnItems.addLayer(layer));
    }

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

function HomeLanding({ onNavigate }) {
  const capabilities = [
    ["01", "Satellite monitoring", "Review Sentinel-2 vegetation imagery and available radar evidence."],
    ["02", "Weather context", "Compare rainfall for the selected period with historical records when available."],
    ["03", "Explainable screening", "See provisional signals, their evidence, and clear field-verification guidance."],
    ["04", "Farmer report", "Download a readable PDF with sources, comparison periods, and limitations."],
  ];
  return (
    <div className="landing-page">
      <section className="landing-hero">
        <div className="landing-copy">
          <span className="eyebrow">FARM EVIDENCE, MADE CLEAR</span>
          <h1>Smarter crop monitoring.<br />Clearer insurance evidence.</h1>
          <p>Bring satellite vegetation signals, rainfall context, and historical comparisons together for a farm-focused evidence review.</p>
          <div className="landing-actions">
            <button type="button" onClick={() => onNavigate("assessment")}>Start crop assessment <span>→</span></button>
            <button type="button" className="button-secondary" onClick={() => onNavigate("dashboard")}>Explore dashboard</button>
          </div>
          <p className="landing-note">This tool provides supporting evidence. It does not confirm crop loss or decide insurance payouts.</p>
        </div>
        <div className="hero-visual" aria-label="Illustrative farm visualization">
          <div className="hero-map-grid"><div className="hero-field field-one"/><div className="hero-field field-two"/><div className="hero-field field-three"/><div className="hero-field field-four"/><div className="hero-boundary"/></div>
          <span className="visual-label">Illustrative farm visualization</span>
          <span className="visual-label-sub">Actual imagery appears only when available for a submitted field.</span>
        </div>
      </section>
      <section className="landing-capabilities">
        <div className="section-intro"><span className="section-kicker">HOW IT WORKS</span><h2>Evidence in four clear steps</h2><p>From field boundary to an understandable report.</p></div>
        <div className="capability-grid">{capabilities.map(([number, title, description]) => <article className="capability-card" key={number}><span className="capability-number">{number}</span><h3>{title}</h3><p>{description}</p></article>)}</div>
      </section>
      <section className="landing-limitations"><strong>Interpret evidence carefully</strong><p>NDVI is vegetation evidence, not direct proof of crop loss. Rainfall variation alone does not prove damage. Screening thresholds are provisional and require field verification.</p></section>
    </div>
  );
}

function DashboardOverview({ result, onNavigate }) {
  const scenes = result?.satellite_evidence?.image_count;
  const concern = screeningConcern(result?.crop_stress_assessment?.screening_category, result?.crop_stress_assessment?.status);
  const category = result?.crop_stress_assessment?.screening_category;
  const field = result?.field || {};
  return (
    <section className="dashboard-page">
      <div className="page-heading-row"><div><span className="section-kicker">OVERVIEW</span><h1>Farmer dashboard</h1><p>A clear view of farm evidence and recent activity.</p></div><button type="button" onClick={() => onNavigate("assessment")}>＋ New assessment</button></div>
      <div className="overview-grid">
        <article className="overview-card"><span>ASSESSMENT HISTORY</span><strong>Not stored</strong><small>The backend does not keep a registered farm or assessment history.</small></article>
        <article className="overview-card"><span>SATELLITE OBSERVATIONS</span><strong>{isFiniteNumber(scenes) && scenes > 0 ? scenes : "Unavailable"}</strong><small>Scene count from the latest assessment, when returned.</small></article>
        <article className="overview-card"><span>LATEST SCREENING</span><strong className={`concern-${concern.toLowerCase()}`}>{concern === "Unavailable" ? "Not assessed" : concern}</strong><small>{displayText(category, "Start an assessment to see screening.")}</small></article>
        <article className="overview-card"><span>FARMER REPORTS</span><strong>{result ? "1 available" : "No reports yet"}</strong><small>Download a report after an assessment.</small></article>
      </div>
      <div className="dashboard-columns">
        <article className="dashboard-card farm-overview-card"><div className="card-heading"><div><h2>Farm overview</h2><p>Current assessment context</p></div><button type="button" className="text-action" onClick={() => onNavigate("assessment")}>＋ Add assessment</button></div>
          {result ? <div className="farm-detail-grid"><div><small>Crop</small><strong>{displayText(field.crop, "Not provided")}</strong></div><div><small>Location</small><strong>{isFiniteNumber(field.latitude) && isFiniteNumber(field.longitude) ? `${Number(field.latitude).toFixed(4)}, ${Number(field.longitude).toFixed(4)}` : "Unavailable"}</strong></div><div><small>Boundary</small><strong>{displayText(field.geometry_type, "Unavailable")}</strong></div><div><small>Observation period</small><strong>{displayText(field.start_date)} → {displayText(field.end_date)}</strong></div></div> : <div className="empty-card-state"><div className="empty-state-mark">⌖</div><strong>No farm assessment yet</strong><p>Draw a field boundary to request a satellite and weather evidence review.</p><button type="button" className="button-secondary" onClick={() => onNavigate("assessment")}>Select a farm</button></div>}
        </article>
        <article className="dashboard-card latest-screening-card"><h2>Latest screening</h2><p>Evidence summary</p><div className={`screening-empty ${concern !== "Unavailable" ? `screening-${concern.toLowerCase()}` : ""}`}><span>{concern === "Unavailable" ? "NOT AVAILABLE" : `${concern} CONCERN`}</span><strong>{result ? screeningIndication(category) : "No evidence to screen yet"}</strong></div><p className="small-note">Screening is provisional, uses available comparisons, and requires field verification.</p><button type="button" className="text-action" onClick={() => onNavigate(result ? "results" : "assessment")}>{result ? "Review results →" : "Start an assessment →"}</button></article>
      </div>
      <article className="dashboard-card recent-card"><div className="card-heading"><div><h2>Latest assessment</h2><p>Current in-memory result; history is not persisted.</p></div><button type="button" className="text-action" onClick={() => onNavigate("results")}>View report →</button></div>{result ? <div className="recent-row"><span>{displayText(field.crop, "Farm assessment")}</span><span>{displayText(field.start_date)} – {displayText(field.end_date)}</span><span>{displayText(category, "Screening unavailable")}</span><button type="button" className="text-action" onClick={() => onNavigate("results")}>Open report</button></div> : <div className="empty-history">No assessment in this session. Submitted assessments are not saved to a database.</div>}</article>
    </section>
  );
}


function App() {
  const [form, setForm] = useState({
  latitude: "",
  longitude: "",
  crop: "other",
  start_date: "",
  end_date: "",

  state_name: "",
  district_name: "",
  crop_name: "",
  season: "",
  benchmark_year: "",
});

  const [fieldBoundary, setFieldBoundary] = useState(null);
  const maxObservationDate = localISODate();

  const position = [
    form.latitude.trim() === "" ? 18.5204 : Number(form.latitude),
    form.longitude.trim() === "" ? 73.8567 : Number(form.longitude),
  ];

  const [result, setResult] = useState(null);
  const [insuredSum, setInsuredSum] = useState("");
  const [minimumAssumedLoss, setMinimumAssumedLoss] = useState("");
  const [maximumAssumedLoss, setMaximumAssumedLoss] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ndviResult, setNdviResult] = useState(null);
  const [satelliteImageErrors, setSatelliteImageErrors] = useState({});
  const [satelliteImageData, setSatelliteImageData] = useState({ trueColour: null, ndvi: null, beforeTrueColour: null, beforeNdvi: null });
  const [satelliteImagesReady, setSatelliteImagesReady] = useState(true);
  const validPages = ["home", "dashboard", "assessment", "results"];
  const initialPage = window.location.hash.replace(/^#\/?/, "");
  const [activePage, setActivePage] = useState(validPages.includes(initialPage) ? initialPage : "home");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  React.useEffect(() => {
    const syncPage = () => {
      const page = window.location.hash.replace(/^#\/?/, "");
      setActivePage(validPages.includes(page) ? page : "home");
    };
    window.addEventListener("hashchange", syncPage);
    return () => window.removeEventListener("hashchange", syncPage);
  }, []);

  function navigate(page) {
    if (!validPages.includes(page)) return;
    if (window.location.hash !== `#${page}`) window.location.hash = page;
    setActivePage(page);
    setSidebarOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  React.useEffect(() => {
    let cancelled = false;
    const imagery = result?.satellite_visualizations;
    setSatelliteImageErrors({});
    setSatelliteImageData({ trueColour: null, ndvi: null, beforeTrueColour: null, beforeNdvi: null });
    setSatelliteImagesReady(imagery?.status !== "SUCCESS");

    async function loadImage(path) {
      if (typeof path !== "string" || !path.startsWith("/api/satellite/images/")) return null;
      try {
        const response = await fetch(`${API}${path}`, { cache: "no-store" });
        if (!response.ok) return null;
        const blob = await response.blob();
        if (blob.type !== "image/png" || blob.size > 1_500_000) return null;
        return await new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : null);
          reader.onerror = () => resolve(null);
          reader.readAsDataURL(blob);
        });
      } catch {
        return null;
      }
    }

    if (imagery?.status === "SUCCESS") {
      Promise.all([
        loadImage(imagery.true_colour_url),
        loadImage(imagery.ndvi_url),
        loadImage(imagery.before_period?.true_colour_url),
        loadImage(imagery.before_period?.ndvi_url),
      ]).then(([trueColour, ndvi, beforeTrueColour, beforeNdvi]) => {
        if (!cancelled) {
          setSatelliteImageData({ trueColour, ndvi, beforeTrueColour, beforeNdvi });
          setSatelliteImagesReady(true);
        }
      });
    }

    return () => { cancelled = true; };
  }, [result]);

  
function validateAssessmentDates(startDate, endDate) {
  if (!startDate || !endDate) {
    return "Please select both observation dates.";
  }

  if (endDate < startDate) {
    return "End date must be on or after the start date.";
  }

  const today = localISODate();
  if (startDate > today || endDate > today) {
    return "Observation dates cannot be in the future. Choose today or an earlier date.";
  }

  const start = new Date(`${startDate}T00:00:00`);
  const end = new Date(`${endDate}T00:00:00`);
  const days = Math.round((end - start) / (1000 * 60 * 60 * 24));

  if (days > 400) {
    return "Please select dates no more than 400 days apart.";
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
    setSatelliteImageErrors({});


    try {
      const response = await fetch(`${API}/api/assess`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify((() => {
          const {
            state_name,
            district_name,
            crop_name,
            season,
            benchmark_year,
            ...assessmentForm
          } = form;
          const payload = {
            ...assessmentForm,
            latitude: Number(form.latitude),
            longitude: Number(form.longitude),
            field_boundary: fieldBoundary,
          };
          if (
            state_name.trim() &&
            district_name.trim() &&
            crop_name.trim() &&
            season.trim() &&
            String(benchmark_year).trim()
          ) {
            Object.assign(payload, {
              state_name: state_name.trim(),
              district_name: district_name.trim(),
              crop_name: crop_name.trim(),
              season: season.trim(),
              benchmark_year: Number(benchmark_year),
            });
          }
          return payload;
        })()),
      });

      const body = await response.json();

      if (!response.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail.map((item) => item?.msg).filter(Boolean).join(" ")
          : body.detail;
        throw new Error(detail || "Assessment request failed");
      }

      setResult(body);
      navigate("results");
      
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

  const visualizations = result.satellite_visualizations || {};
  const imageData = satelliteImageData;

  const pdf = new jsPDF("p", "mm", "a4");
  const W = 210;
  const M = 17;
  const CW = W - M * 2;
  const TOP = 19;
  const BODY_BOTTOM = 275;
  const field = result.field || {};
  const weather = result.weather_summary || {};
  const satellite = result.satellite_evidence || {};
  const imageMetadata = visualizations;
  const beforeImageMetadata = visualizations.before_period || {};
  const history = result.historical_comparison || {};
  const rainfallHistory = result.historical_rainfall_comparison || {};
  const radarEvidence = result.satellite_radar_evidence || {};
  const stress = result.crop_stress_assessment || {};
  const stressIndicators = stress.indicators || {};
  const yieldData = result.historical_yield_benchmark || {};
  const imageObservationPeriod = `${safeValue(imageMetadata.start_date, safeValue(field.start_date))} to ${safeValue(imageMetadata.end_date, safeValue(field.end_date))}`;
  const imageContext = `Source: ${safeValue(imageMetadata.source)}. Requested search period: ${imageObservationPeriod}. Scenes: ${isNumber(imageMetadata.image_count) ? imageMetadata.image_count : "Unavailable"}.`;
  const crop = safeValue(field.crop, "Farm");
  const reportDate = new Date().toLocaleDateString("en-IN");
  const reportId = "SC-" + Date.now().toString().slice(-8);
  let y = TOP;

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function safeValue(value, fallback = "Unavailable") {
    if (value == null) return fallback;
    if (typeof value === "number") return Number.isFinite(value) ? String(value) : fallback;
    const stringValue = String(value).trim();
    return !stringValue || ["undefined", "null", "nan"].includes(stringValue.toLowerCase())
      ? fallback
      : stringValue;
  }

  function number(value, digits = 2, suffix = "") {
    return isNumber(value) ? `${value.toFixed(digits)}${suffix}` : "Unavailable";
  }

  function pageText(value, x, yy, size = 10, style = "normal", color = [45, 55, 50], options = {}) {
    pdf.setFont("helvetica", style);
    pdf.setFontSize(size);
    pdf.setTextColor(...color);
    pdf.text(String(value), x, yy, options);
  }

  function addPage() {
    pdf.addPage();
    y = TOP;
  }

  function ensureSpace(height) {
    if (y > TOP && y + height > BODY_BOTTOM) addPage();
  }

  function wrappedLines(value, width, size = 9.5, style = "normal") {
    pdf.setFont("helvetica", style);
    pdf.setFontSize(size);
    return pdf.splitTextToSize(safeValue(value), Math.max(10, width));
  }

  function paragraph(value, options = {}) {
    const size = options.size || 9.3;
    const lineHeight = options.lineHeight || 4.5;
    const indent = options.indent || 0;
    const lines = wrappedLines(value, CW - indent, size);

    lines.forEach((line) => {
      ensureSpace(lineHeight);
      pageText(line, M + indent, y, size, "normal", [65, 78, 69]);
      y += lineHeight;
    });
    y += options.after == null ? 3 : options.after;
  }

  function sectionHeading(numberLabel, title, reserve = 9) {
    ensureSpace(14 + reserve);
    y += 3;
    pdf.setFillColor(226, 241, 231);
    pdf.roundedRect(M, y - 5.5, 8, 8, 2, 2, "F");
    pageText(numberLabel, M + 1.7, y, 8, "bold", [24, 105, 68]);
    pageText(title, M + 12, y, 11.5, "bold", [28, 65, 46]);
    y += 9;
  }

  function subheading(title) {
    ensureSpace(12);
    pageText(title, M, y, 9.5, "bold", [38, 81, 53]);
    y += 5;
  }

  function labelValue(label, value, after = 2) {
    const lines = wrappedLines(value, CW, 9.3, "bold");
    ensureSpace(8 + 4.4);
    pageText(safeValue(label), M, y, 7.8, "normal", [110, 120, 113]);
    y += 4.2;
    lines.forEach((line) => {
      ensureSpace(4.5);
      pageText(line, M, y, 9.3, "bold", [35, 48, 40]);
      y += 4.5;
    });
    y += after;
  }

  function linkValue(label, url) {
    ensureSpace(14);
    pageText(label, M, y, 7.8, "normal", [110, 120, 113]);
    y += 4.2;
    const lines = wrappedLines(url, CW, 8.8);
    lines.forEach((line) => {
      ensureSpace(4.5);
      pdf.setFont("helvetica", "normal");
      pdf.setFontSize(8.8);
      pdf.setTextColor(24, 105, 68);
      pdf.textWithLink(line, M, y, { url });
      y += 4.5;
    });
    y += 2;
  }

  function metricCard(x, yy, width, label, value, note) {
    const cardHeight = 29;
    pdf.setFillColor(242, 248, 243);
    pdf.roundedRect(x, yy, width, cardHeight, 3, 3, "F");
    pageText(safeValue(label), x + 4, yy + 6.5, 7.4, "normal", [90, 110, 95]);
    const valueLines = wrappedLines(value, width - 8, 10.5, "bold").slice(0, 2);
    valueLines.forEach((line, index) => {
      pageText(line, x + 4, yy + 14 + index * 4.1, 10.5, "bold", [25, 105, 65]);
    });
    pageText(safeValue(note), x + 4, yy + 25.5, 6.7, "normal", [105, 115, 108]);
  }

  function metricPair(left, right) {
    ensureSpace(32);
    const gap = 4;
    const width = (CW - gap) / 2;
    metricCard(M, y, width, left.label, left.value, left.note);
    metricCard(M + width + gap, y, width, right.label, right.value, right.note);
    y += 34;
  }

  function drawNDVIChart() {
    const periods = [];
    (Array.isArray(history.historical_periods) ? history.historical_periods : []).forEach((period) => {
      if (isNumber(period?.ndvi_mean)) {
        periods.push({ year: safeValue(period.year), value: period.ndvi_mean });
      }
    });
    const currentNdvi = currentAssessmentNdvi(result);
    if (isNumber(currentNdvi)) {
      periods.push({
        year: safeValue(history.current_period?.start_date?.slice(0, 4), "Current"),
        value: currentNdvi,
      });
    }

    if (!periods.length) {
      paragraph("No historical NDVI chart is available because usable values were not returned.");
      return;
    }

    // Keep the chart and its interpretation together when space allows.
    ensureSpace(72);
    const chartY = y;
    const chartHeight = 49;
    const zeroY = chartY + chartHeight / 2;
    const maxAbs = Math.max(0.1, ...periods.map((period) => Math.abs(period.value)));
    pdf.setFillColor(247, 249, 247);
    pdf.roundedRect(M, chartY, CW, chartHeight, 3, 3, "F");
    pdf.setDrawColor(205, 216, 207);
    pdf.line(M + 5, zeroY, W - M - 5, zeroY);

    const slot = (CW - 12) / periods.length;
    const barWidth = Math.min(15, slot * 0.48);
    periods.forEach((period, index) => {
      const centerX = M + 6 + slot * index + slot / 2;
      const barHeight = Math.max(0.7, (Math.abs(period.value) / maxAbs) * 16);
      const barY = period.value >= 0 ? zeroY - barHeight : zeroY;
      pdf.setFillColor(45, 145, 91);
      pdf.roundedRect(centerX - barWidth / 2, barY, barWidth, barHeight, 1, 1, "F");
      pageText(period.value.toFixed(3), centerX, period.value >= 0 ? barY - 1.5 : barY + barHeight + 3, 6.5, "bold", [35, 75, 48], { align: "center" });
      pageText(period.year, centerX, chartY + chartHeight - 2, 6.5, "normal", [75, 85, 78], { align: "center" });
    });
    y += chartHeight + 4;
  }

  function drawSatelliteImage(title, dataUrl, note, reserveAfter = 0) {
    if (!dataUrl) return false;
    try {
      const properties = pdf.getImageProperties(dataUrl);
      const maxHeight = 65;
      const scale = Math.min(CW / properties.width, maxHeight / properties.height);
      const imageWidth = properties.width * scale;
      const imageHeight = properties.height * scale;
      ensureSpace(imageHeight + 18 + reserveAfter);
      pageText(title, M, y, 9.2, "bold", [38, 81, 53]);
      y += 5;
      pdf.addImage(dataUrl, "PNG", M + (CW - imageWidth) / 2, y, imageWidth, imageHeight, undefined, "FAST");
      y += imageHeight + 2;
      paragraph(note, { size: 8.3, after: 4 });
      return true;
    } catch {
      return false;
    }
  }

  function drawNdviLegend() {
    const legend = imageMetadata.ndvi_legend || {};
    const palette = Array.isArray(legend.palette)
      ? legend.palette.filter((colour) => typeof colour === "string" && /^[0-9a-f]{6}$/i.test(colour))
      : [];
    const minimum = isNumber(legend.min) ? legend.min : -0.2;
    const maximum = isNumber(legend.max) ? legend.max : 0.9;
    if (!palette.length || maximum <= minimum) return;

    ensureSpace(17);
    pageText("NDVI legend", M, y, 8.2, "bold", [38, 81, 53]);
    y += 2;
    const legendWidth = Math.min(CW - 12, 150);
    const legendX = M + (CW - legendWidth) / 2;
    const swatchWidth = legendWidth / palette.length;
    palette.forEach((colour, index) => {
      const red = parseInt(colour.slice(0, 2), 16);
      const green = parseInt(colour.slice(2, 4), 16);
      const blue = parseInt(colour.slice(4, 6), 16);
      pdf.setFillColor(red, green, blue);
      pdf.rect(legendX + index * swatchWidth, y, swatchWidth + 0.1, 4, "F");
    });
    y += 8;
    pageText(minimum.toFixed(1), legendX, y, 7, "normal", [65, 78, 69]);
    pageText(maximum.toFixed(1), legendX + legendWidth, y, 7, "normal", [65, 78, 69], { align: "right" });
    pageText("Lower vegetation index", legendX, y + 4, 6.5, "normal", [100, 110, 103]);
    pageText("Higher vegetation index", legendX + legendWidth, y + 4, 6.5, "normal", [100, 110, 103], { align: "right" });
    y += 8;
    paragraph(`NDVI values below ${minimum.toFixed(1)} or above ${maximum.toFixed(1)} use the end colours.`, { size: 7.6, after: 2 });
  }

  function percentage(value) {
    return isNumber(value) ? `${value > 0 ? "+" : ""}${value.toFixed(2)}%` : "Unavailable";
  }

  // Cover and farm summary.
  pdf.setFillColor(20, 83, 53);
  pdf.rect(0, 0, W, 62, "F");
  pageText("FARM EVIDENCE", M, 21, 11, "bold", [255, 255, 255]);
  pageText("FARM EVIDENCE REPORT", M, 39, 20, "bold", [255, 255, 255]);
  pageText("Satellite and weather observations for review", M, 50, 8.5, "normal", [225, 242, 229]);
  y = 73;
  sectionHeading("01", "Farm and observation period", 39);
  labelValue("Crop", crop);
  labelValue("Requested observation period", `${safeValue(field.start_date)} to ${safeValue(field.end_date)}`);
  labelValue("Field location (latitude, longitude)", `${safeValue(field.latitude)}, ${safeValue(field.longitude)}`);
  labelValue("Assessment area", field.geometry_type || (satellite.geometry_type === "Polygon" ? "Farm polygon" : "Point buffer (100 m)"));
  metricPair(
    { label: "CURRENT RAINFALL", value: number(weather.total_precipitation_mm, 1, " mm"), note: "Complete requested period" },
    { label: "CURRENT NDVI", value: number(currentAssessmentNdvi(result), 4), note: "Vegetation indicator" },
  );
  paragraph("Prototype evidence report only. It is not an official crop-loss certificate or insurance decision, and it does not confirm crop damage, eligibility, or a claim outcome.", { size: 8.5 });
  pageText(`Report ID: ${reportId}`, M, y, 7.5, "normal", [100, 110, 103]);
  pageText(`Generated: ${reportDate}`, W - M, y, 7.5, "normal", [100, 110, 103], { align: "right" });
  y += 9;

  // Rainfall evidence and comparison.
  sectionHeading("02", "Rainfall evidence", 30);
  labelValue("Current rainfall total", number(weather.total_precipitation_mm, 1, " mm"));
  labelValue("Valid rainfall days returned", isNumber(weather.days_returned) ? `${weather.days_returned}${isNumber(weather.requested_days) ? ` of ${weather.requested_days}` : ""}` : "Unavailable");
  labelValue("Rainfall data status", safeValue(weather.status));
  if (weather.message) paragraph(weather.message, { size: 8.5 });
  labelValue("Weather source", weather.source);
  labelValue("Historical average rainfall", number(rainfallHistory.historical_average_mm, 1, " mm"));
  labelValue("Change from historical average", percentage(currentRainfallChange(result)));
  const rainfallPeriods = Array.isArray(rainfallHistory.periods) ? rainfallHistory.periods : [];
  if (rainfallHistory.status === "SUCCESS" && rainfallPeriods.length) {
    // Keep the subheading with at least the first historical year row.
    ensureSpace(22);
    subheading("Historical rainfall by year");
    rainfallPeriods.forEach((period) => {
      labelValue(
        isNumber(period.year) ? String(period.year) : "Historical year",
        `${number(period.total_rainfall_mm, 1, " mm")} | ${isNumber(period.days_returned) ? `${period.days_returned} valid days` : "record count unavailable"}${period.start_date && period.end_date ? ` | ${period.start_date} to ${period.end_date}` : ""}`,
      );
    });
  } else {
    paragraph("Year-wise historical rainfall comparison is unavailable.");
  }
  paragraph("Rainfall variation is supporting weather context. It does not by itself prove flooding, drought damage, or crop loss.", { size: 8.8 });

  // Current satellite vegetation evidence.
  sectionHeading("03", "Satellite vegetation evidence", 28);
  labelValue("Source", satellite.source || "Sentinel-2 source unavailable");
  labelValue("Satellite status", satellite.status);
  labelValue("Usable scenes returned", satellite.status === "UNAVAILABLE" || !isNumber(satellite.image_count) ? "Unavailable" : String(satellite.image_count));
  labelValue("Current mean NDVI", number(currentAssessmentNdvi(result), 4));
  labelValue("Requested Sentinel-2 search period", `${safeValue(satellite.start_date, safeValue(field.start_date))} to ${safeValue(satellite.end_date, safeValue(field.end_date))}`);
  paragraph("The period above is the requested search interval. Individual Sentinel-2 scene acquisition dates are not included in this report.", { size: 8.2 });
  paragraph("NDVI is a vegetation indicator derived from reflected light. It is not a direct measurement of production and is not direct proof of crop loss.", { size: 8.8 });

  // Field-clipped thumbnails are optional; image fetch failures do not block the report.
  const hasBothImages = Boolean(imageData.trueColour && imageData.ndvi);
  sectionHeading("04", "Sentinel-2 satellite images", hasBothImages ? 230 : 28);
  if (imageMetadata.status === "SUCCESS") {
    paragraph(imageContext, { size: 8.5, after: 3 });

    const beforePeriod = `${safeValue(beforeImageMetadata.start_date)} to ${safeValue(beforeImageMetadata.end_date)}`;
    if (beforeImageMetadata.status === "SUCCESS") {
      drawSatelliteImage(
        "Before: Sentinel-2 true-colour reference",
        imageData.beforeTrueColour,
        `Same-length reference period before the selected observation period: ${beforePeriod}. Source: ${safeValue(beforeImageMetadata.source)}; scenes: ${isNumber(beforeImageMetadata.image_count) ? beforeImageMetadata.image_count : "Unavailable"}.`,
      );
    } else {
      paragraph(`Before-period reference image is unavailable (${beforePeriod}). ${safeValue(beforeImageMetadata.message, "No usable Sentinel-2 image was returned.")}`, { size: 8.4 });
    }

    const rgbAdded = drawSatelliteImage(
      "Selected period: true-colour RGB composite",
      imageData.trueColour,
      `${imageContext} Sentinel-2 B4/B3/B2 true-colour composite, clipped to the selected farm polygon.`,
    );
    const ndviAdded = drawSatelliteImage(
      "NDVI vegetation map",
      imageData.ndvi,
      `${imageContext} NDVI visualization from the same cloud-masked composite, clipped to the selected farm polygon.`,
      25,
    );
    if (ndviAdded) drawNdviLegend();
    if (!rgbAdded || !ndviAdded) {
      paragraph("One or more satellite previews could not be retrieved. The remaining evidence is included and the report was still generated.", { size: 8.4 });
    }
  } else {
    paragraph(safeValue(imageMetadata.message, "Satellite imagery is unavailable for this field and observation period."));
  }
  paragraph("Satellite images can be affected by cloud cover, observation quality, crop stage, and field conditions. Imagery cannot independently establish insurance eligibility or payout.", { size: 8.5 });

  subheading("Sentinel-1 SAR evidence");
  labelValue("SAR status", radarEvidence.status);
  labelValue("Source and mode", `${safeValue(radarEvidence.source)} | ${safeValue(radarEvidence.instrument_mode)}`);
  labelValue("Requested Sentinel-1 search period", `${safeValue(radarEvidence.start_date)} to ${safeValue(radarEvidence.end_date)}`);
  labelValue("Usable scenes", isNumber(radarEvidence.image_count) ? String(radarEvidence.image_count) : "Unavailable");
  labelValue("Orbit pass", radarEvidence.orbit_pass);
  metricPair(
    { label: "VV MEAN BACKSCATTER", value: number(radarEvidence.vv_mean_db, 2, " dB"), note: "Selected orbit pass" },
    { label: "VH MEAN BACKSCATTER", value: number(radarEvidence.vh_mean_db, 2, " dB"), note: "Selected orbit pass" },
  );
  paragraph(safeValue(radarEvidence.message, "Sentinel-1 SAR evidence is unavailable."), { size: 8.5 });
  paragraph("Radar backscatter can vary with surface moisture, vegetation structure, roughness, and viewing geometry. These values are descriptive evidence only; they do not independently establish crop damage or crop loss.", { size: 8.5 });

  // Historical NDVI comparison with the chart and its explanation kept together.
  sectionHeading("05", "Historical vegetation comparison", 30);
  if (history.status === "SUCCESS") {
    labelValue("Current period mean NDVI", number(currentAssessmentNdvi(result), 4));
    labelValue("Historical average NDVI", number(history.historical_average_ndvi, 4));
    const ndviDifference = ndviDifferenceFromBaseline(result, history.historical_average_ndvi);
    labelValue("NDVI difference from average", isNumber(ndviDifference) ? `${ndviDifference > 0 ? "+" : ""}${ndviDifference.toFixed(4)}` : "Unavailable");
    labelValue("Historical years available", isNumber(history.historical_years_available) ? `${history.historical_years_available} of ${safeValue(history.historical_years_requested)}` : "Unavailable");
    const hasNdviChartData = isNumber(currentAssessmentNdvi(result))
      || (Array.isArray(history.historical_periods)
        && history.historical_periods.some((period) => isNumber(period?.ndvi_mean)));
    ensureSpace(hasNdviChartData ? 90 : 35);
    subheading("Mean NDVI by year");
    drawNDVIChart();
    const change = ndviDifference;
    paragraph(!isNumber(change)
      ? "A directional comparison could not be stated because a valid NDVI difference was unavailable."
      : change < 0
        ? "The current mean NDVI is below the available historical average for the matching calendar period."
        : change > 0
          ? "The current mean NDVI is above the available historical average for the matching calendar period."
          : "The current mean NDVI equals the available historical average for the matching calendar period.", { size: 8.8 });
    paragraph("Calendar-period differences can reflect crop stage, planting dates, weather, or observation conditions. A lower NDVI does not by itself establish crop loss.", { size: 8.8 });
  } else {
    paragraph("Historical NDVI comparison is unavailable because sufficient current or historical satellite observations were not returned.");
  }

  // Screening outputs are presented as evidence indicators, never as a loss estimate.
  sectionHeading("06", "Provisional crop-loss screening", 44);
  const limitations = Array.isArray(stress.limitations) && stress.limitations.length
    ? stress.limitations
    : [
        "Screening thresholds are provisional and not validated.",
        "NDVI is vegetation evidence and is not direct proof of crop loss.",
        "Rainfall variation alone does not prove crop damage.",
      ];
  const stressLabelGap = 0.4;
  labelValue("Status", stress.status, stressLabelGap);
  labelValue("Screening category", stress.category, stressLabelGap);
  labelValue("Screening concern", screeningConcern(stress.category, stress.status), stressLabelGap);
  labelValue("Potential crop-stress indication", screeningIndication(stress.category), stressLabelGap);
  labelValue("Evidence quality", stress.evidence_quality, stressLabelGap);
  labelValue("NDVI change", percentage(stressIndicators.ndvi_change_percent ?? stress.ndvi_change_percent), stressLabelGap);
  labelValue("Rainfall change", percentage(currentRainfallChange(result)), stressLabelGap);
  labelValue("Interpretation", stress.interpretation, stressLabelGap);
  labelValue("Recommended action", stress.recommended_action, stressLabelGap);
  paragraph("Why this result: the provisional category reflects the available NDVI and rainfall comparisons against prototype screening thresholds. NDVI change is not a crop-loss percentage, and this is not a validated crop-loss detection model.", { size: 8.8 });

  const stressLimitationsDisclaimer = "Screening categories use provisional thresholds and require field verification. They are not a validated crop-loss assessment.";
  const limitationLinesHeight = limitations.reduce((height, limitation) => (
    height + wrappedLines(`- ${safeValue(limitation)}`, CW - 2, 8.5).length * 4.2 + 1
  ), 0);
  const disclaimerLinesHeight = wrappedLines(stressLimitationsDisclaimer, CW, 8.8).length * 4.5 + 3;
  const limitationsBlockHeight = 5 + limitationLinesHeight + disclaimerLinesHeight;
  ensureSpace(limitationsBlockHeight);
  subheading("Limitations");
  limitations.forEach((limitation) => paragraph(`- ${safeValue(limitation)}`, { size: 8.5, indent: 2, lineHeight: 4.2, after: 1 }));
  paragraph(stressLimitationsDisclaimer, { size: 8.8 });

  // Historical benchmark, clearly separated from farm-level yield or loss.
  {
    sectionHeading("07", "Historical crop yield benchmark", 27);
    if (yieldData.status === "SUCCESS" && isNumber(yieldData.predicted_yield)) {
      metricCard(M, y, CW, "DISTRICT / CROP HISTORICAL BENCHMARK", `${yieldData.predicted_yield.toFixed(4)} tonnes/ha`, "Model output | not a farm measurement");
      y += 34;
      paragraph("This historical yield benchmark is based on district and crop information. It is not farm-level yield, measured production, or confirmed crop loss.");
    } else {
      if (yieldData.status === "NOT_REQUESTED") paragraph("No optional historical yield benchmark was requested.");
      else paragraph(safeValue(yieldData.message, "Historical yield benchmark is unavailable."));
    }
    paragraph("A historical district/crop productivity benchmark is a broad model reference. It is not measured farm productivity, actual crop loss, or an insurance payout basis.", { size: 8.8 });
  }

  const payoutScenario = calculateIllustrativePayoutRange(insuredSum, minimumAssumedLoss, maximumAssumedLoss);
  if (payoutScenario) {
    sectionHeading("08", "Illustrative loss / payout scenario", 32);
    labelValue("User-entered assumed loss range", `${payoutScenario.minimumPercent}% to ${payoutScenario.maximumPercent}%`);
    labelValue("User-entered insured sum", `INR ${Number(insuredSum).toLocaleString("en-IN")}`);
    labelValue("Illustrative amount range", `INR ${Math.round(payoutScenario.minimumAmount).toLocaleString("en-IN")} to INR ${Math.round(payoutScenario.maximumAmount).toLocaleString("en-IN")}`);
    paragraph("Hypothetical arithmetic scenario using only the values entered by the user. This is not an official insurance payout, eligibility decision, or scheme formula. Percentages are not derived from NDVI or rainfall.", { size: 8.8 });
  }

  // Manual support only: the app has no insurer/PMFBY claim API connection.
  sectionHeading(payoutScenario ? "09" : "08", "Manual claim support", 38);
  paragraph("This tool does not submit or track insurance claims. If crop damage has occurred, contact the official PMFBY channel promptly and ask which reporting route and deadline apply to your policy, state, crop, season, and event type.", { size: 8.8 });
  labelValue("PMFBY loss reporting and grievance helpline", "14447");
  labelValue("Information to keep ready", "Policy ID, insured crop and area, season, event date, and any official acknowledgement or ticket number.");
  paragraph("Keep field photographs and supporting records. This report can be shared as contextual evidence only; it is not a loss certificate, claim submission, eligibility decision, or payout calculation.", { size: 8.8 });
  linkValue("Official PMFBY portal", "https://pmfby.gov.in/");
  linkValue("Policy status and beneficiary report", "https://pmfby.gov.in/BeneficiaryReport/");

  // Plain-language summary of the evidence already shown in this report.
  const currentNdvi = currentAssessmentNdvi(result);
  const historicalNdviDifference = ndviDifferenceFromBaseline(result, history.historical_average_ndvi);
  const rainfallChange = currentRainfallChange(result);
  const imageAvailability = imageMetadata.status === "SUCCESS" && imageData.trueColour && imageData.ndvi
    ? "True-colour and NDVI satellite images were available for the selected period."
    : "Satellite images were unavailable for the selected period.";
  const evidenceSummary = [
    `Rainfall recorded for the selected dates: ${number(weather.total_precipitation_mm, 1, " mm")}. Historical average: ${number(rainfallHistory.historical_average_mm, 1, " mm")}; change: ${percentage(rainfallChange)}.`,
    `Current satellite vegetation reading (NDVI): ${number(currentNdvi, 4)}. Difference from the historical average: ${isNumber(historicalNdviDifference) ? `${historicalNdviDifference > 0 ? "+" : ""}${historicalNdviDifference.toFixed(4)} NDVI` : "Unavailable"}. NDVI describes vegetation, not crop loss.`,
    imageAvailability,
    `Provisional screening label: ${safeValue(stress.category)}; concern: ${screeningConcern(stress.category, stress.status)}. This is a prompt for field checking, not confirmation of crop damage.`,
    "These are satellite and weather observations for the selected field and dates. Please compare them with actual field conditions; the observations alone do not prove crop loss.",
  ];
  const evidenceSummaryHeight = evidenceSummary.reduce((height, item) => (
    height + wrappedLines(item, CW, 8.8).length * 4.5 + 2
  ), 0);
  ensureSpace(evidenceSummaryHeight + 20);
  sectionHeading(payoutScenario ? "10" : "09", "Farmer summary: evidence in simple words", evidenceSummaryHeight);
  evidenceSummary.forEach((item) => paragraph(item, { size: 8.8, after: 2 }));

  // Add consistent footers after all content and page breaks have been finalized.
  const totalPages = pdf.getNumberOfPages();
  for (let page = 1; page <= totalPages; page += 1) {
    pdf.setPage(page);
    pdf.setDrawColor(220, 228, 221);
    pdf.line(M, 283, W - M, 283);
    pageText("Farm Evidence Report", M, 290, 7.5, "normal", [100, 110, 103]);
    pageText(`Page ${page} of ${totalPages}`, W - M, 290, 7.5, "normal", [100, 110, 103], { align: "right" });
  }

  const safeCrop = crop.replace(/[^a-z0-9]/gi, "_");
  pdf.save(`Farm_Evidence_${safeCrop}_Report.pdf`);
}
  return (
    <div className="app-shell">
      <header className={`topbar ${activePage !== "home" ? "topbar-workspace" : ""}`}>
        {activePage !== "home" && <button type="button" className="mobile-menu" aria-label="Toggle navigation" onClick={() => setSidebarOpen((open) => !open)}>☰</button>}
        <div className="brand-mark">FE</div>
        <div>
          <div className="brand-name">Farm Evidence</div>
          <div className="brand-caption">
            Evidence for crop-loss assessment
          </div>
        </div>

        <nav className="top-navigation" aria-label="Main navigation">
          {["home", "dashboard", "assessment", "results"].map((page) => <button key={page} type="button" className={activePage === page ? "nav-link active" : "nav-link"} onClick={() => navigate(page)}>{page === "home" ? "Home" : page === "dashboard" ? "Dashboard" : page === "assessment" ? "New assessment" : "Reports"}</button>)}
        </nav>
        <span className="top-pill">MVP · Evidence only</span>
      </header>

      {activePage !== "home" && <aside className={`app-sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <span className="sidebar-label">WORKSPACE</span>
        {[{page:"dashboard",icon:"◫",label:"Overview"},{page:"dashboard",icon:"⌖",label:"My farms"},{page:"assessment",icon:"＋",label:"New assessment"},{page:"dashboard",icon:"◷",label:"Assessment history"},{page:"results",icon:"▤",label:"Reports"}].map((item,index) => <button key={`${item.label}-${index}`} type="button" className={(activePage === item.page && (item.label !== "My farms" && item.label !== "Assessment history")) ? "sidebar-link selected" : "sidebar-link"} onClick={() => navigate(item.page)}><span>{item.icon}</span>{item.label}</button>)}
        <div className="sidebar-footnote">Prototype · Evidence requires field verification</div>
      </aside>}

      <main className={activePage !== "home" ? "page-main with-sidebar" : "page-main"}>
        {activePage === "home" && <HomeLanding onNavigate={navigate} />}
        {activePage === "dashboard" && <DashboardOverview result={result} onNavigate={navigate} />}
        {(activePage === "assessment" || activePage === "results") && <>
        <section className="hero page-hero">
          <div className="eyebrow">
            {activePage === "assessment" ? "NEW FARM ASSESSMENT" : "ASSESSMENT EVIDENCE"}
          </div>

          <h1>{activePage === "assessment" ? "Start with your farm." : "Review the evidence."}</h1>

          <p>
            {activePage === "assessment" ? "Select a field boundary and observation period to request satellite and weather evidence." : "Explore returned satellite, rainfall, and historical evidence with clear limitations."}
          </p>
        </section>

        <div className="content-grid">
          {activePage === "assessment" && <section className="panel assessment-panel">
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
  boundary={fieldBoundary}
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
      No farm boundary selected. Draw and save the actual farm polygon before submission. The map’s initial center is illustrative and is not a farmer location.
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
                    max={maxObservationDate}
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
                    max={maxObservationDate}
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


<details className="benchmark-inputs">
  <summary>Optional historical yield benchmark</summary>
  <p className="muted">
    Leave these fields blank to skip the benchmark. Enter historical district
    and crop details yourself. All five fields are required to request it; it is
    not a farm-level yield estimate.
  </p>
  <div className="two-cols">
    <label>State<input name="state_name" value={form.state_name} onChange={update} placeholder="State" /></label>
    <label>District<input name="district_name" value={form.district_name} onChange={update} placeholder="District" /></label>
  </div>
  <div className="two-cols">
    <label>Benchmark crop<input name="crop_name" value={form.crop_name} onChange={update} placeholder="Crop name" /></label>
    <label>Season<input name="season" value={form.season} onChange={update} placeholder="Season" /></label>
  </div>
  <label>
    Benchmark year (1997–2022)
    <input name="benchmark_year" type="number" min="1997" max="2022" step="1" value={form.benchmark_year} onChange={update} placeholder="Optional year" />
  </label>
</details>

              <button disabled={loading} type="submit">
                {loading ? "Analyzing…" : "Run assessment"}
                <span>→</span>
              </button>
            </form>
          </section>}

          {activePage === "results" && <section className="panel result-panel">
            {!result && <div className="empty-state results-empty"><div className="empty-icon">▤</div><h2>No report in this session</h2><p>Run an assessment to see real satellite and weather evidence here. Reports are not stored after the session ends.</p><button type="button" onClick={() => navigate("assessment")}>Start an assessment <span>→</span></button></div>}
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
                    <strong>{displayText(result.assessment?.status)}</strong>
                    <small>Current evidence status</small>
                  </div>
                </div>

<button
  type="button"
  onClick={downloadFarmerReport}
  disabled={result.satellite_visualizations?.status === "SUCCESS" && !satelliteImagesReady}
  className="download-report-btn"
>
  {result.satellite_visualizations?.status === "SUCCESS" && !satelliteImagesReady
    ? "Preparing satellite images..."
    : "Download Farmer Report (PDF)"}
</button>

                
<div className="metric-grid">
  <div className="metric">
    <small>Total rainfall in period</small>
    <strong>{formatNumber(result.weather_summary?.total_precipitation_mm, 1, " mm")}</strong>
  </div>

  <div className="metric">
    <small>Valid rainfall days</small>
    <strong>{isFiniteNumber(result.weather_summary?.days_returned) && result.weather_summary.days_returned > 0
      ? `${result.weather_summary.days_returned}${isFiniteNumber(result.weather_summary.requested_days) ? ` / ${result.weather_summary.requested_days}` : ""}`
      : "Unavailable"}</strong>
  </div>
</div>
{result.weather_summary?.status !== "SUCCESS" && (
  <p className="muted" role="status">
    {displayText(result.weather_summary?.message,
      result.weather_summary?.status === "PARTIAL"
        ? "Rainfall coverage is incomplete, so a period total is unavailable."
        : "Rainfall data is unavailable for the requested period.")}
  </p>
)}

<h3>Historical rainfall comparison</h3>
{(() => {
  const comparison = result.historical_rainfall_comparison;
  const periods = Array.isArray(comparison?.periods) ? comparison.periods : [];
  const current = result.weather_summary?.total_precipitation_mm;
  const average = comparison?.historical_average_mm;
  const change = currentRainfallChange(result);

  return (
    <>
      {!comparison || comparison.status !== "SUCCESS" ? (
        <p className="muted">Historical rainfall comparison is unavailable for this period.</p>
      ) : (
        <>
          <div className="metric-grid">
            <div className="metric">
              <small>Current period rainfall</small>
              <strong>{formatNumber(current, 1, " mm")}</strong>
            </div>
            <div className="metric">
              <small>Historical average rainfall</small>
              <strong>{formatNumber(average, 1, " mm")}</strong>
            </div>
            <div className="metric">
              <small>Change from historical average</small>
              <strong>{isFiniteNumber(change) ? `${change > 0 ? "+" : ""}${change.toFixed(2)}%` : "Unavailable"}</strong>
            </div>
            <div className="metric">
              <small>Historical years available</small>
              <strong>{isFiniteNumber(comparison.years_available) && comparison.years_available > 0 ? comparison.years_available : "Unavailable"}</strong>
            </div>
          </div>
          {periods.length > 0 ? periods.map((period) => (
            <p className="muted" key={period.year}>
              {isFiniteNumber(period.year) ? period.year : "Year unavailable"}: {formatNumber(period.total_rainfall_mm, 1, " mm")}
              {period.start_date && period.end_date ? ` · ${period.start_date} to ${period.end_date}` : ""}
              {isFiniteNumber(period.days_returned) && period.days_returned > 0
                ? ` · ${period.days_returned} valid rainfall days`
                : " · record count unavailable"}
            </p>
          )) : <p className="muted">No year-wise historical rainfall records are available.</p>}
          {!isFiniteNumber(change) && (
            <p className="muted">Percentage change is unavailable when current rainfall is missing or the historical average is zero or too low for a stable comparison.</p>
          )}
        </>
      )}
      <p className="evidence-caveat">
        Rainfall variation is supporting weather context only. It does not by itself prove flooding, drought damage, or crop loss.
      </p>
    </>
  );
})()}

<h3>Provisional crop-loss screening</h3>
{(() => {
  const stress = result.crop_stress_assessment || {};
  const indicators = stress.indicators || {};
  const concern = screeningConcern(stress.category, stress.status);
  const limitations = Array.isArray(stress.limitations) && stress.limitations.length
    ? stress.limitations
    : [
        "Screening thresholds are provisional and not validated.",
        "NDVI is vegetation evidence and does not directly measure crop loss.",
        "Rainfall variation alone does not prove crop damage.",
      ];

  return (
    <>
      <div className="metric-grid">
        <div className="metric"><small>Status</small><strong>{displayText(stress.status)}</strong></div>
        <div className="metric"><small>Screening category</small><strong>{displayText(stress.category)}</strong></div>
        <div className="metric"><small>Screening concern</small><strong className={`concern-chip concern-${concern.toLowerCase()}`}>{concern}</strong></div>
        <div className="metric"><small>Potential crop-stress indication</small><strong>{screeningIndication(stress.category)}</strong></div>
        <div className="metric"><small>Evidence quality</small><strong>{displayText(stress.evidence_quality)}</strong></div>
        <div className="metric"><small>NDVI change</small><strong>{formatNumber(indicators.ndvi_change_percent ?? stress.ndvi_change_percent, 2, "%")}</strong></div>
        <div className="metric"><small>Rainfall deviation from historical average</small><strong>{formatNumber(currentRainfallChange(result), 2, "%")}</strong></div>
      </div>
      <div className="evidence-note">
        <strong>Why this result was generated</strong>
        <p>{displayText(stress.interpretation)} The provisional category reflects available NDVI and rainfall comparisons; it is not a validated crop-loss detection model.</p>
        <strong>Interpretation</strong>
        <p>{displayText(stress.interpretation)}</p>
        <strong>Recommended action</strong>
        <p>{displayText(stress.recommended_action)}</p>
        <strong>Limitations</strong>
        <ul>{limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul>
      </div>
      <p className="evidence-caveat">
        NDVI is vegetation evidence, not direct proof of crop loss, and its percentage change is not a crop-loss percentage. Rainfall deviation alone does not prove crop damage. Screening categories use provisional thresholds and require field verification.
      </p>
    </>
  );
})()}

<section className="scenario-calculator" aria-labelledby="scenario-title">
  <h3 id="scenario-title">Illustrative loss / payout scenario</h3>
  <p className="muted">Optional hypothetical calculator. Enter all three values; no percentages are inferred from NDVI, rainfall, or screening results.</p>
  <div className="two-cols">
    <label>Insured sum amount (₹)<input type="number" min="0.01" step="any" inputMode="decimal" value={insuredSum} onChange={(event) => setInsuredSum(event.target.value)} placeholder="Enter amount" /></label>
    <label>Minimum assumed loss (%)<input type="number" min="0" max="100" step="any" inputMode="decimal" value={minimumAssumedLoss} onChange={(event) => setMinimumAssumedLoss(event.target.value)} placeholder="0–100" /></label>
    <label>Maximum assumed loss (%)<input type="number" min="0" max="100" step="any" inputMode="decimal" value={maximumAssumedLoss} onChange={(event) => setMaximumAssumedLoss(event.target.value)} placeholder="0–100" /></label>
  </div>
  {(() => {
    const scenario = calculateIllustrativePayoutRange(insuredSum, minimumAssumedLoss, maximumAssumedLoss);
    const anyEntered = [insuredSum, minimumAssumedLoss, maximumAssumedLoss].some((value) => value !== "");
    return scenario ? (
      <div className="scenario-result" aria-live="polite">
        <p><strong>Assumed loss range:</strong> {scenario.minimumPercent}%–{scenario.maximumPercent}%</p>
        <p><strong>Illustrative amount range:</strong> ₹{Math.round(scenario.minimumAmount).toLocaleString("en-IN")}–₹{Math.round(scenario.maximumAmount).toLocaleString("en-IN")}</p>
      </div>
    ) : <p className={anyEntered ? "scenario-error" : "muted"} aria-live="polite">{anyEntered ? "Enter a positive insured sum and loss percentages from 0 to 100, with minimum no greater than maximum." : "Complete all fields to see an illustrative amount range."}</p>;
  })()}
  <p className="evidence-caveat">These values are hypothetical arithmetic scenarios based only on your inputs. They are not an official insurance payout, eligibility decision, or PMFBY formula.</p>
</section>

<section className="claim-support" aria-labelledby="claim-support-title">
  <div className="section-kicker">MANUAL CLAIM SUPPORT · NO PORTAL CONNECTION</div>
  <h3 id="claim-support-title">Prepare for official claim reporting</h3>
  <p>
    This tool cannot submit or track claims. If crop damage has occurred,
    contact the official PMFBY channel promptly and confirm the reporting
    route and deadline for your policy, state, crop, season, and event type.
  </p>
  <ol>
    <li>Keep your policy ID, insured crop and area, season, and event date ready.</li>
    <li>Save field photographs, supporting records, and any official acknowledgement or ticket number.</li>
    <li>Use the assessment PDF only as contextual evidence; it does not prove loss or eligibility.</li>
  </ol>
  <div className="claim-support-links">
    <a href="https://pmfby.gov.in/" target="_blank" rel="noreferrer">Official PMFBY portal</a>
    <a href="https://pmfby.gov.in/BeneficiaryReport/" target="_blank" rel="noreferrer">Policy status / beneficiary report</a>
    <a href="tel:14447">Call PMFBY loss reporting and grievance helpline: 14447</a>
  </div>
  <p className="claim-support-note">
    Reporting deadlines and claim procedures vary. Confirm current instructions
    with the official portal, helpline, insurer, or state authority.
  </p>
</section>

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
        <strong>{formatNumber(currentAssessmentNdvi(result), 4)}</strong>
      </div>

      <div className="metric">
        <small>Satellite scenes</small>
        <strong>{isFiniteNumber(result.satellite_evidence.image_count) && result.satellite_evidence.image_count > 0
          ? result.satellite_evidence.image_count
          : "Unavailable"}</strong>
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
      Requested search period:{" "}
      {result.satellite_evidence.start_date ?? result.field?.start_date}
      {" to "}
      {result.satellite_evidence.end_date ?? result.field?.end_date}
    </p>
    <p className="muted">This is the requested search interval; individual Sentinel-2 scene acquisition dates are not shown.</p>

<h3>Actual Sentinel-2 imagery</h3>
{(() => {
  const imagery = result.satellite_visualizations;
  if (imagery?.status !== "SUCCESS") {
    return (
      <div className="satellite-image-unavailable">
        {displayText(imagery?.message, "Satellite imagery is unavailable for this field and observation period.")}
      </div>
    );
  }

  const palette = Array.isArray(imagery.ndvi_legend?.palette)
    ? imagery.ndvi_legend.palette.filter((colour) => /^[0-9a-f]{6}$/i.test(colour))
    : [];
  const legendMin = isFiniteNumber(imagery.ndvi_legend?.min) ? imagery.ndvi_legend.min : -0.2;
  const legendMax = isFiniteNumber(imagery.ndvi_legend?.max) ? imagery.ndvi_legend.max : 0.9;
  const observationPeriod = `${imagery.start_date || "Unavailable"} to ${imagery.end_date || "Unavailable"}`;
  const beforePeriod = imagery.before_period;
  const beforeObservationPeriod = beforePeriod?.start_date && beforePeriod?.end_date
    ? `${beforePeriod.start_date} to ${beforePeriod.end_date}`
    : "Unavailable";

  return (
    <div className="satellite-visualizations">
      <p className="muted">
        Source: {displayText(imagery.source)} · Requested search period: {observationPeriod} · Scenes: {isFiniteNumber(imagery.image_count) ? imagery.image_count : "Unavailable"}
      </p>
      <p className="muted">The displayed dates are the requested search interval, not the acquisition date of each satellite scene.</p>
      <p className="muted">Before image: a same-length Sentinel-2 composite from immediately before the selected period. It is a visual reference; season, crop stage, cloud cover, and observation quality may differ.</p>
      <div className="satellite-image-grid">
        <figure className="satellite-figure">
          {!satelliteImagesReady ? (
            <div className="satellite-image-unavailable">Loading before-period image…</div>
          ) : beforePeriod?.status === "SUCCESS" && satelliteImageData.beforeTrueColour ? (
            <img src={satelliteImageData.beforeTrueColour} alt={`Sentinel-2 true-colour reference before selected period, ${beforeObservationPeriod}`} loading="lazy" />
          ) : (
            <div className="satellite-image-unavailable">Before-period image is unavailable{beforePeriod?.message ? `: ${beforePeriod.message}` : "."}</div>
          )}
          <figcaption>Before · Sentinel-2 true-colour · {beforeObservationPeriod}</figcaption>
        </figure>
        <figure className="satellite-figure">
          {!satelliteImagesReady ? (
            <div className="satellite-image-unavailable">Loading selected-period image…</div>
          ) : imagery.true_colour_url && !satelliteImageErrors.trueColour ? (
            <img
              src={`${API}${imagery.true_colour_url}`}
              alt={`Sentinel-2 true-colour image of the selected farm, ${observationPeriod}`}
              loading="lazy"
              onError={() => setSatelliteImageErrors((current) => ({ ...current, trueColour: true }))}
            />
          ) : (
            <div className="satellite-image-unavailable">True-colour image is unavailable. Run the assessment again to retry.</div>
          )}
          <figcaption>Selected period · Sentinel-2 true-colour · {observationPeriod}</figcaption>
        </figure>
        <figure className="satellite-figure">
          {!satelliteImagesReady ? (
            <div className="satellite-image-unavailable">Loading before-period NDVI map…</div>
          ) : beforePeriod?.status === "SUCCESS" && satelliteImageData.beforeNdvi ? (
            <img src={satelliteImageData.beforeNdvi} alt={`NDVI map before selected period, ${beforeObservationPeriod}`} loading="lazy" />
          ) : (
            <div className="satellite-image-unavailable">Before-period NDVI map is unavailable.</div>
          )}
          <figcaption>Before · NDVI vegetation map · {beforeObservationPeriod}</figcaption>
        </figure>
        <figure className="satellite-figure">
          {!satelliteImagesReady ? (
            <div className="satellite-image-unavailable">Loading NDVI map…</div>
          ) : imagery.ndvi_url && !satelliteImageErrors.ndvi ? (
            <img
              src={`${API}${imagery.ndvi_url}`}
              alt={`NDVI vegetation map of the selected farm, ${observationPeriod}`}
              loading="lazy"
              onError={() => setSatelliteImageErrors((current) => ({ ...current, ndvi: true }))}
            />
          ) : (
            <div className="satellite-image-unavailable">NDVI map is unavailable. Run the assessment again to retry.</div>
          )}
          <figcaption>Selected period · NDVI vegetation map · {observationPeriod}</figcaption>
        </figure>
      </div>
      <div className="ndvi-legend" aria-label={`NDVI scale from ${legendMin} to ${legendMax}`}>
        <div
          className="ndvi-legend-gradient"
          style={{ background: palette.length ? `linear-gradient(90deg, ${palette.map((colour) => `#${colour}`).join(", ")})` : "linear-gradient(90deg, #8c510a, #d8b365, #f6e8c3, #a6d96a, #1a9850, #006837)" }}
        />
        <div className="ndvi-legend-labels"><span>{legendMin.toFixed(1)} · lower vegetation index</span><span>{legendMax.toFixed(1)} · higher vegetation index</span></div>
        <p className="muted">NDVI range shown: {legendMin.toFixed(1)} to {legendMax.toFixed(1)}. Values outside this range use the nearest end colour.</p>
      </div>
      <p className="evidence-caveat">
        NDVI is vegetation evidence, not direct proof of crop loss. Cloud cover, observation quality, crop stage, and field conditions can affect interpretation. Imagery alone cannot establish insurance eligibility or payout.
      </p>
    </div>
  );
})()}

<h3>Sentinel-1 SAR evidence</h3>
{(() => {
  const radar = result.satellite_radar_evidence || {};
  return radar.status === "SUCCESS" ? (
    <>
      <div className="metric-grid">
        <div className="metric"><small>VV mean backscatter</small><strong>{formatNumber(radar.vv_mean_db, 2, " dB")}</strong></div>
        <div className="metric"><small>VH mean backscatter</small><strong>{formatNumber(radar.vh_mean_db, 2, " dB")}</strong></div>
        <div className="metric"><small>Usable scenes</small><strong>{isFiniteNumber(radar.image_count) ? radar.image_count : "Unavailable"}</strong></div>
        <div className="metric"><small>Orbit pass</small><strong>{displayText(radar.orbit_pass)}</strong></div>
      </div>
      <p className="muted">
        Source: {displayText(radar.source)} · Mode: {displayText(radar.instrument_mode)} · Requested search period: {displayText(radar.start_date)} to {displayText(radar.end_date)}
      </p>
    </>
  ) : (
    <div className="satellite-image-unavailable">
      {displayText(radar.message, "Sentinel-1 SAR evidence is unavailable for this area and observation period.")}
    </div>
  );
})()}
<p className="evidence-caveat">
  VV/VH backscatter is descriptive radar evidence. Surface moisture, vegetation structure, roughness, and viewing geometry affect it; it does not independently establish crop damage or crop loss.
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
          {formatNumber(currentAssessmentNdvi(result), 4)}
        </strong>
      </div>

      <div className="metric">
        <small>Multi-year baseline</small>
        <strong>
          {formatNumber(result.historical_comparison.historical_average_ndvi, 4)}
        </strong>
      </div>

      <div className="metric">
        <small>NDVI change</small>
        <strong>
          {isFiniteNumber(ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi))
            ? `${ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi) > 0 ? "+" : ""}${ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi).toFixed(4)}`
            : "Unavailable"}
        </strong>
      </div>
    </div>

    <p className="muted">
      Historical years available:{" "}
      {isFiniteNumber(result.historical_comparison.historical_years_available)
        ? result.historical_comparison.historical_years_available
        : "Unavailable"}
      {" / "}
      {isFiniteNumber(result.historical_comparison.historical_years_requested)
        ? result.historical_comparison.historical_years_requested
        : "Unavailable"}
    </p>

    {(Array.isArray(result.historical_comparison.historical_periods)
      ? result.historical_comparison.historical_periods
      : []).map((period) => (
      <p className="muted" key={period.year}>
        {isFiniteNumber(period.year) ? period.year : "Year unavailable"}:{" "}
        {isFiniteNumber(period.ndvi_mean)
          ? `NDVI ${period.ndvi_mean.toFixed(4)}`
          : "NDVI unavailable"}
        {" · "}
        {isFiniteNumber(period.image_count) && period.image_count > 0
          ? `${period.image_count} satellite scenes`
          : "scene count unavailable"}
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
      ...(Array.isArray(result.historical_comparison.historical_periods)
        ? result.historical_comparison.historical_periods
        : []),
      {
        year: Number(
          result.historical_comparison.current_period?.start_date?.slice(0, 4) || 0
        ) || "Current",
        ndvi: currentAssessmentNdvi(result),
        image_count:
          result.historical_comparison.current_period?.image_count,
      },
    ]
      .sort((a, b) => a.year - b.year)
      .map((period) => {
        const value = period.year === "Current" ? period.ndvi : period.ndvi_mean ?? period.ndvi;

        return (
          <div className="ndvi-bar-item" key={period.year}>
            <strong>{formatNumber(value, 4)}</strong>

            <div className="ndvi-bar-track">
              <div
                className="ndvi-bar"
                style={{
                  height: `${isFiniteNumber(value) ? Math.max(0, Math.min(100, value * 100)) : 0}%`,
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

<h3>Optional historical crop yield benchmark</h3>

{result.historical_yield_benchmark?.status === "SUCCESS" ? (
  <div className="metric-grid">
    <div className="metric">
      <small>Predicted historical yield</small>
      <strong>{formatNumber(result.historical_yield_benchmark.predicted_yield, 4, " tonnes/ha")}</strong>
    </div>

    <div className="metric">
      <small>Model</small>
      <strong>XGBoost</strong>
    </div>
  </div>
) : result.historical_yield_benchmark?.status === "NOT_REQUESTED" ? (
  <p className="muted">No yield benchmark was requested.</p>
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
        {formatNumber(currentAssessmentNdvi(result), 4)}
      </strong>
      , compared with a historical average of{" "}
      <strong>
        {formatNumber(result.historical_comparison.historical_average_ndvi, 4)}
      </strong>
      .
    </p>

    <p>
      The difference is{" "}
      <strong>
        {isFiniteNumber(ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi))
          ? `${ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi) > 0 ? "+" : ""}${ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi).toFixed(4)}`
          : "Unavailable"}
      </strong>
      . Comparison with the historical average is{" "}
      {isFiniteNumber(ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi))
        ? ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi) < 0
          ? "below"
          : ndviDifferenceFromBaseline(result, result.historical_comparison.historical_average_ndvi) > 0
            ? "above"
            : "equal to"
        : "unavailable"}.
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
          </section>}
        </div>

        {activePage === "assessment" && <section className="workflow">
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
        </section>}
        </>}
      </main>

      <footer>
        Farm Evidence · Prototype for demonstration ·
        Not an official insurance assessment
      </footer>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
