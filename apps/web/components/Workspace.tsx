"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Flame, Search, X } from "lucide-react";

import { api } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { groupOf } from "@/lib/taxonomy";
import type { CategoryGroup, ContextFeature, DetectionsResponse, EventDetail, Priority, SiteProps, Status, ThermalEvent } from "@/lib/types";
import Analytics from "./Analytics";
import Dossier from "./Dossier";
import EventQueue, { type Range } from "./EventQueue";
import ThermalMap, { type Basemap, type FocusRequest, type Layers } from "./ThermalMap";

type View = "map" | "analytics";

function freshnessColor(hours: number | null | undefined) {
  if (hours === null || hours === undefined) return "#74777e";
  return hours <= 24 ? "#4cb782" : hours <= 72 ? "#f0a020" : "#e04848";
}

export default function Workspace() {
  const [now] = useState(() => Date.now());
  const [view, setView] = useState<View>("map");
  const [events, setEvents] = useState<ThermalEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [detections, setDetections] = useState<DetectionsResponse | null>(null);

  const [range, setRange] = useState<Range>(14);
  const [priorities, setPriorities] = useState<Set<Priority>>(() => new Set(["investigate", "review"]));
  const [group, setGroup] = useState<CategoryGroup | "all">("all");
  const [search, setSearch] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [contextFeatures, setContextFeatures] = useState<ContextFeature[]>([]);
  const [basemap, setBasemap] = useState<Basemap>("dark");
  const [layers, setLayers] = useState<Layers>({ heat: true, sites: true, context: true });
  const [focus, setFocus] = useState<FocusRequest>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    api.events(14)
      .then((r) => setEvents(r.features))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
    api.status().then(setStatus).catch(() => setStatus(null));
    api.detections(14).then(setDetections).catch((e) => console.warn("Detections unavailable", e));
  }, []);

  // Period, category and search scope everything; priority scopes the
  // queue and the event markers; the heat layer shows every detection.
  const scoped = useMemo(() => {
    const cutoff = now - range * 86400000;
    const query = search.trim().toLowerCase();
    return events.filter((e) => {
      const p = e.properties;
      if (new Date(p.end_time).getTime() < cutoff) return false;
      if (group !== "all" && groupOf(p.category) !== group) return false;
      if (query && ![p.event_id, p.site_id, p.place_label, p.context_name, p.category_title]
        .some((v) => v?.toLowerCase().includes(query))) return false;
      return true;
    });
  }, [events, now, range, group, search]);

  const counts = useMemo(() => {
    const c: Record<Priority, number> = { investigate: 0, review: 0, monitor: 0 };
    for (const e of scoped) c[e.properties.priority_level] += 1;
    return c;
  }, [scoped]);

  const queue = useMemo(() => scoped
    .filter((e) => priorities.has(e.properties.priority_level))
    .sort((a, b) => b.properties.priority_score - a.properties.priority_score
      || b.properties.end_time.localeCompare(a.properties.end_time)), [scoped, priorities]);

  // Detections of every in-scope event, as heat points.
  const heat = useMemo(() => {
    if (!detections) return [];
    const inScope = new Set(scoped.map((e) => e.id));
    return detections.rows
      .filter((r) => inScope.has(detections.event_ids[r[4]]))
      .map((r) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [r[0], r[1]] },
        properties: { frp: r[2], night: r[3] },
      }));
  }, [detections, scoped]);

  const selected = useMemo(() => events.find((e) => e.id === selectedId) ?? null, [events, selectedId]);

  const select = useCallback((event: ThermalEvent, fly: boolean) => {
    setSelectedId(event.id);
    if (fly) setFocus({ center: event.geometry.coordinates, zoom: 9.5, nonce: Date.now() });
  }, []);

  const onDetail = useCallback((detail: EventDetail | null) => {
    setContextFeatures(detail?.properties.context.features ?? []);
  }, []);

  const togglePriority = (p: Priority) => setPriorities((current) => {
    const next = new Set(current);
    if (next.has(p)) next.delete(p); else next.add(p);
    return next;
  });

  const openSite = (site: SiteProps) => {
    setView("map");
    const match = events.find((e) => e.properties.site_id === site.site_id);
    if (match) setSelectedId(match.id);
    setBasemap("sentinel");
    setFocus({ center: [site.longitude, site.latitude], zoom: 13, nonce: Date.now() });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName);
      if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); return; }
      if (e.key === "Escape") { if (typing) (e.target as HTMLElement).blur(); else setSelectedId(null); return; }
      if (typing || view !== "map" || !["j", "k", "ArrowDown", "ArrowUp"].includes(e.key)) return;
      e.preventDefault();
      const index = queue.findIndex((x) => x.id === selectedId);
      const step = e.key === "j" || e.key === "ArrowDown" ? 1 : -1;
      const next = queue[Math.min(queue.length - 1, Math.max(0, index + step))];
      if (next) select(next, true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue, selectedId, select, view]);

  const rangeLabel = range === 1 ? "last 24 hours" : `last ${range} days`;
  const gaps = status?.days_without_data_last_30d ?? [];

  return <div className="app">
    <header className="topbar">
      <div className="brand"><Flame size={16} fill="currentColor" />AgniSight</div>
      <nav className="views" aria-label="Views">
        <button aria-pressed={view === "map"} onClick={() => setView("map")}>Map</button>
        <button aria-pressed={view === "analytics"} onClick={() => setView("analytics")}>Analytics</button>
      </nav>
      <label className="search">
        <Search size={14} />
        <input ref={searchRef} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Place, facility, event or site ID" aria-label="Search events" />
        {search ? <button className="icon-button" style={{ width: 20, height: 20 }} onClick={() => setSearch("")} aria-label="Clear search"><X size={12} /></button> : <kbd>/</kbd>}
      </label>
      <div className="freshness" title={gaps.length ? `No data on: ${gaps.join(", ")}` : "No missing days in the last 30 days"}>
        <span className="dot" style={{ background: freshnessColor(status?.hours_since_latest) }} />
        <span>NOAA-21 VIIRS<span className="long"> · latest {formatDateTime(status?.latest_observation)}</span> · {formatRelative(status?.latest_observation, now)}</span>
      </div>
    </header>

    <main style={{ position: "relative", minHeight: 0 }}>
      <div className="workspace" style={{ height: "100%" }}>
        <EventQueue
          events={queue} counts={counts} priorities={priorities} onTogglePriority={togglePriority}
          range={range} onRange={setRange} group={group} onGroup={setGroup}
          selectedId={selectedId} onSelect={(e) => select(e, true)} now={now} loading={loading}
        />
        <ThermalMap
          events={queue} heat={heat} selected={selected} contextFeatures={selected ? contextFeatures : []}
          basemap={basemap} onBasemap={setBasemap} layers={layers} onLayers={setLayers}
          focus={focus} onSelect={(id) => { const e = events.find((x) => x.id === id); if (e) select(e, false); }}
          onSiteClick={(siteId, center) => {
            const current = scoped.find((e) => e.properties.site_id === siteId);
            if (current) select(current, true);
            else setFocus({ center, zoom: 12, nonce: Date.now() });
          }}
          loading={loading} error={error}
        />
        {selected && <Dossier
          event={selected}
          onClose={() => setSelectedId(null)}
          onZoom={() => setFocus({ center: selected.geometry.coordinates, zoom: 11, nonce: Date.now() })}
          onImagery={() => { setBasemap("sentinel"); setFocus({ center: selected.geometry.coordinates, zoom: 14, nonce: Date.now() }); }}
          onDetail={onDetail}
        />}
      </div>
      {view === "analytics" && <div style={{ position: "absolute", inset: 0, zIndex: 5, background: "var(--bg)", display: "flex" }}>
        <Analytics events={scoped} rangeLabel={rangeLabel} status={status} onOpenSite={openSite} />
      </div>}
    </main>
  </div>;
}
