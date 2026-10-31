import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Check, Info, Pencil, RefreshCw, Save, X } from "lucide-react";
import { ApiError, api, errText } from "@/lib/api";
import { workTypeLabel } from "@/lib/settings";
import { Badge, Banner, Btn, Card, Field, H2, Loading, Mono, Msg, PageHead, fmt } from "@/components/rr/ui";
import RoleGate from "@/components/rr/settings/RoleGate";
import FieldTable from "@/components/rr/settings/FieldTable";
import FieldEditor, { fromRow, toRow } from "@/components/rr/settings/FieldEditor";

const backCls = "rr-focus inline-flex min-h-[44px] items-center gap-1 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-medium hover:bg-[#F3F4F4]";

function History({ id, list, sel }) {
  return (
    <Card testid="template-history" className="space-y-2">
      <H2>Editions</H2>
      <ol className="space-y-1">
        {list.map((v) => (
          <li key={v.version}>
            <Link to={`/office/settings/templates/${id}?version=${v.version}`} data-testid={`template-history-${v.version}`} aria-current={v.version === sel ? "page" : undefined}
              className={`rr-focus flex min-h-[44px] flex-wrap items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${v.version === sel ? "border-[#202428] bg-[#F3F4F4]" : "border-[#D9DEE2] hover:bg-[#F8F9F9]"}`}>
              <span className="font-medium">Edition {v.version}</span>
              {v.current ? <Badge label="Current" icon={Check} tone="success" /> : null}
              <span className="text-[13px] text-[#59636B]">{v.fields?.length ?? "-"} fields - {fmt(v.created_at)}</span>
            </Link>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Editor({ t, onSaved, onReload }) {
  const [name, setName] = useState(t.name);
  const [rows, setRows] = useState(() => t.fields.map(toRow));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [stale, setStale] = useState(false);
  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/templates/${t.template_id}/versions`, { body: { expected_version: t.version, name: name.trim() || null, fields: rows.map(fromRow), default_for: t.default_for } });
      onSaved(r);
    } catch (e) {
      setStale(e instanceof ApiError && e.status === 409);
      setErr(errText(e)); // edits kept
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card testid="template-editor" className="space-y-4">
      <H2>Edit checklist</H2>
      <Banner tone="info" icon={Info} testid="template-pinned-note" text="Inspections already under way keep the edition they started with. Sent agreements are not changed." />
      <Field id="tpl-name" testid="template-name-input" label="Template name" value={name} onChange={setName} />
      <FieldEditor rows={rows} onChange={setRows} />
      {err ? <Banner tone="error" testid="template-save-error" text={err}>{stale ? <Btn small kind="secondary" icon={RefreshCw} testid="template-reload-latest" onClick={onReload}>Load latest (discards your edits)</Btn> : null}</Banner> : null}
      <div className="flex flex-wrap gap-2 border-t border-[#D9DEE2] pt-4">
        <Btn icon={Save} testid="template-save-button" loading={busy} onClick={save}>Save as a new edition</Btn>
        <Btn kind="secondary" icon={X} testid="template-cancel-button" onClick={() => onSaved(null)}>Cancel</Btn>
      </div>
    </Card>
  );
}

function DetailInner() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const ver = sp.get("version");
  const [t, setT] = useState(null);
  const [hist, setHist] = useState([]);
  const [msg, setMsg] = useState(null);
  const [editing, setEditing] = useState(false);
  const load = useCallback(async () => {
    try {
      const d = await api(`/templates/${id}${ver ? `?version=${ver}` : ""}`);
      setT(d);
      const all = await Promise.all((d.versions || []).map((n) => (n === d.version ? d : api(`/templates/${id}?version=${n}`).catch(() => ({ version: n })))));
      setHist(all.sort((a, b) => b.version - a.version));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id, ver]);
  useEffect(() => { load(); }, [load]);

  if (!t) return msg ? <Banner testid="template-error" tone="error" text={msg.text} /> : <Loading text="Loading template..." />;
  const saved = (r) => {
    setEditing(false);
    if (!r) return;
    setMsg({ tone: "success", text: "Saved. Inspections already under way keep the edition they started with." });
    if (ver) setSp({}, { replace: true });
    else load();
  };
  return (
    <div data-testid="template-detail-page" className="space-y-5">
      <PageHead kicker={`Settings - ${workTypeLabel(t.work_type)}`} title={t.name} subtitle={`Edition ${t.version}${t.current ? ", the latest" : ", an earlier edition, read only"} - saved ${fmt(t.created_at)}`}
        right={<>
          <Link to="/office/settings/templates" data-testid="template-back-link" className={backCls}><ArrowLeft aria-hidden className="h-4 w-4" />All templates</Link>
          {t.current && !editing ? <Btn small icon={Pencil} testid="template-edit-button" onClick={() => setEditing(true)}>Edit</Btn> : null}
          {!t.current ? <Link to={`/office/settings/templates/${id}`} data-testid="template-current-link" className={backCls}>Open the latest edition</Link> : null}
        </>} />
      <Msg msg={msg} testid="template-message" />
      <div className="grid gap-5 xl:grid-cols-12">
        <div className="min-w-0 space-y-5 xl:col-span-9">
          {editing ? <Editor key={t.version} t={t} onSaved={saved} onReload={() => { setEditing(false); setMsg(null); setSp({}, { replace: true }); load(); }} /> : (
            <section aria-labelledby="tf-h" className="space-y-2">
              <H2 id="tf-h">Fields ({t.fields.length})</H2>
              <FieldTable fields={t.fields} />
            </section>
          )}
        </div>
        <aside className="space-y-5 xl:col-span-3">
          <Card testid="template-defaults" className="space-y-1 text-sm">
            <H2>Default for</H2>
            <p>Work types: {(t.default_for?.work_types || []).map(workTypeLabel).join(", ") || "-"}</p>
            <p>Sites: {t.default_for?.site_ids?.length || "none"}</p>
            <Mono label="Version details">{t.template_id} - v{t.version} - {t.uuid} - by {t.created_by}</Mono>
          </Card>
          <History id={id} list={hist} sel={t.version} />
        </aside>
      </div>
    </div>
  );
}

export default function TemplateDetail() {
  return <RoleGate><DetailInner /></RoleGate>;
}
