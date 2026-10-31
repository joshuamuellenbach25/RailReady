// Phase 16 (REQ-1604): WGS84 coordinate validation shared by the map entry and pins. 0 is a valid coordinate.
export const OUT_OF_RANGE = "Location is out of range";

export function parseLatLon(latText: string, lonText: string): { lat: number; lon: number } | { error: string } {
  const t = (s: string) => s.trim();
  if (!t(latText) || !t(lonText)) return { error: "Enter both latitude and longitude." };
  const num = /^[-+]?\d+(\.\d+)?$/;
  if (!num.test(t(latText)) || !num.test(t(lonText))) return { error: OUT_OF_RANGE };
  const lat = Number(t(latText));
  const lon = Number(t(lonText));
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return { error: OUT_OF_RANGE };
  return { lat, lon };
}

export const METHOD_LABEL: Record<string, string> = {
  gps: "My location (GPS)", pin: "Map pin", coordinates: "Entered coordinates", milepost: "From milepost reference",
  milepost_pin: "Milepost entered; pin confirmed by worker",
};

// Operator-required railroad/track/milepost (same rules as backend routes_repair.loc_field_error).
export const LOC_FIELDS = [["railroad", "Railroad"], ["track", "Track"], ["milepost", "Milepost"]] as const;
export function locFieldError(k: string, v: string): string | null {
  const s = (v || "").trim();
  if (k === "railroad" && (s.length < 2 || s.length > 120)) return "Railroad must be 2 to 120 characters.";
  if (k === "track" && (s.length < 1 || s.length > 40)) return "Track must be 1 to 40 characters.";
  if (k === "milepost" && !/^(mp\s?)?\d{1,4}(\.\d{1,4})?$/i.test(s)) return "Milepost must be a number such as 17 or 17.25.";
  return null;
}
