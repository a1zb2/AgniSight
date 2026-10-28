export type Priority = "investigate" | "review" | "monitor";
export type CategoryGroup = "industrial" | "unmapped" | "vegetation" | "offshore" | "unresolved";
export type Stance = "supports" | "conflicts" | "context";
export type Point = { type: "Point"; coordinates: [number, number] };

export type Place = {
  name: string | null;
  kind: string | null;
  distance_km: number | null;
  district: string | null;
  state: string | null;
  label: string | null;
};

export type EventProps = {
  event_id: string;
  observation_count: number;
  start_time: string;
  end_time: string;
  max_frp_mw: number | null;
  day_night: string;
  category: string;
  category_title: string;
  short_title: string;
  priority_level: Priority;
  priority_score: number;
  strength_level: "strong" | "moderate" | "limited";
  location_pattern: string;
  site_id: string | null;
  context_name: string | null;
  place_label: string | null;
};

export type ThermalEvent = { type: "Feature"; id: string; geometry: Point; properties: EventProps };

export type EventsResponse = {
  type: "FeatureCollection";
  metadata: { window_start: string; window_end: string; latest_observation: string | null; events: number; observations: number };
  features: ThermalEvent[];
};

// [longitude, latitude, frp_mw, night (0/1), event_index]
export type DetectionRow = [number, number, number, number, number];
export type DetectionsResponse = { event_ids: string[]; rows: DetectionRow[] };

export type Evidence = { stance: Stance; source: string; text: string; weight: "strong" | "moderate" | "weak" };

export type ContextFeature = {
  osm_id: string;
  name: string | null;
  category: string;
  group: string;
  group_label: string;
  thermal_relevance: "high" | "medium" | "low";
  distance_m: number;
  relation: "inside" | "adjacent" | "nearby" | "vicinity";
  latitude: number;
  longitude: number;
};

export type EventDetail = {
  id: string;
  geometry: Point;
  properties: EventProps & {
    satellites: string;
    span_hours: number;
    reported_frp_sum_mw: number | null;
    max_brightness_ti4: number | null;
    confidence_counts: Record<string, number>;
    place: Place | null;
    assessment: {
      title: string;
      location_pattern_label: string;
      evidence: Evidence[];
      unknowns: string[];
      next_steps: string[];
      strength: { level: string; supporting_sources: string[]; conflicts: number; definition: string };
      priority: { score: number; level: Priority; factors: Array<{ points: number; label: string }>; definition: string };
    };
    history: {
      detection_count: number;
      active_days: number;
      active_months: number;
      calendar_months: number;
      first_seen: string | null;
      last_seen: string | null;
      night_share: number | null;
      mean_frp: number | null;
      max_frp: number | null;
      nasa_typed_count: number;
      nasa_static_share: number | null;
      prior: { active_days: number; mean_frp: number | null; last_date: string | null };
    };
    site: {
      site_id: string;
      site_class: string;
      distance_m: number;
      active_months: number;
      calendar_months: number;
      first_seen: string | null;
      context_name: string | null;
    } | null;
    context: { relation: string; feature_count_1500m: number; features: ContextFeature[] };
    model: { static_probability: number; name: string; spatial_test: { precision: number; recall: number } } | null;
  };
};

export type HistoryMonth = {
  month: string;
  detections: number;
  active_days: number;
  night_detections: number;
  max_frp: number | null;
  mean_frp: number | null;
  data_days: number;
};

export type RecentDetection = {
  id: number;
  observed_at: string;
  frp: number | null;
  confidence: string | null;
  day_night: string | null;
  firms_type: number | null;
};

export type LocationHistory = { months: HistoryMonth[]; recent_detections: RecentDetection[] };

export type Status = {
  source: string;
  observations: number;
  first_observation: string | null;
  latest_observation: string | null;
  hours_since_latest: number | null;
  observations_last_24h: number;
  days_without_data_last_30d: string[];
  sites: Record<string, number>;
  pipeline: Record<string, { finished_at: string | null; details: Record<string, unknown> }>;
};

export type SiteProps = {
  site_id: string;
  site_class: "persistent" | "recurrent" | "seasonal";
  detection_count: number;
  active_months: number;
  calendar_months: number;
  night_share: number;
  mean_frp: number | null;
  nasa_static_share: number | null;
  nasa_typed_count: number;
  first_seen: string;
  last_seen: string;
  context_relation: string;
  context_group: string | null;
  context_category: string | null;
  context_name: string | null;
  place_label: string | null;
  latitude: number;
  longitude: number;
};

export type SitesResponse = { type: "FeatureCollection"; features: Array<{ type: "Feature"; id: string; geometry: Point; properties: SiteProps }> };

export type Analytics = {
  monthly_detections: Array<{ month: string; detections: number; night_detections: number; nasa_static: number; nasa_labelled: number; data_days: number }>;
  sites_by_class_and_context: Array<{ site_class: string; context_group: string; sites: number; detections: number }>;
};
