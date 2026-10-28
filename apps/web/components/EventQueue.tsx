"use client";

import { useEffect, useRef, useState } from "react";

import { formatCompact, formatCoords, formatFrp, formatNumber, formatRelative } from "@/lib/format";
import { GROUPS, PRIORITIES, PRIORITY_BY_KEY } from "@/lib/taxonomy";
import type { CategoryGroup, Priority, ThermalEvent } from "@/lib/types";

export type Range = 1 | 7 | 14;
const PAGE = 120;

type Props = {
  events: ThermalEvent[];
  counts: Record<Priority, number>;
  priorities: Set<Priority>;
  onTogglePriority: (p: Priority) => void;
  range: Range;
  onRange: (r: Range) => void;
  group: CategoryGroup | "all";
  onGroup: (g: CategoryGroup | "all") => void;
  selectedId: string | null;
  onSelect: (event: ThermalEvent) => void;
  now: number;
  loading: boolean;
};

export function headline(event: ThermalEvent): { title: string; region: string | null } {
  const { context_name, place_label } = event.properties;
  const [place, region] = place_label ? place_label.split(" · ") : [null, null];
  if (context_name) return { title: context_name, region: place_label };
  if (place) return { title: place, region: region ?? null };
  return { title: formatCoords(event.geometry.coordinates), region: null };
}

export default function EventQueue(props: Props) {
  const { events, selectedId, now } = props;
  const [limit, setLimit] = useState(PAGE);
  const listRef = useRef<HTMLDivElement | null>(null);

  // Reset paging whenever the filtered set changes.
  const [lastEvents, setLastEvents] = useState(events);
  if (lastEvents !== events) {
    setLastEvents(events);
    setLimit(PAGE);
  }

  useEffect(() => {
    if (!selectedId) return;
    listRef.current?.querySelector(`[data-id="${CSS.escape(selectedId)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  const detections = events.reduce((sum, e) => sum + e.properties.observation_count, 0);

  return <aside className="queue" aria-label="Investigation queue">
    <div className="queue-head">
      <div className="queue-title">
        <h2>Investigation queue</h2>
        <span>{formatNumber(events.length)} events · {formatNumber(detections)} detections</span>
      </div>
      <div className="filter-row">
        <div className="segmented" role="group" aria-label="Period">
          {([1, 7, 14] as Range[]).map((r) =>
            <button key={r} aria-pressed={props.range === r} onClick={() => props.onRange(r)}>{r === 1 ? "24 h" : `${r} days`}</button>)}
        </div>
        <select className="select" aria-label="Assessment" value={props.group} onChange={(e) => props.onGroup(e.target.value as CategoryGroup | "all")} style={{ flex: 1 }}>
          <option value="all">All assessments</option>
          {GROUPS.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
        </select>
      </div>
      <div className="filter-row" role="group" aria-label="Priority">
        {PRIORITIES.map((p) =>
          <button key={p.key} className="chip" aria-pressed={props.priorities.has(p.key)} onClick={() => props.onTogglePriority(p.key)}>
            <span className="swatch" style={{ background: p.color }} />{p.label}<b>{formatCompact(props.counts[p.key])}</b>
          </button>)}
      </div>
    </div>

    <div className="queue-list" ref={listRef}>
      {!props.loading && events.length === 0 && <div className="queue-empty">
        No events match these filters.{props.priorities.has("monitor") ? "" : " Monitor-level events are hidden; enable them above to see routine activity."}
      </div>}
      {events.slice(0, limit).map((event) => {
        const p = event.properties;
        const { title, region } = headline(event);
        return <button key={event.id} data-id={event.id} className="queue-row" aria-current={selectedId === event.id} onClick={() => props.onSelect(event)}>
          <span className="bar" style={{ background: PRIORITY_BY_KEY[p.priority_level].color }} />
          <span className="title">{title}</span>
          <span className="score" title={`${PRIORITY_BY_KEY[p.priority_level].label}: triage score ${p.priority_score}/100`}>{p.priority_score}</span>
          <span className="meta">{p.short_title}{region ? ` · ${region}` : ""}</span>
          <span className="meta">{p.observation_count} detection{p.observation_count === 1 ? "" : "s"} · {formatFrp(p.max_frp_mw)} peak · {formatRelative(p.end_time, now)}</span>
        </button>;
      })}
      {events.length > limit && <div className="queue-more">
        Showing {formatNumber(limit)} of {formatNumber(events.length)} ·{" "}
        <button onClick={() => setLimit((n) => n + PAGE * 4)}>show more</button>
      </div>}
    </div>
  </aside>;
}
