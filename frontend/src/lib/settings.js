// Display labels for Phase 5 settings (REQ-206..216). All decisions (effective policy, missing items) come from the server.
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export const BLOCKED_MSG = "Analysis is turned off for this inspection. Contact your admin to check the setting.";

const BASIS = {
  organization_default: "Your company setting",
  site_restriction: "Turned off for this site",
  customer_restriction: "Turned off for this customer",
  visit_restriction: "Turned off for this inspection",
  evidence_exception: "Set for this one item",
  legacy_visit_denied: "Turned off for this inspection",
  legacy_visit_unknown: "Turned off for this inspection",
};
export const basisLabel = (b) => BASIS[b] || (b ? b.replace(/_/g, " ") : "-");

const PIN_BASIS = { default: "Default for this site / work type", changed_by_estimator: "Changed by an estimator", changed_by_admin: "Changed by an admin" };
export const pinBasisLabel = (b) => PIN_BASIS[b] || (b ? b.replace(/_/g, " ") : "-");

export const workTypeLabel = (w) => (w ? w.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "-");

export const NON_ANSWERS = [["unknown", "Unknown"], ["defer", "Defer"], ["not_applicable", "Not applicable"]];
export const nonAnswerLabel = (k) => (NON_ANSWERS.find(([v]) => v === k) || [k, k])[1];
export const TYPES = [["text", "Text"], ["number", "Number"], ["integer", "Whole number"], ["choice", "Choice"]];
export const APPLIES = [["inspection", "Inspection"], ["finding", "Each finding"]];
export const STAGES = [["capture", "Capture"], ["handoff", "Handoff"], ["pricing", "Pricing"]];
export const ROLES = [["foreman", "Foreman"], ["estimator", "Estimator"]];
export const SCOPES = [["site", "Site"], ["customer", "Customer"], ["visit", "Inspection"]];
export const scopeLabel = (s) => (SCOPES.find(([v]) => v === s) || [s, s])[1];
export const optLabel = (list, v) => (list.find(([k]) => k === v) || [v, v])[1];

/** Sites, customers (derived from sites) and inspections for policy pickers / name lookup. */
export function useLookups() {
  const [l, setL] = useState({ sites: [], customers: [], inspections: [], ready: false });
  useEffect(() => {
    Promise.all([
      api("/sites").catch(() => []),
      api("/inspections?status=all").then((r) => r?.inspections || []).catch(() => []),
    ]).then(([sites, inspections]) => {
      const cm = new Map();
      (sites || []).forEach((s) => s.customer_id && cm.set(s.customer_id, s.customer_name || s.customer_id));
      setL({ sites: sites || [], customers: [...cm].map(([id, name]) => ({ id, name })), inspections, ready: true });
    });
  }, []);
  const targets = useCallback((scope) => {
    if (scope === "site") return l.sites.map((s) => [s.uuid, s.name]);
    if (scope === "customer") return l.customers.map((c) => [c.id, c.name]);
    return l.inspections.map((i) => [i.visit_id, `${i.title} - ${i.site_name || ""}`]);
  }, [l]);
  const nameOf = useCallback((scope, id) => (targets(scope).find(([k]) => k === id) || [])[1], [targets]);
  return { ...l, targets, nameOf };
}
