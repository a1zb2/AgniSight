"use client";

import { useEffect, useRef, useState } from "react";
import { Map as MapLibreMap, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import type { ExpressionSpecification, GeoJSONSource, MapLayerMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { LoaderCircle } from "lucide-react";

import { api } from "@/lib/api";
import { formatDate, formatDateTime, formatFrp } from "@/lib/format";
import { PRIORITIES, PRIORITY_BY_KEY } from "@/lib/taxonomy";
import type { ContextFeature, ThermalEvent } from "@/lib/types";

setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

export type Basemap = "dark" | "sentinel" | "viirs";
export type Layers = { heat: boolean; sites: boolean; context: boolean };
export type FocusRequest = { center: [number, number]; zoom: number; nonce: number } | null;

const INDIA_BOUNDS: [[number, number], [number, number]] = [[68, 6], [98, 37.5]];
const EMPTY = { type: "FeatureCollection" as const, features: [] };
// Latest complete UTC day of daily VIIRS imagery.
const VIIRS_DATE = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

const BASEMAPS: Record<Basemap, { label: string; note: string }> = {
  dark: { label: "Overview", note: "" },
  sentinel: {
    label: "Sentinel-2",
    note: "Sentinel-2 cloudless mosaic, 2021 (10 m). Shows site layout, not current conditions.",
  },
  viirs: {
    label: "VIIRS daily",
    note: `VIIRS NOAA-20 true colour, ${formatDate(VIIRS_DATE)} (≈375 m). Same-day smoke and cloud.`,
  },
};

// Sequential, one hue: deep orange (faint) to near-white (intense).
const HEAT_RAMP: ExpressionSpecification = ["interpolate", ["linear"], ["get", "frp"],
  0, "#c2410c", 8, "#ea580c", 30, "#f97316", 100, "#fdba74"];
const HEAT_CORE_RAMP: ExpressionSpecification = ["interpolate", ["linear"], ["get", "frp"],
  0, "#f97316", 15, "#fdba74", 80, "#fff1e0"];

// Radius at a given zoom for faint (0 MW), typical (20 MW) and intense (150 MW).
function byFrp(faint: number, typical: number, intense: number): ExpressionSpecification {
  return ["interpolate", ["linear"], ["get", "frp"], 0, faint, 20, typical, 150, intense];
}

function fc(features: unknown[]) {
  return { type: "FeatureCollection", features } as GeoJSON.FeatureCollection;
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

type Props = {
  events: ThermalEvent[];
  heat: GeoJSON.Feature[];
  selected: ThermalEvent | null;
  contextFeatures: ContextFeature[];
  basemap: Basemap;
  onBasemap: (value: Basemap) => void;
  layers: Layers;
  onLayers: (value: Layers) => void;
  focus: FocusRequest;
  onSelect: (id: string) => void;
  loading: boolean;
  error: string | null;
};

export default function ThermalMap(props: Props) {
  const { events, heat, selected, contextFeatures, basemap, layers, focus, onSelect } = props;
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const onSelectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);

  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new MapLibreMap({
      container: container.current,
      style: {
        version: 8,
        // No basemap with drawn political boundaries: third-party world
        // basemaps do not follow India's official boundary depiction.
        sources: {
          sentinel: {
            type: "raster", tileSize: 256, maxzoom: 15,
            tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg"],
            attribution: "Sentinel-2 cloudless 2021 by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2021)",
          },
          viirs: {
            type: "raster", tileSize: 256, maxzoom: 9,
            tiles: [`https://gibs.earthdata.nasa.gov/wmts/epsg3857/all/VIIRS_NOAA20_CorrectedReflectance_TrueColor/default/${VIIRS_DATE}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`],
            attribution: "NASA GIBS / EOSDIS",
          },
        },
        layers: [
          {
            // The overview map is the same mosaic, darkened and desaturated so
            // detections carry the colour.
            id: "base-dark", type: "raster", source: "sentinel",
            paint: {
              "raster-saturation": -0.75,
              // Brighter when zoomed in, where terrain detail matters.
              "raster-brightness-max": ["interpolate", ["linear"], ["zoom"], 4, 0.32, 9, 0.5, 13, 0.62],
              "raster-contrast": 0.15,
            },
          },
          { id: "base-sentinel", type: "raster", source: "sentinel", layout: { visibility: "none" } },
          { id: "base-viirs", type: "raster", source: "viirs", layout: { visibility: "none" } },
        ],
      },
      center: [80, 22],
      zoom: 4,
      attributionControl: { compact: true },
      maxZoom: 17,
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: false }), "bottom-right");

    // The dossier opening and closing changes the map's width.
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container.current);

    map.on("load", () => {
      map.resize();
      map.fitBounds(INDIA_BOUNDS, { padding: 24, duration: 0 });
      // Every satellite detection as a heat point: a soft glow plus a
      // bright core, both scaled and coloured by FRP. Built from blurred
      // circles because MapLibre's heatmap layer blanks the whole map on
      // some WebGL setups.
      map.addSource("heat", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "heat-glow", type: "circle", source: "heat",
        layout: { "circle-sort-key": ["get", "frp"] },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            3, byFrp(3, 6, 10),
            6, byFrp(6, 11, 17),
            10, byFrp(18, 28, 40),
            14, byFrp(30, 44, 60)],
          "circle-color": HEAT_RAMP,
          "circle-blur": 1,
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], 3, 0.3, 8, 0.36, 13, 0.32],
        },
      });
      map.addLayer({
        id: "heat-core", type: "circle", source: "heat",
        layout: { "circle-sort-key": ["get", "frp"] },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            3, byFrp(1, 1.5, 2.4),
            8, byFrp(2.4, 3.4, 4.8),
            13, byFrp(4.5, 6.5, 9)],
          "circle-color": HEAT_CORE_RAMP,
          "circle-blur": 0.35,
          "circle-opacity": 0.92,
        },
      });

      map.addSource("sites", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "sites", type: "circle", source: "sites",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 2.5, 9, 7, 13, 14],
          "circle-color": "rgba(144,133,233,0.06)",
          "circle-stroke-color": "#9085e9",
          "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0.55, 9, 0.9],
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 0.8, 10, 1.5],
        },
      });

      map.addSource("events", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "events", type: "circle", source: "events",
        layout: { "circle-sort-key": ["get", "priority_score"] },
        paint: {
          // Assessed events are dark-centred rings so they stand out from
          // the orange heat field; priority is shown by size and colour.
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            4, ["match", ["get", "priority_level"], "investigate", 6, "review", 4.5, 2.5],
            10, ["match", ["get", "priority_level"], "investigate", 11, "review", 8.5, 5],
          ],
          "circle-color": "#0d0e10",
          "circle-opacity": 0.85,
          "circle-stroke-color": ["match", ["get", "priority_level"],
            "investigate", PRIORITY_BY_KEY.investigate.color,
            "review", PRIORITY_BY_KEY.review.color,
            PRIORITY_BY_KEY.monitor.color],
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 2, 10, 3],
        },
      });

      map.addSource("context", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "context", type: "circle", source: "context",
        paint: { "circle-radius": 4.5, "circle-color": "#5aa9f0", "circle-stroke-color": "#0d0e10", "circle-stroke-width": 1.5 },
      });

      map.addSource("selected", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "selected", type: "circle", source: "selected",
        paint: { "circle-radius": 13, "circle-color": "rgba(255,255,255,0.04)", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 },
      });

      const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "280px" });
      const hover = (html: (p: Record<string, unknown>) => string) => (e: MapLayerMouseEvent) => {
        const feature = e.features?.[0];
        if (!feature || feature.geometry.type !== "Point") return;
        map.getCanvas().style.cursor = "pointer";
        popup.setLngLat(feature.geometry.coordinates as [number, number]).setHTML(html(feature.properties ?? {})).addTo(map);
      };
      const leave = () => { map.getCanvas().style.cursor = ""; popup.remove(); };

      map.on("mousemove", "events", hover((p) => {
        const where = String(p.context_name || p.place_label || "");
        return `<div class="tip-title">${escapeHtml(String(p.short_title))}</div>`
          + (where && where !== "null" ? `<div>${escapeHtml(where)}</div>` : "")
          + `<div class="tip-meta">${p.observation_count} detection${p.observation_count === 1 ? "" : "s"} · ${formatFrp(Number(p.max_frp_mw) || null)} · ${formatDateTime(String(p.end_time))}</div>`;
      }));
      map.on("mouseleave", "events", leave);
      map.on("mousemove", "sites", hover((p) => {
        const where = p.context_name && p.context_name !== "null" ? String(p.context_name) : String(p.place_label ?? "Unmapped location");
        return `<div class="tip-title">${escapeHtml(where)}</div>`
          + `<div class="tip-meta">Persistent site · active ${p.calendar_months}/12 calendar months · ${Math.round(Number(p.night_share) * 100)}% night</div>`;
      }));
      map.on("mouseleave", "sites", leave);
      map.on("click", "events", (e) => {
        const id = e.features?.[0]?.properties?.event_id;
        if (id) onSelectRef.current(String(id));
      });

      api.sites("persistent")
        .then((sites) => (map.getSource("sites") as GeoJSONSource).setData(sites as unknown as GeoJSON.FeatureCollection))
        .catch((error) => console.warn("Persistent sites unavailable", error));

      setReady(true);
    });

    return () => { observer.disconnect(); map.remove(); mapRef.current = null; };
  }, []);

  const source = (id: string) => mapRef.current?.getSource(id) as GeoJSONSource | undefined;

  useEffect(() => { if (ready) source("events")?.setData(fc(events)); }, [ready, events]);
  useEffect(() => { if (ready) source("heat")?.setData(fc(heat)); }, [ready, heat]);
  useEffect(() => { if (ready) source("selected")?.setData(fc(selected ? [selected] : [])); }, [ready, selected]);
  useEffect(() => {
    if (!ready) return;
    source("context")?.setData(fc(contextFeatures.map((f) => ({
      type: "Feature", geometry: { type: "Point", coordinates: [f.longitude, f.latitude] }, properties: { name: f.name },
    }))));
  }, [ready, contextFeatures]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const id of ["dark", "sentinel", "viirs"] as Basemap[]) {
      map.setLayoutProperty(`base-${id}`, "visibility", id === basemap ? "visible" : "none");
    }
    for (const id of ["heat-glow", "heat-core"]) {
      map.setLayoutProperty(id, "visibility", layers.heat ? "visible" : "none");
    }
    map.setLayoutProperty("sites", "visibility", layers.sites ? "visible" : "none");
    map.setLayoutProperty("context", "visibility", layers.context ? "visible" : "none");
  }, [ready, basemap, layers]);

  useEffect(() => {
    if (!ready || !focus) return;
    mapRef.current?.flyTo({ center: focus.center, zoom: focus.zoom, speed: 1.4, essential: true });
  }, [ready, focus]);

  const note = BASEMAPS[basemap].note;

  return <section className="map-wrap" aria-label="Thermal events map">
    <div className="map-canvas" ref={container} />
    {note && <div className="imagery-note map-card">{note}</div>}

    <div className="map-tools">
      <div className="basemaps map-card" role="group" aria-label="Basemap">
        {(Object.keys(BASEMAPS) as Basemap[]).map((key) =>
          <button key={key} aria-pressed={basemap === key} onClick={() => props.onBasemap(key)}>{BASEMAPS[key].label}</button>)}
      </div>
      <div className="layers map-card">
        <label><input type="checkbox" checked={layers.heat} onChange={(e) => props.onLayers({ ...layers, heat: e.target.checked })} />Satellite detections<span className="key" style={{ background: "radial-gradient(#fff1e0, #f97316 55%, transparent 75%)" }} /></label>
        <label><input type="checkbox" checked={layers.sites} onChange={(e) => props.onLayers({ ...layers, sites: e.target.checked })} />Persistent heat sites<span className="key" style={{ border: "1.5px solid #9085e9" }} /></label>
        <label><input type="checkbox" checked={layers.context} onChange={(e) => props.onLayers({ ...layers, context: e.target.checked })} />Mapped facilities near selection<span className="key" style={{ background: "#5aa9f0" }} /></label>
      </div>
    </div>

    <div className="legend map-card" aria-label="Legend">
      {PRIORITIES.map((p, i) => <div key={p.key}><i style={{ width: 11 - i * 2, height: 11 - i * 2, margin: `${i}px`, background: "#0d0e10", border: `2px solid ${p.color}` }} />{p.label}</div>)}
      <div><i style={{ width: 11, height: 11, background: "radial-gradient(#fff1e0, #f97316 50%, rgba(234,88,12,0.2) 75%)" }} />Satellite detection, brighter = more FRP</div>
    </div>

    {props.loading && <div className="map-status map-card"><LoaderCircle size={16} className="spin" />Assessing recent detections…</div>}
    {props.error && <div className="map-status map-card error">Could not load events: {props.error}</div>}
  </section>;
}
