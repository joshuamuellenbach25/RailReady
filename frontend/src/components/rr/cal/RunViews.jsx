import { useCallback, useEffect, useRef, useState } from "react";
import { api, errText } from "@/lib/api";
import { DOMAIN_LABEL, num } from "@/lib/calibration";
import { Badge, Banner, H2, Mono } from "../ui";
import { MetricTable, Reliability, Semantics, SfUnknown } from "./Metrics";

/** Locked-val evaluation (REQ-254/256): supplied-box classification, every rate with its denominator. */
export function EvaluationView({ ev }) {
  const classes = Object.keys(ev.per_class || {});
  const [sel, setSel] = useState(classes[0] || "overall");
  const bins = sel === "overall" ? ev.overall?.reliability_bins : ev.per_class?.[sel]?.reliability_bins;
  const rows = [...(ev.overall ? [["overall", ev.overall]] : []), ...classes.map((k) => [k, ev.per_class[k]])];
  return (
    <section data-testid="cal-evaluation" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><H2>Evaluation</H2><Badge testid="cal-eval-label" label={ev.label} tone="neutral" />{ev.not ? <span className="text-[13px] text-[#59636B]">not {ev.not}</span> : null}</div>
      <Banner tone="warning" testid="cal-eval-domain" text={ev.domain_label || DOMAIN_LABEL} />
      <Semantics semantics={ev.score_semantics} testid="cal-eval-semantics" />
      <p className="text-sm">Test set: {ev.test_set}</p>
      <p className="text-sm">Threshold rule: {ev.threshold_rule}</p>
      {ev.excluded ? <p className="text-[13px] text-[#59636B]">{ev.excluded}</p> : null}
      {rows.length ? <MetricTable rows={rows} testid="cal-eval-table" /> : <p className="text-sm text-[#59636B]">No class had a fitted calibration. Nothing to score.</p>}
      {Object.keys(ev.classes_without_calibration || {}).length ? (
        <div data-testid="cal-eval-uncalibrated" className="text-sm"><p className="font-medium">Classes without calibration (abstained, no probability)</p>
          <ul className="mt-1 space-y-0.5">{Object.entries(ev.classes_without_calibration).map(([k, v]) => <li key={k}><span className="font-medium">{k}</span>: <span className="text-[#59636B]">{v}</span></li>)}</ul></div>
      ) : null}
      {rows.length ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Reliability class">
            <span className="text-sm font-medium">Reliability</span>
            {rows.map(([k]) => <button key={k} role="tab" aria-selected={sel === k} data-testid={`cal-rel-tab-${k}`} onClick={() => setSel(k)} className={`rr-focus min-h-[36px] rounded-md border px-2 text-sm ${sel === k ? "border-[#202428] bg-[#F3F4F4]" : "border-[#D9DEE2]"}`}>{k}</button>)}
          </div>
          {bins ? <Reliability bins={bins} testid="cal-eval-reliability" /> : null}
        </div>
      ) : null}
      <SfUnknown sf={ev.sf_validation} testid="cal-eval-sf" />
      <Mono label="Evaluation details">profile {ev.profile_id} v{ev.profile_version} - model run {ev.model_run_id} - checkpoint sha256 {ev.checkpoint_sha256}</Mono>
    </section>
  );
}

/** Hosted baseline summary: qualitative candidates, no calibrated probability. */
export function BaselineView({ b, items }) {
  return (
    <section data-testid="cal-baseline" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><H2>Baseline</H2><Badge label={b.label} tone="neutral" /></div>
      <p className="text-sm">Items: {num(b.items)} - {Object.entries(b.status_counts || {}).map(([k, v]) => `${k} ${v}`).join(" - ")}</p>
      <p data-testid="cal-baseline-calibrated" className="text-sm">Calibrated probability: <b className="font-medium">none</b> - {b.calibrated_probability_reason}</p>
      {Object.entries(b.per_category || {}).map(([k, m]) => (m ? (
        <div key={k} className="space-y-1"><p className="text-sm font-medium">{k} <span className="font-normal text-[#59636B]">model category "{m.model_category}"</span></p><MetricTable rows={[[k, m]]} testid={`cal-baseline-${k}`} /></div>
      ) : <p key={k} className="text-sm text-[#59636B]">{k}: no scored items.</p>))}
      {b.budget_after ? <p className="text-[13px] text-[#59636B]">Budget after run: {num(b.budget_after.used)} of {num(b.budget_after.cap)} used</p> : null}
      {items?.length ? (
        <details data-testid="cal-baseline-items" className="text-sm">
          <summary className="rr-focus inline-flex min-h-[32px] cursor-pointer items-center rounded font-medium">Per-item raw responses ({items.length})</summary>
          <ul className="mt-2 space-y-2">
            {items.map((it) => (
              <li key={it.image_key} className="rounded border border-[#D9DEE2] p-2">
                <p className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs">{it.image_key?.split(":").slice(1).join("/")}</span><Badge label={it.status || "Unknown"} />{it.error ? <span className="text-[13px] text-[#8F1D1B]">{it.error}</span> : null}</p>
                <Mono label="Raw response">{typeof it.raw_response === "string" ? it.raw_response : JSON.stringify(it.raw_response ?? it.parsed ?? null)}</Mono>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

export function useRun(id) {
  const [r, setR] = useState(null);
  const [err, setErr] = useState(null);
  const cur = useRef(id);
  cur.current = id;
  const load = useCallback(() => api(`/calibration/runs/${id}?include_items=1`)
    .then((x) => { if (cur.current !== id) return null; setR(x); return `${x.status}-${x.logs?.length}`; })
    .catch((e) => cur.current === id && setErr(errText(e))), [id]);
  useEffect(() => { setR(null); setErr(null); load(); }, [load]);
  return [r, err, load];
}
