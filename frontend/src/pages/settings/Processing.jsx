import { useCallback, useEffect, useState } from "react";
import { Check, ChevronRight, Lock, Pencil, RefreshCw } from "lucide-react";
import { ApiError, api, errText } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLookups } from "@/lib/settings";
import { Badge, Banner, Btn, Card, H2, Loading, Msg, PageHead } from "@/components/rr/ui";
import RoleGate from "@/components/rr/settings/RoleGate";
import PolicyRules, { DefaultBadge } from "@/components/rr/settings/PolicyRules";
import PolicyEditor from "@/components/rr/settings/PolicyEditor";

function History({ versions, nameOf }) {
  return (
    <Card testid="policy-history" className="space-y-3">
      <H2>Change history ({versions.length})</H2>
      <ol className="divide-y divide-[#D9DEE2]">
        {versions.map((p) => (
          <li key={p.uuid} data-testid={`policy-version-${p.version}`}>
            <details className="group/ver py-2">
              <summary className="rr-focus flex min-h-[44px] cursor-pointer list-none flex-wrap items-center gap-2 rounded [&::-webkit-details-marker]:hidden">
                <ChevronRight aria-hidden className="h-4 w-4 shrink-0 transition-transform group-open/ver:rotate-90" />
                <span className="font-medium">Change {p.version}</span>
                {p.current ? <Badge label="Current" icon={Check} tone="success" /> : null}
                <DefaultBadge p={p} />
                <span className="text-[13px] text-[#59636B]">{p.restrictions.length} turned off - {p.evidence_exceptions.length} set by hand</span>
              </summary>
              <div className="pb-2 pl-1 pt-2"><PolicyRules p={p} nameOf={nameOf} prefix={`v${p.version}`} /></div>
            </details>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function ProcessingInner() {
  const { isAdmin } = useAuth();
  const { targets, nameOf } = useLookups();
  const [p, setP] = useState(null);
  const [versions, setVersions] = useState([]);
  const [msg, setMsg] = useState(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const load = useCallback(async () => {
    try {
      const [cur, vs] = await Promise.all([api("/policy"), api("/policy/versions")]);
      setP(cur);
      setVersions(vs.versions || []);
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save(body) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api("/policy", { method: "PUT", body });
      setMsg({ tone: "success", text: "Saved." });
      setEditing(false);
      setStale(false);
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setStale(true);
      setMsg({ tone: "error", text: errText(e) }); // edits kept in the form
    } finally {
      setBusy(false);
    }
  }
  async function reloadLatest() {
    setEditing(false);
    setStale(false);
    setMsg(null);
    await load();
  }

  if (!p) return msg ? <Banner testid="policy-error" tone="error" text={msg.text} /> : <Loading text="Loading..." />;
  return (
    <div data-testid="processing-page" className="space-y-5">
      <PageHead kicker="Settings" title="Photo analysis" subtitle="Choose where RailReady looks through photos, notes and voice notes for possible issues. Applies to every inspection in this organization."
        right={<>
          <Btn small kind="secondary" icon={RefreshCw} testid="policy-refresh-button" onClick={load}>Refresh</Btn>
          {isAdmin && !editing ? <Btn small icon={Pencil} testid="policy-edit-button" onClick={() => setEditing(true)}>Change setting</Btn> : null}
        </>} />
      <Msg msg={msg} testid="policy-message" />
      {stale ? <Banner tone="warning" testid="policy-stale" text="Someone else changed this setting while you were editing. Your changes are still in the form."><Btn small kind="secondary" icon={RefreshCw} testid="policy-reload-latest" onClick={reloadLatest}>Load latest (discards your edits)</Btn></Banner> : null}
      {!isAdmin ? <Banner testid="policy-admin-only" icon={Lock} tone="info" text="Only admins can change this setting." /> : null}
      <div className="grid gap-5 lg:grid-cols-12">
        <div className="space-y-5 lg:col-span-7">
          <Card testid="policy-current" className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <H2>Current setting</H2>
              <DefaultBadge p={p} testid="policy-default" />
            </div>
            <PolicyRules p={p} nameOf={nameOf} prefix="current" />
          </Card>
          {editing ? <PolicyEditor key={p.version} policy={p} targets={targets} busy={busy} onSave={save} onCancel={() => { setEditing(false); setStale(false); }} /> : null}
        </div>
        <div className="lg:col-span-5"><History versions={versions} nameOf={nameOf} /></div>
      </div>
    </div>
  );
}

export default function Processing() {
  return <RoleGate><ProcessingInner /></RoleGate>;
}
