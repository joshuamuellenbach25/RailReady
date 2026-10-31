import { CheckCircle2, XCircle } from "lucide-react";
import { DOMAIN_LABEL, dec, num, pct } from "@/lib/calibration";
import { Badge } from "../ui";

export function Mark({ ok, testid, yes = "Matches", no = "Differs" }) {
  const I = ok ? CheckCircle2 : XCircle;
  return <span data-testid={testid} className={`inline-flex items-center gap-1 text-[13px] font-medium ${ok ? "text-[#1E5B32]" : "text-[#8F1D1B]"}`}><I aria-hidden className="h-3.5 w-3.5" />{ok ? yes : no}</span>;
}

/** Score semantics + domain label - shown next to every probability (REQ-251/255). */
export function Semantics({ semantics = "source_bad_condition_probability", testid }) {
  return (
    <p data-testid={testid} className="text-[13px] text-[#59636B]">
      Score: <span className="font-mono text-[12px] text-[#202428]">{semantics}</span> - {DOMAIN_LABEL}
    </p>
  );
}

export const ratio = (r, part) => (r ? `${pct(r.value)} (${num(part)} of ${num(r.denominator)})` : "-");

const TH = "px-2 py-1.5 text-left font-medium";
const TD = "px-2 py-1.5 font-mono text-[13px]";

/** Metrics table: one row per class (or "overall"), every rate with its denominator. */
export function MetricTable({ rows, testid }) {
  return (
    <div className="overflow-x-auto rounded-md border border-[#D9DEE2]">
      <table data-testid={testid} className="w-full min-w-[980px] bg-white text-sm">
        <thead className="bg-[#F3F4F4] text-[13px] text-[#3C444B]">
          <tr>{["Class", "n (Bad / Good)", "TP", "FP", "FN", "TN", "Precision", "Recall", "False alerts", "Misses", "Brier", "ECE", "Abstained", "Assessable coverage"].map((h) => <th key={h} scope="col" className={TH}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map(([name, m]) => (
            <tr key={name} data-testid={`${testid}-${name}`} className="border-t border-[#D9DEE2]">
              <th scope="row" className="px-2 py-1.5 text-left font-medium">{name}</th>
              <td className={TD}>{num(m.n)} ({num(m.n_bad)} / {num(m.n_good)})</td>
              <td className={TD}>{num(m.confusion?.tp)}</td><td className={TD}>{num(m.confusion?.fp)}</td>
              <td className={TD}>{num(m.confusion?.fn)}</td><td className={TD}>{num(m.confusion?.tn)}</td>
              <td className={TD}>{ratio(m.precision, m.confusion?.tp)}</td>
              <td className={TD}>{ratio(m.recall, m.confusion?.tp)}</td>
              <td className={TD}>{num(m.false_alerts)}</td><td className={TD}>{num(m.misses)}</td>
              <td className={TD}>{dec(m.brier, 4)}</td><td className={TD}>{dec(m.ece, 4)}</td>
              <td className={TD}>{num(m.abstained)}</td><td className={TD}>{m.assessable_coverage == null ? "-" : pct(m.assessable_coverage)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Reliability bins: table + bars (observed Bad rate vs mean predicted), with bin counts. */
export function Reliability({ bins, testid }) {
  return (
    <div data-testid={testid} className="space-y-2">
      <div className="flex items-end gap-1 rounded-md border border-[#D9DEE2] bg-white p-3" role="img" aria-label="Reliability chart: observed Bad rate per predicted-probability bin">
        {bins.map((b, i) => (
          <div key={i} className="flex min-w-0 flex-1 flex-col items-center gap-1">
            <div className="relative flex h-28 w-full items-end justify-center gap-0.5">
              <div title="mean predicted" className="w-1/3 bg-[#C5CCD2]" style={{ height: `${(b.mean_predicted ?? 0) * 100}%` }} />
              <div title="observed Bad rate" className="w-1/3 bg-[#22272B]" style={{ height: `${(b.observed_bad_rate ?? 0) * 100}%` }} />
            </div>
            <span className="font-mono text-[11px] text-[#59636B]">{b.bin?.[0]?.toFixed(1)}</span>
            <span className="font-mono text-[11px]">n={b.n}</span>
          </div>
        ))}
      </div>
      <p className="flex flex-wrap gap-3 text-[12px] text-[#59636B]"><span><span className="mr-1 inline-block h-2.5 w-2.5 bg-[#C5CCD2] align-middle" />mean predicted probability</span><span><span className="mr-1 inline-block h-2.5 w-2.5 bg-[#22272B] align-middle" />observed Bad rate</span></p>
      <details className="text-sm">
        <summary className="rr-focus inline-flex min-h-[32px] cursor-pointer items-center rounded font-medium text-[#3C444B]">Bin table</summary>
        <table className="mt-1 w-full max-w-md text-[13px]">
          <thead><tr className="text-left text-[#3C444B]"><th className="py-1">Bin</th><th>n</th><th>Mean predicted</th><th>Observed Bad rate</th></tr></thead>
          <tbody>{bins.map((b, i) => <tr key={i} className="border-t border-[#D9DEE2] font-mono"><td className="py-1">{b.bin?.map((x) => x.toFixed(1)).join("-")}</td><td>{b.n}</td><td>{dec(b.mean_predicted)}</td><td>{dec(b.observed_bad_rate)}</td></tr>)}</tbody>
        </table>
      </details>
    </div>
  );
}

export function SfUnknown({ sf, testid }) {
  if (!sf) return null;
  return <p data-testid={testid} className="flex flex-wrap items-center gap-2 text-sm"><Badge label={sf.status} prefix="SF validation" /> <span className="text-[#59636B]">{sf.reason}</span></p>;
}
