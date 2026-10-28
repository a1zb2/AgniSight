"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, ArrowUpRight, BarChart3, Building2,
  CalendarClock, CheckCircle2, ChevronDown, CircleHelp, Crosshair,
  Flame, Layers3, Map as MapIcon, MapPin, Radar, RefreshCw, Search,
  ShieldCheck, ThermometerSun, X,
} from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const EVENTS_API = `${API_BASE}/api/v1/events`;
const SITES_API = `${API_BASE}/api/v1/sites/geojson?site_class=persistent`;
const HISTORY_API = `${API_BASE}/api/v1/history/location`;
const STATUS_API = `${API_BASE}/api/v1/status`;
const INDIA_BOUNDS: [[number, number], [number, number]] = [[68, 6], [98, 38]];
const IMAGERY_DATE = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10);
const NASA_IMAGERY_TILES = `https://gibs-a.earthdata.nasa.gov/wmts/epsg3857/all/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/${IMAGERY_DATE}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`;
const TOOLTIP_STYLE = { background: "#0b1220", border: "1px solid #29364a", borderRadius: 8, color: "#e2e8f0", fontSize: 12 };

type Point = { type: "Point"; coordinates: [number, number] };
type EventProps = {
  event_id: string; observation_count: number; start_time: string; end_time: string;
  max_frp_mw: number | null; day_night: string; category: string; category_title: string;
  priority_level: Priority; priority_score: number; strength_level: string;
  location_pattern: string; site_id: string | null;
};
type ThermalEvent = { type: "Feature"; id: string; geometry: Point; properties: EventProps };
type Evidence = { stance: "supports" | "conflicts" | "context"; source: string; text: string; weight: string };
type ContextFeature = { osm_id: string; name: string | null; category: string; group_label: string; thermal_relevance: string; distance_m: number; relation: string; latitude: number; longitude: number };
type EventDetail = {
  id: string; geometry: Point;
  properties: EventProps & {
    satellites: string; reported_frp_sum_mw: number | null; max_brightness_ti4: number | null;
    confidence_counts: Record<string, number>; span_hours: number;
    assessment: {
      title: string; location_pattern_label: string; evidence: Evidence[]; unknowns: string[]; next_steps: string[];
      strength: { level: string; supporting_sources: string[]; definition: string };
      priority: { score: number; level: Priority; factors: Array<{ points: number; label: string }>; definition: string };
    };
    history: { detection_count: number; active_days: number; active_months: number; calendar_months: number; first_seen: string | null; night_share: number | null; mean_frp: number | null; nasa_typed_count: number; nasa_static_share: number | null; scope: string };
    site: { site_id: string; site_class: string; distance_m: number; context_name: string | null } | null;
    context: { relation: string; feature_count_1500m: number; features: ContextFeature[] };
    model: { static_probability: number; spatial_test: { precision: number; recall: number } } | null;
  };
};
type HistoryMonth = { month: string; detections: number; active_days: number; night_detections: number; max_frp: number | null; data_days: number };
type Status = { latest_observation: string | null; hours_since_latest: number | null; observations: number; sites: Record<string, number>; days_without_data_last_30d: string[] };
type View = "dashboard" | "map" | "incidents" | "analytics";
type Tab = "overview" | "context" | "timeline" | "evidence";
type Range = 1 | 7 | 14;
type Priority = "investigate" | "review" | "monitor";
type Group = "all" | "industrial" | "unmapped" | "vegetation" | "offshore" | "unresolved";

const GROUP_OF: Record<string, Exclude<Group, "all">> = {
  industrial_source: "industrial", industrial_anomaly: "industrial", kiln_activity: "industrial",
  extraction_source: "industrial", extraction_activity: "industrial", waste_source: "industrial", waste_activity: "industrial",
  unmapped_source: "unmapped", vegetation_candidate: "vegetation",
  offshore_source: "offshore", offshore_anomaly: "offshore", volcanic: "offshore", unresolved: "unresolved",
};
const GROUP_LABEL: Record<Exclude<Group, "all">, string> = {
  industrial: "Mapped industry / mining", unmapped: "Persistent, unmapped", vegetation: "Vegetation burning",
  offshore: "Offshore / volcanic", unresolved: "Unresolved",
};
const GROUP_COLORS: Record<Exclude<Group, "all">, string> = {
  industrial: "#fb923c", unmapped: "#c084fc", vegetation: "#4ade80", offshore: "#38bdf8", unresolved: "#94a3b8",
};
const PRIORITY_LABEL: Record<Priority, string> = { investigate: "Investigate", review: "Review", monitor: "Monitor" };
const PRIORITY_TONE: Record<Priority, "high" | "moderate" | "low"> = { investigate: "high", review: "moderate", monitor: "low" };

function dateText(value: string | null | undefined, time = true): string {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return date.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", ...(time ? { hour: "2-digit", minute: "2-digit" } : {}) });
}
function distanceText(m: number): string { return m < 1 ? "inside" : m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(2)} km`; }
function pct(v: number | null | undefined): string { return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`; }
function groupOf(category: string): Exclude<Group, "all"> { return GROUP_OF[category] ?? "unresolved"; }
function activitySeries(events: ThermalEvent[], days: Range, now: number) {
  const span = days * 86400000, count = days === 1 ? 8 : days, interval = span / count;
  const bins = Array.from({ length: count }, (_, i) => {
    const date = new Date(now - span + i * interval);
    return { label: days === 1 ? `${String(i * 3).padStart(2, "0")}h` : date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "Asia/Kolkata" }), events: 0 };
  });
  for (const e of events) {
    const t = new Date(e.properties.start_time).getTime();
    if (!Number.isFinite(t) || t < now - span || t > now) continue;
    bins[Math.min(count - 1, Math.max(0, Math.floor((t - (now - span)) / interval)))].events += 1;
  }
  return bins;
}

function StatCard({ icon: Icon, label, value, note, tone }: { icon: typeof Activity; label: string; value: string | number; note: string; tone: "orange" | "blue" | "green" | "red" }) {
  return <div className="stat-card"><div className={`stat-icon ${tone}`}><Icon size={16} /></div><div className="stat-copy"><span>{label}</span><strong>{value}</strong><small>{note}</small></div></div>;
}
function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>; }

export default function Map() {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const detailRequest = useRef(0);
  const [clockNow] = useState<number>(() => Date.now());
  const [allEvents, setAllEvents] = useState<ThermalEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryMonth[] | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [view, setView] = useState<View>("dashboard");
  const [tab, setTab] = useState<Tab>("overview");
  const [search, setSearch] = useState("");
  const [range, setRange] = useState<Range>(14);
  const [group, setGroup] = useState<Group>("all");
  const [priority, setPriority] = useState<Priority | "all">("all");
  const [basemap, setBasemap] = useState<"satellite" | "street">("satellite");
  const [showContextOnMap, setShowContextOnMap] = useState(true);
  const [showSites, setShowSites] = useState(true);

  const clearSelection = useCallback(() => {
    detailRequest.current += 1;
    setSelectedId(null); setDetail(null); setHistory(null); setDetailError(null); setDetailLoading(false);
  }, []);

  const selectEvent = useCallback(async (feature: ThermalEvent) => {
    const requestId = ++detailRequest.current;
    setSelectedId(feature.id); setTab("overview"); setDetail(null); setHistory(null); setDetailError(null); setDetailLoading(true);
    const [longitude, latitude] = feature.geometry.coordinates;
    try {
      const [detailResponse, historyResponse] = await Promise.all([
        fetch(`${EVENTS_API}/${encodeURIComponent(feature.id)}`),
        fetch(`${HISTORY_API}?${new URLSearchParams({ latitude: String(latitude), longitude: String(longitude), radius_m: "750" })}`),
      ]);
      const detailData = await detailResponse.json();
      if (!detailResponse.ok) throw new Error(detailData.detail ?? "Event details are unavailable.");
      const historyData = historyResponse.ok ? await historyResponse.json() : null;
      if (requestId !== detailRequest.current) return;
      setDetail(detailData as EventDetail);
      setHistory(historyData ? historyData.months as HistoryMonth[] : null);
    } catch (error) {
      if (requestId === detailRequest.current) setDetailError(error instanceof Error ? error.message : "Event details are unavailable.");
    } finally {
      if (requestId === detailRequest.current) setDetailLoading(false);
    }
  }, []);

  const visibleEvents = useMemo(() => {
    const cutoff = clockNow - range * 86400000;
    const query = search.trim().toLowerCase();
    return allEvents.filter((event) => {
      const p = event.properties;
      if (new Date(p.end_time).getTime() < cutoff) return false;
      if (group !== "all" && groupOf(p.category) !== group) return false;
      if (priority !== "all" && p.priority_level !== priority) return false;
      if (query) {
        const haystack = [p.event_id, p.category_title, p.site_id, event.geometry.coordinates[1], event.geometry.coordinates[0]].join(" ").toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }, [allEvents, range, group, priority, search, clockNow]);

  const activityData = useMemo(() => activitySeries(visibleEvents, range, clockNow), [visibleEvents, range, clockNow]);
  const categoryData = useMemo(() => {
    const counts = new globalThis.Map<Exclude<Group, "all">, number>();
    for (const e of visibleEvents) counts.set(groupOf(e.properties.category), (counts.get(groupOf(e.properties.category)) ?? 0) + 1);
    return [...counts.entries()].map(([key, count]) => ({ name: GROUP_LABEL[key], count, color: GROUP_COLORS[key] })).sort((a, b) => b.count - a.count);
  }, [visibleEvents]);
  const priorityData = useMemo(() => {
    const c: Record<Priority, number> = { investigate: 0, review: 0, monitor: 0 };
    for (const e of visibleEvents) c[e.properties.priority_level] += 1;
    return [{ name: "Investigate", value: c.investigate, color: "#f87171" }, { name: "Review", value: c.review, color: "#fb923c" }, { name: "Monitor", value: c.monitor, color: "#38bdf8" }];
  }, [visibleEvents]);
  const stats = useMemo(() => ({
    events: visibleEvents.length,
    detections: visibleEvents.reduce((sum, e) => sum + e.properties.observation_count, 0),
    industrial: visibleEvents.filter((e) => groupOf(e.properties.category) === "industrial").length,
    investigate: visibleEvents.filter((e) => e.properties.priority_level === "investigate").length,
  }), [visibleEvents]);
  const incidentList = useMemo(() => [...visibleEvents].sort((a, b) => b.properties.priority_score - a.properties.priority_score || b.properties.end_time.localeCompare(a.properties.end_time)), [visibleEvents]);

  useEffect(() => {
    fetch(STATUS_API).then((r) => r.ok ? r.json() : null).then((data) => { if (data) setStatus(data as Status); }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    const map = new MapLibreMap({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          satelliteBase: { type: "raster", tiles: [NASA_IMAGERY_TILES], tileSize: 256, maxzoom: 9, attribution: `NASA GIBS / VIIRS SNPP True Color · ${IMAGERY_DATE}` },
          streetBase: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" },
        },
        layers: [
          { id: "satellite-base-layer", type: "raster", source: "satelliteBase", layout: { visibility: "visible" } },
          { id: "street-base-layer", type: "raster", source: "streetBase", layout: { visibility: "none" } },
        ],
      },
      center: [78.9629, 20.5937], zoom: 4.5, attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: true }), "top-right");

    map.on("load", async () => {
      map.fitBounds(INDIA_BOUNDS, { padding: 42, maxZoom: 5.1, duration: 650 });
      map.addSource("thermal-sites", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "thermal-site-rings", type: "circle", source: "thermal-sites", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 3, 9, 9],
        "circle-color": "rgba(192,132,252,0.12)", "circle-stroke-color": "#c084fc", "circle-stroke-width": 1.2,
      } });
      try {
        const response = await fetch(`${EVENTS_API}/geojson?days=14`);
        if (!response.ok) throw new Error(`Thermal events endpoint returned ${response.status}.`);
        const geojson = await response.json() as { features?: ThermalEvent[] };
        const features = Array.isArray(geojson.features) ? geojson.features : [];
        setAllEvents(features);
        fetch(SITES_API).then((r) => r.ok ? r.json() : null).then((sites) => {
          if (sites) (map.getSource("thermal-sites") as GeoJSONSource | undefined)?.setData(sites);
        }).catch((error) => console.warn("Persistent sites unavailable:", error));
        map.addSource("thermal-events", { type: "geojson", data: { type: "FeatureCollection", features } as unknown as GeoJSON.FeatureCollection });
        map.addLayer({ id: "thermal-event-points", type: "circle", source: "thermal-events", paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "observation_count"], 1, 4, 2, 5.5, 5, 8, 10, 11, 25, 14],
          "circle-color": ["match", ["get", "priority_level"], "investigate", "#ef4444", "review", "#f97316", "#facc15"],
          "circle-opacity": 0.92, "circle-stroke-color": "#fff7ed", "circle-stroke-width": 1.1,
        } });
        map.addSource("osm-context", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "osm-context-points", type: "circle", source: "osm-context", paint: { "circle-radius": 6, "circle-color": "#38bdf8", "circle-opacity": 0.96, "circle-stroke-color": "#e0f2fe", "circle-stroke-width": 1.6 } });
        map.addSource("selected-event", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({ id: "selected-event-ring", type: "circle", source: "selected-event", paint: { "circle-radius": 17, "circle-color": "rgba(249,115,22,0.08)", "circle-stroke-color": "#fbbf24", "circle-stroke-width": 2.4 } });
        map.on("click", "thermal-event-points", (event) => {
          const id = String(event.features?.[0]?.properties?.event_id ?? "");
          const feature = features.find((item) => item.id === id);
          if (feature) void selectEvent(feature);
        });
        map.on("mouseenter", "thermal-event-points", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "thermal-event-points", () => { map.getCanvas().style.cursor = ""; });
        setMapReady(true);
        // Events arrive sorted by priority score.
        if (features[0]) void selectEvent(features[0]);
      } catch (error) { setLoadError(error instanceof Error ? error.message : "Could not load thermal events."); }
      finally { setLoading(false); }
    });
    return () => { detailRequest.current += 1; map.remove(); mapRef.current = null; };
  }, [selectEvent]);

  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    (mapRef.current.getSource("thermal-events") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: visibleEvents } as unknown as GeoJSON.FeatureCollection);
  }, [visibleEvents, mapReady]);
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const selected = allEvents.find((e) => e.id === selectedId);
    (mapRef.current.getSource("selected-event") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: selected ? [selected] : [] } as unknown as GeoJSON.FeatureCollection);
  }, [selectedId, allEvents, mapReady]);
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const features = showContextOnMap && detail ? detail.properties.context.features.map((f) => ({ type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [f.longitude, f.latitude] }, properties: { name: f.name, category: f.category } })) : [];
    (mapRef.current.getSource("osm-context") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features } as GeoJSON.FeatureCollection);
  }, [detail, showContextOnMap, mapReady]);
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    mapRef.current.setLayoutProperty("thermal-site-rings", "visibility", showSites ? "visible" : "none");
  }, [showSites, mapReady]);
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    mapRef.current.setLayoutProperty("satellite-base-layer", "visibility", basemap === "satellite" ? "visible" : "none");
    mapRef.current.setLayoutProperty("street-base-layer", "visibility", basemap === "street" ? "visible" : "none");
  }, [basemap, mapReady]);
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const timer = window.setTimeout(() => mapRef.current?.resize(), 80);
    return () => window.clearTimeout(timer);
  }, [view, mapReady]);

  const fitIndia = () => mapRef.current?.fitBounds(INDIA_BOUNDS, { padding: 42, maxZoom: 5.1, duration: 650 });
  const focusEvent = (feature: ThermalEvent) => {
    setView("dashboard"); void selectEvent(feature);
    mapRef.current?.flyTo({ center: feature.geometry.coordinates, zoom: Math.max(mapRef.current.getZoom(), 8), speed: 0.8 });
  };
  const freshness = status?.latest_observation ? `${dateText(status.latest_observation)}${status.hours_since_latest !== null && status.hours_since_latest > 36 ? ` · ${Math.round(status.hours_since_latest / 24)} days old` : ""}` : "Waiting for data";
  const selected = allEvents.find((e) => e.id === selectedId) ?? null;
  const p = detail?.properties;
  const a = p?.assessment;
  const priorityTone = a ? PRIORITY_TONE[a.priority.level] : "low";

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><div className="brand-mark"><Flame size={25} fill="currentColor" /></div><div className="brand-name">Agni<span>Sight</span></div><div className="brand-divider"/><div className="brand-caption"><strong>THERMAL INTELLIGENCE</strong><span>Satellite signals. Real-world context.</span></div></div>
      <div className="top-nav"><span>Detect</span><i/><span>Classify</span><i/><span>Monitor</span><i/><span>Investigate</span></div>
      <label className="global-search"><Search size={16}/><input value={search} onChange={(e) => { clearSelection(); setSearch(e.target.value); }} placeholder="Search event ID, category, site…"/>{search && <button aria-label="Clear search" onClick={() => { clearSelection(); setSearch(""); }}><X size={14}/></button>}</label>
      <div className="system-status"><span className="status-dot"/><div><strong>FIRMS DATA</strong><small>Latest: {freshness}</small></div></div>
    </header>

    <div className="app-body">
      <aside className="sidebar">
        <div className="sidebar-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          <button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}><Activity size={17}/><span>Dashboard</span></button>
          <button className={view === "map" ? "active" : ""} onClick={() => setView("map")}><MapIcon size={17}/><span>Live map</span></button>
          <button className={view === "incidents" ? "active" : ""} onClick={() => setView("incidents")}><AlertTriangle size={17}/><span>Incidents</span><em>{visibleEvents.length.toLocaleString("en-IN")}</em></button>
          <button className={view === "analytics" ? "active" : ""} onClick={() => setView("analytics")}><BarChart3 size={17}/><span>Analytics</span></button>
        </nav>
        <div className="sidebar-section"><div className="sidebar-label">DATA LAYERS</div><div className="layer-chip"><span className="layer-dot firms"/>NASA FIRMS <b>{status ? `${(status.observations / 1e6).toFixed(2)}M` : "ON"}</b></div><div className="layer-chip"><span className="layer-dot osm"/>OSM context <b>LOCAL</b></div><div className="layer-chip"><span className="layer-dot time"/>Persistent sites <b>{status?.sites?.persistent ?? "—"}</b></div></div>
        <div className="sidebar-bottom"><div className="leaf-symbol"><ShieldCheck size={23}/></div><strong>Investigate with evidence.</strong><p>Remote sensing highlights where to look. Context helps decide what to examine.</p><span>GROUND VERIFICATION MATTERS</span></div>
        <div className="sidebar-foot"><span className="green-dot"/>Local PostGIS context</div>
      </aside>

      <section className={`main-area view-${view}`}>
        {view === "analytics" ? <div className="analytics-page">
          <div className="page-heading"><div><div className="eyebrow">OBSERVATION INTELLIGENCE</div><h1>Analytics overview</h1><p>Assessed thermal events from the selected period.</p></div><RangePicker range={range} setRange={(value) => { clearSelection(); setRange(value); }}/></div>
          <div className="analytics-stats"><StatCards stats={stats} range={range}/></div>
          <div className="analytics-charts analytics-charts-large"><ActivityChart data={activityData}/><CategoryChart data={categoryData}/><PriorityChart data={priorityData}/></div>
          <section className="table-card analytics-recent"><div className="panel-heading"><div><h2>Highest-priority events</h2><p>Sorted by triage score.</p></div><button className="text-action" onClick={() => setView("incidents")}>Open incident list <ArrowUpRight size={14}/></button></div><IncidentRows incidents={incidentList.slice(0, 6)} onSelect={focusEvent} selectedId={selectedId ?? ""}/></section>
        </div> : <div className={`workspace-grid ${view === "map" ? "map-only" : ""}`}>
          <section className="map-panel">
            <div className="map-canvas" ref={mapContainer}/>
            <div className="map-header-overlay"><div><div className="eyebrow">INDIA · THERMAL OBSERVATIONS</div><h1>{view === "map" ? "Live map" : "Thermal activity map"}</h1><p>{visibleEvents.length.toLocaleString("en-IN")} events in current filters</p></div><div className="map-header-actions"><button className={`icon-action context-map-toggle ${showSites ? "active" : ""}`} onClick={() => setShowSites((v) => !v)} title="Show or hide year-round persistent heat sites"><Radar size={16}/><span>Sites {showSites ? "on" : "off"}</span></button><button className={`icon-action context-map-toggle ${showContextOnMap ? "active" : ""}`} onClick={() => setShowContextOnMap((v) => !v)} title="Show or hide mapped OSM features around the selected event"><Building2 size={16}/><span>OSM {showContextOnMap ? "on" : "off"}</span></button><button className="icon-action basemap-button" onClick={() => setBasemap((c) => c === "satellite" ? "street" : "satellite")} title="Toggle NASA satellite imagery or street map"><Layers3 size={17}/><span>{basemap === "satellite" ? "Satellite imagery" : "Street map"}</span></button></div></div>
            <div className="map-filters">
              <label><span>PERIOD</span><select value={range} onChange={(e) => { clearSelection(); setRange(Number(e.target.value) as Range); }}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option></select><ChevronDown size={13}/></label>
              <label><span>ASSESSMENT</span><select value={group} onChange={(e) => { clearSelection(); setGroup(e.target.value as Group); }}><option value="all">All assessments</option>{(Object.keys(GROUP_LABEL) as Array<Exclude<Group, "all">>).map((key) => <option key={key} value={key}>{GROUP_LABEL[key]}</option>)}</select><ChevronDown size={13}/></label>
              <label><span>PRIORITY</span><select value={priority} onChange={(e) => { clearSelection(); setPriority(e.target.value as Priority | "all"); }}><option value="all">All priorities</option><option value="investigate">Investigate</option><option value="review">Review</option><option value="monitor">Monitor</option></select><ChevronDown size={13}/></label>
            </div>
            <button className="fit-india" onClick={fitIndia} title="Fit India in map"><Crosshair size={16}/><span>Fit India</span></button>
            <div className="map-legend"><div className="legend-heading">TRIAGE PRIORITY</div><div><i className="legend-red"/>Investigate</div><div><i className="legend-orange"/>Review</div><div><i className="legend-yellow"/>Monitor</div><div><i className="legend-blue"/>Mapped OSM features</div><div><i style={{ border: "1.5px solid #c084fc" }}/>Persistent heat site</div><small>Marker size represents grouped detections</small></div>
            {loading && <div className="map-state"><RefreshCw className="spin" size={18}/>Loading assessed events…</div>}
            {!loading && loadError && <div className="map-state map-error"><AlertTriangle size={18}/><div><strong>Could not load thermal events</strong><span>{loadError}</span><button onClick={() => window.location.reload()}>Retry</button></div></div>}
            {!loading && !loadError && visibleEvents.length === 0 && <div className="map-state empty-map"><CircleHelp size={19}/><div><strong>No events match these filters</strong><span>Try a wider period or reset the filters.</span><button onClick={() => { clearSelection(); setRange(14); setGroup("all"); setPriority("all"); setSearch(""); }}>Reset filters</button></div></div>}
            <div className="map-attribution-note">{basemap === "satellite" ? `NASA GIBS · VIIRS true colour · ${IMAGERY_DATE}` : "© OpenStreetMap contributors"} · Approximate event centroids</div>
          </section>

          {view !== "map" && <aside className="incident-panel">
            {view === "incidents" ? <><div className="incident-list-heading"><div><div className="eyebrow">INVESTIGATION QUEUE</div><h2>Thermal incidents</h2><p>{incidentList.length} matching events · highest priority first</p></div><span className="count-pill">{visibleEvents.length}</span></div><div className="incident-list-panel"><IncidentRows incidents={incidentList} onSelect={focusEvent} selectedId={selectedId ?? ""}/></div></> : selected ? <>
              <div className="incident-titlebar"><div className="titlebar-top"><span className={`priority-pill ${PRIORITY_TONE[selected.properties.priority_level]}`}><span/>{PRIORITY_LABEL[selected.properties.priority_level]} · {selected.properties.priority_score}</span><span className="incident-id">ID {selected.id}</span></div><h2>{selected.properties.category_title}</h2><div className="location-line"><MapPin size={15}/><span>{selected.geometry.coordinates[1].toFixed(4)}° N, {selected.geometry.coordinates[0].toFixed(4)}° E</span><button className="plain-icon" title="Clear selected incident" onClick={clearSelection}><X size={16}/></button></div>{a && <p className="panel-intro">{a.location_pattern_label} · evidence {a.strength.level}{p?.site ? ` · site ${p.site.site_id}` : ""}</p>}</div>
              <div className="panel-tabs" role="tablist" aria-label="Incident details">{([["overview", "Assessment"], ["context", "OSM context"], ["timeline", "History"], ["evidence", "Detections"]] as Array<[Tab, string]>).map(([value, label]) => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{label}</button>)}</div>
              <div className="incident-scroll" key={tab}>
                {detailLoading && <div className="loading-box"><RefreshCw className="spin" size={16}/>Loading assessment…</div>}
                {detailError && <div className="notice warning"><AlertTriangle size={16}/><div><strong>Details unavailable</strong><span>{detailError}</span><button onClick={() => void selectEvent(selected)}>Retry</button></div></div>}
                {p && a && tab === "overview" && <>
                  <div className="overview-metrics"><Metric label="Detections" value={String(p.observation_count)} detail="This event"/><Metric label="Peak FRP" value={p.max_frp_mw === null ? "—" : `${p.max_frp_mw.toFixed(1)} MW`} detail={p.history.mean_frp ? `Location mean ${p.history.mean_frp.toFixed(1)} MW` : "Radiative power"}/><Metric label="Active months" value={String(p.history.active_months)} detail={`${p.history.calendar_months}/12 calendar months`}/></div>
                  <div className="assessment-card"><div className="section-overline"><ShieldCheck size={14}/> EVIDENCE · {a.strength.level.toUpperCase()}</div><h3>{a.title}</h3><p>{a.strength.definition}</p><ul className="evidence-list">{a.evidence.map((e, i) => <li key={i}>{e.stance === "supports" ? <CheckCircle2 size={14}/> : e.stance === "conflicts" ? <AlertTriangle size={14} color="#fdba74"/> : <CircleHelp size={14} color="#93a4ba"/>}<span><b>{e.source}.</b> {e.text}</span></li>)}</ul></div>
                  <div className="section-card"><div className="section-title"><h3>Investigation priority</h3><span className={`text-priority ${priorityTone}`}>{PRIORITY_LABEL[a.priority.level]} · {a.priority.score}/100</span></div><div className="signal-reasons">{a.priority.factors.length ? a.priority.factors.map((f, i) => <span key={i}>{f.points > 0 ? `+${f.points}` : f.points} · {f.label}</span>) : <span>No priority factors apply.</span>}</div><div className="section-note">{a.priority.definition}</div></div>
                  <div className="section-card"><div className="section-title"><h3>Next steps</h3></div><ul className="evidence-list">{a.next_steps.map((s, i) => <li key={i}><ArrowUpRight size={14}/>{s}</li>)}</ul></div>
                  <div className="section-card"><div className="section-title"><h3>What remains unknown</h3></div><ul className="evidence-list">{a.unknowns.map((s, i) => <li key={i}><CircleHelp size={14} color="#93a4ba"/>{s}</li>)}</ul></div>
                </>}
                {p && tab === "context" && <>
                  <div className="context-summary"><div className="context-summary-icon"><Building2 size={20}/></div><div><strong>{p.context.feature_count_1500m} mapped feature{p.context.feature_count_1500m === 1 ? "" : "s"} within 1.5 km</strong><p>Relation to event: {p.context.relation}</p></div></div>
                  {!p.context.features.length && <div className="notice neutral"><CircleHelp size={17}/><div><strong>No relevant mapped facilities</strong><span>This does not prove the area is non-industrial; OSM coverage of Indian industry is incomplete.</span></div></div>}
                  <div className="feature-list">{p.context.features.map((f) => <div className="feature-row" key={f.osm_id}><div className="feature-icon"><Building2 size={15}/></div><div className="feature-main"><strong>{f.name || "Unnamed mapped feature"}</strong><span>{f.category} · {f.thermal_relevance} heat relevance</span><small>OpenStreetMap {f.osm_id}</small></div><div className="feature-distance">{distanceText(f.distance_m)}</div></div>)}</div>
                  <div className="section-note">Proximity is supporting evidence, not proof of causation. A VIIRS pixel is about 375 m across.</div>
                </>}
                {p && tab === "timeline" && <>
                  <div className="timeline-head"><div className="section-overline"><CalendarClock size={14}/> LOCATION HISTORY · 750 m</div><h3>Monthly detections since {dateText(history?.[0]?.month, false)}</h3><p>First seen {dateText(p.history.first_seen, false)} · {p.history.active_days} active days · {pct(p.history.night_share)} at night · NASA static label {pct(p.history.nasa_static_share)} of {p.history.nasa_typed_count} labelled</p></div>
                  <HistoryChart months={history}/>
                  <div className="section-note">{history?.some((m) => m.data_days === 0) ? `No stored satellite data anywhere in India for: ${history.filter((m) => m.data_days === 0).map((m) => m.month.slice(0, 7)).join(", ")}. A zero bar there means no data, not no activity.` : "Satellite data is stored for every month shown, so a zero bar means nothing was detected here that month."}</div>
                </>}
                {p && tab === "evidence" && <>
                  <div className="section-card"><div className="section-title"><h3>Detections in this event</h3><span className="source-tag">NASA FIRMS</span></div><div className="detail-rows"><DetailRow label="First detected" value={dateText(p.start_time)}/><DetailRow label="Last detected" value={dateText(p.end_time)}/><DetailRow label="Satellites" value={p.satellites}/><DetailRow label="Reported FRP sum" value={p.reported_frp_sum_mw === null ? "Unavailable" : `${p.reported_frp_sum_mw.toFixed(2)} MW`}/><DetailRow label="Max brightness (I4)" value={p.max_brightness_ti4 === null ? "Unavailable" : `${p.max_brightness_ti4} K`}/><DetailRow label="Confidence codes" value={Object.entries(p.confidence_counts).map(([k, v]) => `${k}: ${v}`).join(", ") || "Unavailable"}/><DetailRow label="Day / night" value={p.day_night}/>{p.model && <DetailRow label="Static-source model" value={`${pct(p.model.static_probability)} (held-out precision ${pct(p.model.spatial_test.precision)})`}/>}</div></div>
                  <div className="notice neutral"><CircleHelp size={17}/><div><strong>Observation ≠ confirmed fire</strong><span>VIIRS detects thermal anomalies at satellite resolution. It does not independently verify a fire, identify one building, or establish the heat source.</span></div></div>
                </>}
              </div>
              <div className="panel-footer"><span><span className="status-dot small-dot"/>{a ? `Supported by: ${a.strength.supporting_sources.join(", ") || "no direct evidence"}` : "Loading evidence"}</span><button className="text-action" onClick={() => setTab("evidence")}>Detections <ArrowUpRight size={14}/></button></div>
            </> : <div className="no-selection"><div className="empty-orb"><Radar size={28}/></div><h2>Select a thermal event</h2><p>Choose a marker to load its assessment, location history and mapped context.</p><button className="primary-button" onClick={() => setView("incidents")}>Browse incidents <ArrowUpRight size={15}/></button></div>}
          </aside>}

          {view === "dashboard" && <section className="analytics-strip"><div className="stats-row"><StatCards stats={stats} range={range}/></div><div className="dashboard-charts"><ActivityChart data={activityData}/><CategoryChart data={categoryData}/><PriorityChart data={priorityData}/></div></section>}
        </div>}
      </section>
    </div>
  </main>;
}

function StatCards({ stats, range }: { stats: { events: number; detections: number; industrial: number; investigate: number }; range: Range }) {
  return <><StatCard icon={Radar} label="Thermal events" value={stats.events.toLocaleString("en-IN")} note={`Last ${range === 1 ? "24 hours" : `${range} days`}`} tone="orange"/><StatCard icon={ThermometerSun} label="Detections" value={stats.detections.toLocaleString("en-IN")} note="Grouped into events" tone="blue"/><StatCard icon={Building2} label="At mapped industry / mines" value={stats.industrial.toLocaleString("en-IN")} note="OSM context + history" tone="green"/><StatCard icon={AlertTriangle} label="To investigate" value={stats.investigate.toLocaleString("en-IN")} note="Triage score ≥ 50" tone="red"/></>;
}
function DetailRow({ label, value }: { label: string; value: string }) { return <div className="detail-row"><span>{label}</span><strong>{value}</strong></div>; }
function RangePicker({ range, setRange }: { range: Range; setRange: (value: Range) => void }) {
  return <label className="range-select"><CalendarClock size={15}/><select value={range} onChange={(e) => setRange(Number(e.target.value) as Range)}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option></select><ChevronDown size={14}/></label>;
}
function IncidentRows({ incidents, onSelect, selectedId }: { incidents: ThermalEvent[]; onSelect: (event: ThermalEvent) => void; selectedId: string }) {
  if (!incidents.length) return <div className="empty-list"><Radar size={22}/><strong>No matching incidents</strong><span>Widen the period or remove filters to see more events.</span></div>;
  return <div className="incident-rows">{incidents.slice(0, 300).map((event) => {
    const tone = PRIORITY_TONE[event.properties.priority_level];
    return <button className={`incident-row ${selectedId === event.id ? "selected" : ""}`} key={event.id} onClick={() => onSelect(event)}><div className={`incident-mark ${tone}`}><Flame size={16}/></div><div className="incident-row-copy"><strong>{event.properties.category_title}</strong><span>{event.id} · {event.properties.observation_count} detection{event.properties.observation_count === 1 ? "" : "s"} · evidence {event.properties.strength_level}</span><small>{dateText(event.properties.end_time)}</small></div><div className={`signal-chip ${tone}`}>{PRIORITY_LABEL[event.properties.priority_level]} {event.properties.priority_score}</div></button>;
  })}</div>;
}
function ActivityChart({ data }: { data: Array<{ label: string; events: number }> }) {
  return <div className="chart-card"><div className="chart-heading"><div><h3>Event activity</h3><p>Events first observed per interval</p></div><span className="chart-indicator orange"/></div><div className="chart-stage"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{ top: 8, right: 9, left: -17, bottom: 0 }}><defs><linearGradient id="activityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#fb923c" stopOpacity={0.27}/><stop offset="100%" stopColor="#fb923c" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false}/><XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} axisLine={false} interval="preserveStartEnd"/><YAxis allowDecimals={false} tick={{ fill: "#64748b", fontSize: 10 }} tickLine={false} axisLine={false}/><Tooltip contentStyle={TOOLTIP_STYLE}/><Area type="monotone" dataKey="events" name="New events" stroke="#fb923c" strokeWidth={2} fill="url(#activityFill)"/></AreaChart></ResponsiveContainer></div></div>;
}
function CategoryChart({ data }: { data: Array<{ name: string; count: number; color: string }> }) {
  return <div className="chart-card"><div className="chart-heading"><div><h3>Assessment mix</h3><p>Evidence-based source categories</p></div><span className="chart-indicator blue"/></div>{!data.length ? <div className="chart-empty">No events in this period.</div> : <div className="chart-stage"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ top: 0, right: 22, left: 8, bottom: 0 }}><CartesianGrid stroke="#1e293b" strokeDasharray="3 3" horizontal={false}/><XAxis type="number" allowDecimals={false} tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false}/><YAxis type="category" dataKey="name" width={124} tick={{ fill: "#94a3b8", fontSize: 10 }} axisLine={false} tickLine={false}/><Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(148,163,184,0.06)" }}/><Bar dataKey="count" name="Events" radius={[0, 4, 4, 0]} barSize={13}>{data.map((item) => <Cell key={item.name} fill={item.color}/>)}</Bar></BarChart></ResponsiveContainer></div>}</div>;
}
function PriorityChart({ data }: { data: Array<{ name: string; value: number; color: string }> }) {
  const total = data.reduce((sum, item) => sum + item.value, 0);
  return <div className="chart-card"><div className="chart-heading"><div><h3>Triage priority</h3><p>Rule-based, not a probability</p></div><span className="chart-indicator red"/></div><div className="signal-chart-body"><div className="donut-wrap"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius={34} outerRadius={49} paddingAngle={3} stroke="none">{data.map((item) => <Cell key={item.name} fill={item.color}/>)}</Pie><Tooltip contentStyle={TOOLTIP_STYLE}/></PieChart></ResponsiveContainer><div className="donut-total"><strong>{total.toLocaleString("en-IN")}</strong><span>events</span></div></div><div className="signal-legend">{data.map((item) => <div key={item.name}><i style={{ background: item.color }}/><span>{item.name}</span><strong>{item.value.toLocaleString("en-IN")}</strong></div>)}</div></div></div>;
}
function HistoryChart({ months }: { months: HistoryMonth[] | null }) {
  if (!months) return <div className="chart-empty">History unavailable.</div>;
  const data = months.map((m) => ({ ...m, label: new Date(m.month).toLocaleDateString("en-IN", { month: "short", year: "2-digit", timeZone: "UTC" }) }));
  return <div className="chart-stage" style={{ height: 190 }}><ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 8, right: 6, left: -20, bottom: 0 }}><CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false}/><XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 9 }} tickLine={false} axisLine={false} interval={5}/><YAxis allowDecimals={false} tick={{ fill: "#64748b", fontSize: 10 }} tickLine={false} axisLine={false}/><Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value, name) => [String(value), String(name)]}/><Bar dataKey="detections" name="All detections" fill="#fb923c"/><Bar dataKey="night_detections" name="Night detections" fill="#c084fc"/></BarChart></ResponsiveContainer></div>;
}
