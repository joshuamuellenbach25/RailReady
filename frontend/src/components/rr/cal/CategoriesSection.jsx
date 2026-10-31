import { num } from "@/lib/calibration";
import { Banner, Card, H2 } from "../ui";
import { Mark } from "./Metrics";

const gb = (o) => (o ? `${num(o.Good ?? 0)} / ${num(o.Bad ?? 0)}` : "-");

export default function CategoriesSection({ r }) {
  const s = r?.stats;
  if (!s?.categories?.length) return <Card testid="cal-categories"><H2>Categories</H2><p className="mt-1 text-sm text-[#59636B]">Category statistics appear once annotations are indexed.</p></Card>;
  return (
    <Card testid="cal-categories" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><H2>Categories and conditions</H2><Mark ok={!!s.matches_contract} yes="All match the source contract" no="Some differ from the contract" testid="cal-stats-match" /></div>
      <p className="text-[13px] text-[#59636B]">Good / Bad are the dataset's source labels, not RailReady findings.</p>
      <div className="overflow-x-auto rounded-md border border-[#D9DEE2]">
        <table data-testid="cal-categories-table" className="w-full min-w-[860px] bg-white text-sm">
          <thead className="bg-[#F3F4F4] text-left text-[13px] text-[#3C444B]">
            <tr>{["Category", "Good", "Bad", "Train Good / Bad", "Val Good / Bad", "By type (Good / Bad)", "Contract", "Note"].map((h) => <th key={h} scope="col" className="px-2 py-1.5 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {s.categories.map((c) => (
              <tr key={c.category_id} data-testid={`cal-cat-${c.name}`} className="border-t border-[#D9DEE2] align-top">
                <th scope="row" className="px-2 py-2 text-left font-medium">{c.name}<span className="block font-mono text-[11px] font-normal text-[#59636B]">id {c.category_id}</span></th>
                <td className="px-2 py-2 font-mono">{num(c.Good)}</td>
                <td className="px-2 py-2 font-mono">{num(c.Bad)}</td>
                <td className="px-2 py-2 font-mono">{gb(c.by_split?.train)}</td>
                <td className="px-2 py-2 font-mono">{gb(c.by_split?.val)}</td>
                <td className="px-2 py-2">{Object.keys(c.by_type || {}).length ? Object.entries(c.by_type).map(([t, v]) => <span key={t} className="block">{t}: <span className="font-mono">{gb(v)}</span></span>) : "-"}</td>
                <td className="px-2 py-2"><Mark ok={!!c.matches_contract} testid={`cal-cat-match-${c.name}`} /></td>
                <td className="px-2 py-2 text-[13px]">
                  {c.note ? <span data-testid={`cal-cat-note-${c.name}`} className="font-medium text-[#7A4A00]">{c.note}</span> : null}
                  {c.excluded_from_physical_metrics ? <span data-testid={`cal-cat-excluded-${c.name}`} className="block text-[#59636B]">Whole-image label, excluded from component counts and metrics</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Banner tone="warning" testid="cal-rail-note" text={s.rail_note || "No Bad rail labels. Broken-rail sensitivity is not supported."} />
      <p data-testid="cal-virtual-baseplate-note" className="text-[13px] text-[#59636B]">
        {num(r.counts?.virtual_baseplates)} virtual baseplate annotations (plates implied but not visible) are included in the {num(r.counts?.physical_annotations_incl_virtual_baseplates)} component annotations and excluded from evaluation.
      </p>
    </Card>
  );
}
