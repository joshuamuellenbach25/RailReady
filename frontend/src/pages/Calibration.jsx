import { useCallback, useEffect, useState } from "react";
import { Lock, RefreshCw } from "lucide-react";
import { api, errText } from "@/lib/api";
import { ACTIVE, DOMAIN_LABEL, usePoll } from "@/lib/calibration";
import { Banner, Btn, Loading, PageHead } from "@/components/rr/ui";
import DatasetSection from "@/components/rr/cal/DatasetSection";
import CategoriesSection from "@/components/rr/cal/CategoriesSection";
import ImageBrowser from "@/components/rr/cal/ImageBrowser";
import PartitionsSection from "@/components/rr/cal/PartitionsSection";
import RunsSection from "@/components/rr/cal/RunsSection";
import ProfilesSection from "@/components/rr/cal/ProfilesSection";

const SECTIONS = [["cal-dataset", "Dataset"], ["cal-categories", "Categories"], ["cal-images", "Images"], ["cal-partitions", "Partitions"], ["cal-runs", "Runs"], ["cal-profiles", "Profiles"]];

export default function Calibration() {
  const [releases, setReleases] = useState(null);
  const [rid, setRid] = useState(null);
  const [r, setR] = useState(null);
  const [runs, setRuns] = useState({ runs: [], budget: null });
  const [profiles, setProfiles] = useState(null);
  const [partitions, setPartitions] = useState([]);
  const [denied, setDenied] = useState(null);
  const [err, setErr] = useState(null);

  const loadAll = useCallback(async () => {
    try {
      const [d, rs, ps] = await Promise.all([api("/calibration/datasets"), api("/calibration/runs"), api("/calibration/profiles")]);
      setReleases(d.datasets || []);
      setRid((cur) => cur || d.datasets?.[0]?.uuid || null);
      setRuns(rs);
      setProfiles(ps);
      setErr(null);
    } catch (e) {
      if (e?.status === 403 || e?.status === 401) setDenied(errText(e));
      else setErr(errText(e));
    }
  }, []);
  const loadRelease = useCallback(() => (rid ? api(`/calibration/datasets/${rid}`).then((x) => { setR(x); return `${x.status}-${x.progress?.files_verified}-${x.progress?.downloaded_bytes}`; }) : Promise.resolve(null)), [rid]);
  const pollRuns = useCallback(() => api("/calibration/runs").then((x) => { setRuns(x); return x.runs.map((y) => y.status).join(); }), []);
  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => { loadRelease().catch((e) => setErr(errText(e))); }, [loadRelease]);
  usePoll(loadRelease, !!r && ACTIVE.includes(r.status));
  usePoll(pollRuns, runs.runs.some((x) => ACTIVE.includes(x.status)));

  if (denied) return <Banner testid="cal-forbidden" tone="warning" icon={Lock} text={`Calibration is staff-only (admins and estimators). Server: ${denied}`} />;
  if (!releases) return err ? <Banner testid="cal-error" tone="error" text={err} /> : <Loading text="Loading calibration..." />;
  return (
    <div data-testid="calibration-page" className="space-y-5">
      <PageHead kicker="Diagnostics" title="Calibration" subtitle="Source dataset, partitions, runs and calibration profiles for the photo-condition classifier. Staff only."
        right={<Btn small kind="secondary" icon={RefreshCw} testid="cal-refresh" onClick={() => { loadAll(); loadRelease(); }}>Refresh</Btn>} />
      <p data-testid="cal-domain-label" className="text-sm font-medium text-[#7A4A00]">{DOMAIN_LABEL}</p>
      <nav aria-label="Calibration sections" className="flex flex-wrap gap-1">
        {SECTIONS.map(([id, l]) => <a key={id} href={`#${id}`} data-testid={`cal-jump-${id}`} className="rr-focus inline-flex min-h-[36px] items-center rounded-md border border-[#D9DEE2] bg-white px-3 text-sm hover:bg-[#F3F4F4]">{l}</a>)}
      </nav>
      {err ? <Banner tone="error" testid="cal-error" text={err} /> : null}
      <div id="cal-dataset" className="scroll-mt-4"><DatasetSection releases={releases} r={r} onSelect={setRid} onImported={(x) => { setRid(x.release?.uuid || rid); loadAll(); loadRelease(); }} /></div>
      {r ? (
        <>
          <div id="cal-categories" className="scroll-mt-4"><CategoriesSection r={r} /></div>
          <div id="cal-images" className="scroll-mt-4"><ImageBrowser r={r} /></div>
          <div id="cal-partitions" className="scroll-mt-4"><PartitionsSection r={r} onPartitions={setPartitions} /></div>
        </>
      ) : null}
      <div id="cal-runs" className="scroll-mt-4"><RunsSection runs={runs.runs} budget={runs.budget} partitions={partitions} profiles={profiles?.profiles || []} onChanged={loadAll} /></div>
      <div id="cal-profiles" className="scroll-mt-4"><ProfilesSection data={profiles} runs={runs.runs} onChanged={loadAll} /></div>
    </div>
  );
}
