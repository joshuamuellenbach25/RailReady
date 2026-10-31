import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { api, errText } from "@/lib/api";
import { workTypeLabel } from "@/lib/settings";
import { Banner, Loading, PageHead, fmt } from "@/components/rr/ui";
import RoleGate from "@/components/rr/settings/RoleGate";

function TemplatesInner() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api("/templates").then(setD).catch((e) => setErr(errText(e))); }, []);
  if (!d) return err ? <Banner testid="templates-error" tone="error" text={err} /> : <Loading text="Loading templates..." />;
  return (
    <div data-testid="templates-page" className="space-y-5">
      <PageHead kicker="Settings" title="Checklists" subtitle="The questions asked during an inspection. Saving changes creates a new edition. Inspections already under way keep the edition they started with." />
      <div className="overflow-x-auto rounded-lg border border-[#D9DEE2]">
        <table data-testid="templates-table" className="w-full min-w-[720px] bg-white text-sm">
          <thead className="border-b border-[#D9DEE2] bg-[#F3F4F4] text-left text-[13px] text-[#3C444B]">
            <tr>{["Checklist", "Work type", "Edition", "Questions", "Used by default for", "Last saved", ""].map((h) => <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {d.templates.map((t, i) => (
              <tr key={t.template_id} data-testid={`template-row-${t.template_id}`} className={`${i ? "border-t border-[#D9DEE2]" : ""} hover:bg-[#F8F9F9]`}>
                <td className="px-3 py-3 font-medium">{t.name}</td>
                <td className="px-3 py-3">{workTypeLabel(t.work_type)}</td>
                <td className="px-3 py-3" data-testid={`template-version-${t.template_id}`}>Edition {t.version}</td>
                <td className="px-3 py-3">{t.fields.length}</td>
                <td className="px-3 py-3 text-[#59636B]">{(t.default_for?.work_types || []).map(workTypeLabel).join(", ") || "-"}{t.default_for?.site_ids?.length ? ` - ${t.default_for.site_ids.length} site(s)` : ""}</td>
                <td className="px-3 py-3 text-[#59636B]">{fmt(t.created_at)}</td>
                <td className="px-3 py-3"><Link to={`/office/settings/templates/${t.template_id}`} data-testid={`template-open-${t.template_id}`} className="rr-focus inline-flex min-h-[44px] items-center gap-1 font-medium text-[#B32624] hover:underline">Open <ArrowRight aria-hidden className="h-3.5 w-3.5" /></Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Templates() {
  return <RoleGate><TemplatesInner /></RoleGate>;
}
