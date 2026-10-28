"use client";

import { useEffect, useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "@/lib/api";
import { formatCompact, formatDate, formatFrp, formatMonth, formatNumber, formatPercent } from "@/lib/format";
import { CONTEXT_GROUP_LABEL, DAY_COLOR, GROUPS, NIGHT_COLOR, groupOf } from "@/lib/taxonomy";
import type { Analytics as AnalyticsData, SiteProps, SitesResponse, Status, ThermalEvent } from "@/lib/types";

type Props = {
  events: ThermalEvent[];
  rangeLabel: string;
  status: Status | null;
  onOpenSite: (site: SiteProps) => void;
};

type TooltipProps = { active?: boolean; payload?: Array<{ payload: Record<string, number | string> }> };

function MonthlyTooltip({ active, payload }: TooltipProps) {
  const row = active && payload?.[0]?.payload;
  if (!row) return null;
  return <div className="chart-tooltip">
    <strong>{String(row.label)}</strong>
    <div><span>Day detections</span><span>{formatNumber(Number(row.day))}</span></div>
    <div><span>Night detections</span><span>{formatNumber(Number(row.night))}</span></div>
    <div><span>Days with data</span><span>{row.data_days}</span></div>
  </div>;
}

export default function Analytics({ events, rangeLabel, status, onOpenSite }: Props) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [sites, setSites] = useState<SitesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.analytics(), api.sites("persistent")])
      .then(([a, s]) => { setData(a); setSites(s); })
      .catch((e: Error) => setError(e.message));
  }, []);

  const monthly = useMemo(() => (data?.monthly_detections ?? []).map((m) => ({
    label: formatMonth(m.month),
    day: m.detections - m.night_detections,
    night: m.night_detections,
    data_days: m.data_days,
  })), [data]);

  const mix = useMemo(() => GROUPS.map((g) => ({
    ...g, count: events.filter((e) => groupOf(e.properties.category) === g.key).length,
  })), [events]);
  const mixMax = Math.max(1, ...mix.map((m) => m.count));

  const persistentByContext = useMemo(() => {
    const rows = (data?.sites_by_class_and_context ?? []).filter((r) => r.site_class === "persistent");
    return rows.map((r) => ({ label: CONTEXT_GROUP_LABEL[r.context_group] ?? r.context_group, sites: r.sites }))
      .sort((a, b) => b.sites - a.sites);
  }, [data]);
  const contextMax = Math.max(1, ...persistentByContext.map((r) => r.sites));

  const siteRows = useMemo(() => (sites?.features ?? []).map((f) => f.properties)
    .sort((a, b) => b.detection_count - a.detection_count).slice(0, 25), [sites]);

  const registry = status?.pipeline?.registry_build?.details as { sites?: { persistent_sites_not_flagged_static_by_nasa?: number } } | undefined;
  const unflagged = registry?.sites?.persistent_sites_not_flagged_static_by_nasa;
  const persistentCount = status?.sites?.persistent;

  if (error) return <div className="analytics"><div className="notice">Analytics unavailable: {error}</div></div>;

  return <div className="analytics">
    <div className="analytics-inner">
      <header>
        <h1>Thermal activity across India</h1>
        <p>NOAA-21 VIIRS detections since January 2024, the persistent heat sources derived from them, and how the current {rangeLabel} of events was assessed.</p>
      </header>

      <div className="kpis">
        <div className="kpi"><span>Stored detections</span><strong>{status ? formatCompact(status.observations) : "—"}</strong><small>since {formatDate(status?.first_observation)}</small></div>
        <div className="kpi"><span>Year-round persistent sites</span><strong>{persistentCount ?? "—"}</strong><small>≥ 8 calendar months, mostly at night</small></div>
        <div className="kpi"><span>Persistent, not flagged by NASA</span><strong>{unflagged ?? "—"}</strong><small>NASA static label below 50% at the site</small></div>
        <div className="kpi"><span>Events in the {rangeLabel}</span><strong>{formatNumber(events.length)}</strong><small>{formatNumber(events.filter((e) => e.properties.priority_level !== "monitor").length)} in the review queue</small></div>
      </div>

      <div className="panel">
        <h2>Detections per month</h2>
        <p>National totals by overpass. The spring peak recurs each year; January 2024 is partial (data from 17 Jan). Hover a month for its days of data.</p>
        <div className="chart-legend"><span><i style={{ background: DAY_COLOR }} />Day</span><span><i style={{ background: NIGHT_COLOR }} />Night</span></div>
        {!data ? <div className="loading"><LoaderCircle size={16} className="spin" />Loading</div> :
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthly} margin={{ top: 8, right: 8, bottom: 0, left: 4 }} barCategoryGap={2}>
                <CartesianGrid stroke="#24262b" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "#74777e", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#31343a" }} interval={2} />
                <YAxis tick={{ fill: "#74777e", fontSize: 11 }} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => formatCompact(v)} />
                <Tooltip content={<MonthlyTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                <Bar dataKey="day" stackId="a" fill={DAY_COLOR} isAnimationActive={false} />
                <Bar dataKey="night" stackId="a" fill={NIGHT_COLOR} radius={[2, 2, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>}
      </div>

      <div className="panel-grid">
        <div className="panel">
          <h2>Assessment of current events</h2>
          <p>{formatNumber(events.length)} events in the {rangeLabel}, by evidence-based category.</p>
          <div className="hbars">
            {mix.map((m) => <div className="hbar" key={m.key}>
              <span className="label">{m.label}</span>
              <span className="track"><span className="fill" style={{ display: "block", width: `${(m.count / mixMax) * 100}%`, background: m.color }} /></span>
              <span className="value">{formatNumber(m.count)}</span>
            </div>)}
          </div>
        </div>
        <div className="panel">
          <h2>Persistent sites by mapped context</h2>
          <p>What OpenStreetMap shows at or near each year-round site.</p>
          <div className="hbars">
            {persistentByContext.map((r) => <div className="hbar" key={r.label}>
              <span className="label">{r.label}</span>
              <span className="track"><span className="fill" style={{ display: "block", width: `${(r.sites / contextMax) * 100}%`, background: "#9085e9" }} /></span>
              <span className="value">{r.sites}</span>
            </div>)}
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Largest persistent heat sources</h2>
        <p>Top 25 year-round sites by detections since January 2024. Select one to open it on the map.</p>
        <table className="table">
          <thead><tr>
            <th>Site</th><th>Location</th><th className="num">Detections</th><th className="num">Calendar months</th>
            <th className="num">Night</th><th className="num">NASA static</th><th className="num">Mean FRP</th><th>Last seen</th>
          </tr></thead>
          <tbody>{siteRows.map((s) => <tr key={s.site_id}>
            <td><button className="link" onClick={() => onOpenSite(s)}>{s.context_name ?? "No mapped facility"}</button>
              <div className="faint">{s.context_category ?? "—"}</div></td>
            <td>{s.place_label ?? "—"}</td>
            <td className="num">{formatNumber(s.detection_count)}</td>
            <td className="num">{s.calendar_months}/12</td>
            <td className="num">{formatPercent(s.night_share)}</td>
            <td className="num" style={{ color: (s.nasa_static_share ?? 0) < 0.5 ? "#f0a020" : undefined }}
              title={(s.nasa_static_share ?? 0) < 0.5 ? "NASA does not flag this site as a static source" : undefined}>
              {formatPercent(s.nasa_static_share)}</td>
            <td className="num">{formatFrp(s.mean_frp)}</td>
            <td className="mono">{formatDate(s.last_seen)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </div>
  </div>;
}
