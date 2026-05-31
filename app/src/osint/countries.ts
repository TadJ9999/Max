// Join the world-atlas map polygons to the engine's per-country heat.
//
// The atlas (Natural Earth via `world-atlas`) keys each country by its ISO-3166
// *numeric* id; the engine reports heat keyed by ISO-A3. This is the bridge.
// Only countries the engine's gazetteer knows are listed — others render as
// inert wireframe with no heat. Singapore etc. have no polygon at 110m and are
// simply absent from the map.

// ISO numeric (zero-padded, 3 chars) -> ISO-A3
const NUM_TO_ISO: Record<string, string> = {
  "840": "USA", "826": "GBR", "804": "UKR", "643": "RUS", "156": "CHN",
  "158": "TWN", "392": "JPN", "410": "KOR", "408": "PRK", "356": "IND",
  "586": "PAK", "004": "AFG", "364": "IRN", "368": "IRQ", "376": "ISR",
  "275": "PSE", "760": "SYR", "422": "LBN", "682": "SAU", "784": "ARE",
  "634": "QAT", "887": "YEM", "792": "TUR", "818": "EGY", "434": "LBY",
  "788": "TUN", "012": "DZA", "504": "MAR", "566": "NGA", "231": "ETH",
  "404": "KEN", "710": "ZAF", "729": "SDN", "728": "SSD", "706": "SOM",
  "180": "COD", "466": "MLI", "288": "GHA", "120": "CMR", "250": "FRA",
  "276": "DEU", "380": "ITA", "724": "ESP", "620": "PRT", "528": "NLD",
  "056": "BEL", "756": "CHE", "040": "AUT", "616": "POL", "752": "SWE",
  "578": "NOR", "246": "FIN", "208": "DNK", "372": "IRL", "300": "GRC",
  "203": "CZE", "348": "HUN", "642": "ROU", "100": "BGR", "688": "SRB",
  "191": "HRV", "070": "BIH", "112": "BLR", "268": "GEO", "051": "ARM",
  "031": "AZE", "398": "KAZ", "860": "UZB", "124": "CAN", "484": "MEX",
  "076": "BRA", "032": "ARG", "152": "CHL", "170": "COL", "862": "VEN",
  "604": "PER", "218": "ECU", "068": "BOL", "192": "CUB", "332": "HTI",
  "036": "AUS", "554": "NZL", "360": "IDN", "458": "MYS", "764": "THA",
  "704": "VNM", "608": "PHL", "104": "MMR", "050": "BGD", "144": "LKA",
  "524": "NPL",
};

/** Resolve a TopoJSON feature id (numeric, maybe unpadded) to ISO-A3. */
export function isoForFeatureId(id: string | number | undefined): string | null {
  if (id === undefined || id === null) return null;
  const key = String(id).padStart(3, "0");
  return NUM_TO_ISO[key] ?? null;
}

// ---- severity (criticality) tiers ----
// Sleek, dark-ops threat scale: cyan (quiet) escalating to rose-red (critical),
// not a rainbow heatmap. `color` is the marker hue; the country fill uses a
// translucent wash of it plus a same-hue glow.

export const SEV = { LOW: 0, MEDIUM: 1, HIGH: 2, CRITICAL: 3 } as const;

export type SeverityTier = {
  level: number;
  key: string;
  label: string;
  color: string;
};

// High → low (the order the filter bar renders).
export const SEVERITY_TIERS: SeverityTier[] = [
  { level: 3, key: "critical", label: "Critical", color: "#ff2e63" },
  { level: 2, key: "high", label: "High", color: "#ff8c42" },
  { level: 1, key: "medium", label: "Medium", color: "#f5c542" },
  { level: 0, key: "low", label: "Low", color: "#22d3ee" },
];

const BY_LEVEL = new Map(SEVERITY_TIERS.map((t) => [t.level, t]));

export function severityTier(level: number): SeverityTier {
  return BY_LEVEL.get(level) ?? SEVERITY_TIERS[SEVERITY_TIERS.length - 1];
}

export function severityColor(level: number): string {
  return severityTier(level).color;
}
