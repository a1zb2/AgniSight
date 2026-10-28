"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Crosshair, ImageIcon, LoaderCircle, X } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "@/lib/api";
import {
  formatCoords, formatDate, formatDateTime, formatDistance, formatFrp, formatMonth, formatNumber, formatPercent,
} from "@/lib/format";
import { DAY_COLOR, NIGHT_COLOR, PRIORITY_BY_KEY, SITE_CLASS_LABEL } from "@/lib/taxonomy";
import type { ContextFeature, EventDetail, LocationHistory, ThermalEvent } from "@/lib/types";
import { headline } from "./EventQueue";

type Props = {
  event: ThermalEvent;
  onClose: () => void;
  onZoom: () => void;
  onImagery: () => void;
  onDetail: (detail: EventDetail | null) => void;
};

const GLYPH = { supports: "+", conflicts: "!", context: "·" } as const;
const RELEVANCE_COLOR = { high: "#d95926", medium: "#aaadb3", low: "#5c5f66" } as const;

export default function Dossier({ event, onClose, onZoom, onImagery, onDetail }: Props) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [history, setHistory] = useState<LocationHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Reset when a different event is selected (render-time state adjustment).
  const [loadedFor, setLoadedFor] = useState(event.id);
  if (loadedFor !== event.id) {
    setLoadedFor(event.id);
    setDetail(null);
    setHistory(null);
    setError(null);
  }

  useEffect(() => {
    const controller = new AbortController();
    const [lon, lat] = event.geometry.coordinates;
    Promise.all([api.event(event.id, controller.signal), api.history(lat, lon, controller.signal)])
      .then(([d, h]) => { setDetail(d); setHistory(h); onDetail(d); })
      .catch((e: Error) => { if (e.name !== "AbortError") setError(e.message); });
    return () => { controller.abort(); onDetail(null); };
  }, [event, onDetail]);

  const p = event.properties;
  const d = detail?.properties;
  const a = d?.assessment;
  const priority = PRIORITY_BY_KEY[p.priority_level];
  const { title: where } = headline(event);
  const place = d?.place?.label ?? p.place_label;

  const copyCoords = () => {
    const [lon, lat] = event.geometry.coordinates;
    void navigator.clipboard?.writeText(`${lat.toFixed(5)}, ${lon.toFixed(5)}`).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  };

  return <aside className="dossier" aria-label="Event dossier">
    <header className="dossier-head">
      <div className="dossier-top">
        <span className="badge"><span className="swatch" style={{ background: priority.color }} />{priority.label} · {p.priority_score}</span>
        <span className="badge" title={a?.strength.definition}>Evidence {p.strength_level}</span>
        <span className="id">{p.event_id}</span>
        <button className="icon-button" onClick={onClose} aria-label="Close dossier" title="Close (Esc)"><X size={16} /></button>
      </div>
      <h1>{a?.title ?? p.category_title}</h1>
      <div className="place">{p.context_name ? `${where} · ` : ""}{place ?? "Location label unavailable"}</div>
      <div className="coords">
        <span className="mono">{formatCoords(event.geometry.coordinates)}</span>
        <button onClick={copyCoords} aria-label="Copy coordinates" title="Copy coordinates">{copied ? <Check size={13} /> : <Copy size={13} />}</button>
      </div>
      <div className="actions">
        <button className="button" onClick={onZoom}><Crosshair size={14} />Zoom to event</button>
        <button className="button" onClick={onImagery}><ImageIcon size={14} />Inspect on Sentinel-2</button>
      </div>
    </header>

    <div className="dossier-body">
      <div className="figures">
        <Figure label="Peak FRP" value={formatFrp(p.max_frp_mw)}
          note={d?.history.prior.mean_frp ? `usual ${formatFrp(d.history.prior.mean_frp)}` : "radiative power"} />
        <Figure label="Detections" value={String(p.observation_count)}
          note={p.day_night === "N" ? "night pass" : p.day_night === "D" ? "day pass" : "day and night"} />
        <Figure label="Active months" value={d ? String(d.history.active_months) : "…"}
          note={d ? `${d.history.calendar_months}/12 calendar` : "since Jan 2024"} />
        <Figure label="Night share" value={d ? formatPercent(d.history.night_share) : "…"}
          note={d ? `of ${formatNumber(d.history.detection_count)} here` : "location history"} />
      </div>

      {error && <div className="notice">{error}</div>}
      {!d && !error && <div className="loading"><LoaderCircle size={16} className="spin" />Loading assessment</div>}

      {d && a && <>
        <section className="section">
          <h2>Why this assessment <small>{a.location_pattern_label}</small></h2>
          <ul className="ledger">
            {a.evidence.map((e, i) => <li key={i}>
              <span className={`glyph ${e.stance}`} title={e.stance}>{GLYPH[e.stance]}</span>
              <span className="source">{e.source}</span>
              <span className="text">{e.text}</span>
            </li>)}
          </ul>
          <p className="footnote">Marks: + supports, ! conflicts, · context. Evidence is {a.strength.level}: {a.strength.supporting_sources.length
            ? `supported by ${a.strength.supporting_sources.join(", ")}` : "no source directly supports the category"}. This is not a probability.</p>
        </section>

        <section className="section">
          <h2>Triage priority <small>{priority.label}</small></h2>
          <table className="points">
            <tbody>
              {a.priority.factors.length === 0 && <tr><td>No factors apply</td><td>0</td></tr>}
              {a.priority.factors.map((f, i) => <tr key={i}><td>{f.label}</td><td>{f.points > 0 ? `+${f.points}` : f.points}</td></tr>)}
            </tbody>
            <tfoot><tr><td>Score (0–100; investigate ≥ 50, review ≥ 25)</td><td>{a.priority.score}</td></tr></tfoot>
          </table>
          <p className="footnote">A rule for ordering the queue, not a probability of fire or harm.</p>
        </section>

        <section className="section">
          <h2>Activity at this location <small>within 750 m</small></h2>
          <HistoryChart history={history} eventStart={p.start_time} />
          <p className="footnote">
            First detected {formatDate(d.history.first_seen)}.{" "}
            {d.history.nasa_typed_count > 0
              ? `NASA labelled ${formatPercent(d.history.nasa_static_share)} of ${formatNumber(d.history.nasa_typed_count)} archived detections here as a static source.`
              : "No NASA source-type labels exist for this location."}
            {d.site && ` Part of ${SITE_CLASS_LABEL[d.site.site_class]?.toLowerCase() ?? d.site.site_class} site ${d.site.site_id}.`}
          </p>
          {history && history.recent_detections.length > 0 && <details className="more" style={{ marginTop: 12 }}>
            <summary>Recent detections ({history.recent_detections.length})</summary>
            <table className="table">
              <thead><tr><th>Observed</th><th>Pass</th><th>Conf.</th><th className="num">FRP</th><th>NASA type</th></tr></thead>
              <tbody>{history.recent_detections.slice(0, 15).map((r) =>
                <tr key={r.id}><td className="mono">{formatDateTime(r.observed_at)}</td><td>{r.day_night === "N" ? "Night" : "Day"}</td><td>{r.confidence ?? "—"}</td><td className="num">{formatFrp(r.frp)}</td><td>{r.firms_type === 2 ? "Static" : r.firms_type === 0 ? "Vegetation" : r.firms_type === 3 ? "Offshore" : r.firms_type === 1 ? "Volcano" : "Not labelled"}</td></tr>)}
              </tbody>
            </table>
          </details>}
        </section>

        <section className="section">
          <h2>Mapped surroundings <small>OpenStreetMap, 1.5 km</small></h2>
          {d.context.features.length === 0
            ? <p>No industrial, mining, waste or power feature is mapped within 1.5 km. OSM coverage of Indian industry is incomplete, so this does not rule out a facility.</p>
            : <table className="table">
              <thead><tr><th>Feature</th><th>Type</th><th className="num">Distance</th></tr></thead>
              <tbody>{groupFeatures(d.context.features).map((f) =>
                <tr key={f.osm_id}>
                  <td><span className="rel" style={{ background: RELEVANCE_COLOR[f.thermal_relevance] }} title={`${f.thermal_relevance} heat relevance`} /><span className="strong">{f.name ?? (f.count > 1 ? `${f.count} unnamed` : "Unnamed")}</span></td>
                  <td>{f.category}</td>
                  <td className="num">{f.count > 1 ? "from " : ""}{formatDistance(f.distance_m)}</td>
                </tr>)}
              </tbody>
            </table>}
          {d.context.features.length > 0 && <p className="footnote">Dot shows heat relevance: orange high (plants, kilns, heavy industry), grey medium, dark low. Proximity is context, not proof of the source.</p>}
        </section>

        <section className="section">
          <h2>Next steps</h2>
          <ol className="steps">{a.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
        </section>

        <section className="section">
          <h2>Limitations</h2>
          <ul className="plain-list">{a.unknowns.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </section>

        <section className="section">
          <details className="more">
            <summary>Detection data</summary>
            <table className="table">
              <tbody>
                <Row k="First detection" v={formatDateTime(p.start_time)} />
                <Row k="Last detection" v={formatDateTime(p.end_time)} />
                <Row k="Satellite" v={`${d.satellites} (VIIRS)`} />
                <Row k="Reported FRP, sum" v={formatFrp(d.reported_frp_sum_mw)} />
                <Row k="Max brightness (I4)" v={d.max_brightness_ti4 ? `${d.max_brightness_ti4} K` : "—"} />
                <Row k="Confidence codes" v={Object.entries(d.confidence_counts).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"} />
                {d.model && <Row k="Static-source model" v={`${formatPercent(d.model.static_probability)} · held-out precision ${formatPercent(d.model.spatial_test.precision)}, recall ${formatPercent(d.model.spatial_test.recall)}`} />}
              </tbody>
            </table>
          </details>
        </section>
      </>}
    </div>
  </aside>;
}

// Collapse unnamed features of the same type into one row.
function groupFeatures(features: ContextFeature[]) {
  const rows: Array<ContextFeature & { count: number }> = [];
  for (const f of features) {
    const same = !f.name && rows.find((r) => !r.name && r.category === f.category);
    if (same) same.count += 1;
    else rows.push({ ...f, count: 1 });
  }
  return rows;
}

function Figure({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="figure"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

function Row({ k, v }: { k: string; v: string }) {
  return <tr><td>{k}</td><td className="strong" style={{ color: "var(--text)" }}>{v}</td></tr>;
}

type TooltipProps = { active?: boolean; label?: string; payload?: Array<{ payload: Record<string, number | string | null> }> };

function HistoryTooltip({ active, payload }: TooltipProps) {
  const row = active && payload?.[0]?.payload;
  if (!row) return null;
  return <div className="chart-tooltip">
    <strong>{String(row.label)}</strong>
    {Number(row.data_days) === 0
      ? <div><span>No satellite data stored for this month</span></div>
      : <>
        <div><span>Day detections</span><span>{row.day}</span></div>
        <div><span>Night detections</span><span>{row.night}</span></div>
        <div><span>Active days</span><span>{row.active_days}</span></div>
        <div><span>Peak FRP</span><span>{formatFrp(row.max_frp as number | null)}</span></div>
      </>}
  </div>;
}

function HistoryChart({ history, eventStart }: { history: LocationHistory | null; eventStart: string }) {
  if (!history) return <div className="chart" style={{ display: "grid", placeItems: "center", color: "var(--text-3)" }}>Loading history…</div>;
  const eventMonth = `${eventStart.slice(0, 7)}-01`;
  const data = history.months.map((m) => ({
    label: formatMonth(m.month),
    month: m.month,
    day: m.detections - m.night_detections,
    night: m.night_detections,
    active_days: m.active_days,
    max_frp: m.max_frp,
    data_days: m.data_days,
  }));
  const eventLabel = data.find((r) => r.month === eventMonth)?.label;

  return <>
    <div className="chart-legend"><span><i style={{ background: DAY_COLOR }} />Day</span><span><i style={{ background: NIGHT_COLOR }} />Night</span>{eventLabel && <span><i style={{ width: 2, height: 10, background: "#e8e9eb", verticalAlign: -1 }} />This event</span>}</div>
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 14, right: 8, bottom: 0, left: 0 }} barCategoryGap={1}>
          <CartesianGrid stroke="#24262b" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#74777e", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#31343a" }} interval={5} />
          <YAxis allowDecimals={false} tick={{ fill: "#74777e", fontSize: 11 }} tickLine={false} axisLine={false} width={34} />
          <Tooltip content={<HistoryTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
          {eventLabel && <ReferenceLine x={eventLabel} stroke="#e8e9eb" strokeOpacity={0.6} />}
          <Bar dataKey="day" stackId="a" fill={DAY_COLOR} isAnimationActive={false} />
          <Bar dataKey="night" stackId="a" fill={NIGHT_COLOR} radius={[2, 2, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  </>;
}
