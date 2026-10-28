import type { CategoryGroup, Priority } from "./types";

// Assessment categories (backend) folded into five display groups.
const GROUP_OF: Record<string, CategoryGroup> = {
  industrial_source: "industrial",
  industrial_episodic: "industrial",
  kiln_activity: "industrial",
  extraction_source: "industrial",
  extraction_activity: "industrial",
  waste_source: "industrial",
  waste_activity: "industrial",
  unmapped_source: "unmapped",
  vegetation_candidate: "vegetation",
  offshore_source: "offshore",
  offshore_anomaly: "offshore",
  volcanic: "offshore",
  unresolved: "unresolved",
};

export function groupOf(category: string): CategoryGroup {
  return GROUP_OF[category] ?? "unresolved";
}

// Fixed order; colours follow the group, never its rank. Validated
// (dataviz validate_palette.js, dark, surface #141518): all checks pass.
export const GROUPS: Array<{ key: CategoryGroup; label: string; short: string; color: string }> = [
  { key: "industrial", label: "Mapped industry, mining, waste", short: "Industry", color: "#d95926" },
  { key: "unmapped", label: "Persistent, no mapped facility", short: "Unmapped persistent", color: "#9085e9" },
  { key: "vegetation", label: "Vegetation or crop burning", short: "Vegetation", color: "#199e70" },
  { key: "offshore", label: "Offshore or volcanic", short: "Offshore", color: "#3987e5" },
  { key: "unresolved", label: "Unresolved", short: "Unresolved", color: "#7d7f85" },
];

export const GROUP_BY_KEY = Object.fromEntries(GROUPS.map((g) => [g.key, g])) as Record<CategoryGroup, (typeof GROUPS)[number]>;

// Priority is a status, so it uses the reserved status colours and is
// always shown with its name.
export const PRIORITIES: Array<{ key: Priority; label: string; color: string }> = [
  { key: "investigate", label: "Investigate", color: "#e04848" },
  { key: "review", label: "Review", color: "#f0a020" },
  { key: "monitor", label: "Monitor", color: "#8a8c92" },
];

export const PRIORITY_BY_KEY = Object.fromEntries(PRIORITIES.map((p) => [p.key, p])) as Record<Priority, (typeof PRIORITIES)[number]>;

export const SITE_CLASS_LABEL: Record<string, string> = {
  persistent: "Year-round persistent",
  recurrent: "Recurring",
  seasonal: "Seasonal",
};

export const CONTEXT_GROUP_LABEL: Record<string, string> = {
  thermal_power: "Thermal power plant",
  brick_kiln: "Brick kiln",
  heavy_industry: "Heavy industry",
  industrial_area: "Industrial area",
  extraction: "Mine or quarry",
  waste: "Landfill",
  storage: "Storage or depot",
  other_power: "Other power plant",
  utility: "Utility",
  unmapped: "No mapped facility",
};


// Day/night split in history charts (validated pair, dark surface).
export const DAY_COLOR = "#c98500";
export const NIGHT_COLOR = "#3987e5";
