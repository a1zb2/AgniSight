import type { Analytics, DetectionsResponse, EventDetail, EventsResponse, LocationHistory, SitesResponse, Status } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1${path}`, { signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? `${path} returned ${response.status}`);
  }
  return body as T;
}

export const api = {
  events: (days = 14) => get<EventsResponse>(`/events/geojson?days=${days}`),
  detections: (days = 14) => get<DetectionsResponse>(`/events/detections?days=${days}`),
  event: (id: string, signal?: AbortSignal) => get<EventDetail>(`/events/${encodeURIComponent(id)}`, signal),
  history: (lat: number, lon: number, signal?: AbortSignal) =>
    get<LocationHistory>(`/history/location?latitude=${lat}&longitude=${lon}&radius_m=750`, signal),
  sites: (siteClass?: string) => get<SitesResponse>(`/sites/geojson${siteClass ? `?site_class=${siteClass}` : ""}`),
  status: () => get<Status>("/status"),
  analytics: () => get<Analytics>("/analytics/overview"),
};
