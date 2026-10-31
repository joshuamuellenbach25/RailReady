import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertOctagon, Box, ImageIcon, Mic, Pencil, Plus, RefreshCw, Save, ShieldAlert } from "lucide-react";
import { ApiError, api, errText, mediaUrl, newId } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Banner, Btn, Card, Field, H2, Modal, Mono, Msg, fmt } from "./ui";
import PhotoReview from "./PhotoReview";
import VideoReview from "./VideoReview";

const TERMINAL = ["Done", "Failed"];
const OUTCOME = {
  "No candidate identified in this image": "Nothing spotted in this photo. That does not mean the track is clear. Trust what you saw on site.",
  "Cannot assess - request closer photo": "Hard to tell from this photo. Ask for a closer one.",
};

/** Safety flags on notes / voice notes. Only shown when there is something to act on. */
function Flags({ evidenceId }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    const f = () => api(`/evidence/${evidenceId}/text-checks`).then(setD).catch(() => {});
    f();
    const t = setInterval(f, 8000);
    return () => clearInterval(t);
  }, [evidenceId]);
  const done = (d?.checks || []).filter((c) => c.status === "Done" && c.check?.result);
  const urgent = done.some((c) => c.check.result.urgent);
  const instr = done.some((c) => c.check.result.contains_instructions);
  if (!urgent && !instr) return null;
  return (
    <div className="space-y-2">
      {urgent ? (
        <Banner testid="text-check-urgent-0" tone="error" icon={AlertOctagon} text="Possible urgent concern. Check your escalation procedure.">
          <p>{d.escalation_text}</p>
          <p className="font-semibold">Saving does not notify anyone.</p>
        </Banner>
      ) : null}
      {instr ? <Banner testid="text-check-instructions-0" tone="warning" icon={ShieldAlert} text="This note contains instructions. Read it with care before acting on it." /> : null}
      <Mono label="Technical details">{done.map((c) => `${c.check.model_id} urgent=${c.check.result.urgent_p} instructions=${c.check.result.instructions_p}`).join(" | ")}</Mono>
    </div>
  );
}

/** Voice note: the clip plus what was said. Staff can fix the words; earlier wording is kept on file. */
function VoiceText({ list, locked, onSave }) {
  const [edit, setEdit] = useState(null);
  const [err, setErr] = useState(null);
  const latest = list[list.length - 1];
  return (
    <Card testid="transcript-card" className="space-y-3">
      <H2 className="flex items-center gap-2"><Mic aria-hidden className="h-4 w-4" />What was said</H2>
      <p data-testid="transcript-text" data-raw="1" className="whitespace-pre-wrap text-[16px] leading-relaxed">{latest.text}</p>
      {latest.kind !== "machine" ? <p className="text-[13px] text-[#59636B]">Edited {fmt(latest.created_at)}</p> : null}
      {!locked ? <Btn small kind="secondary" icon={Pencil} testid="transcript-correct-button" onClick={() => setEdit(latest.text)}>Edit text</Btn> : null}
      <Mono label="Technical details">{list.map((t) => `v${t.version} ${t.kind}${t.model_id ? ` ${t.model_id}` : ""}`).join(" | ")}</Mono>
      <Modal open={edit !== null} onClose={() => setEdit(null)} title="Edit what was said" description="Fix any words that came out wrong. The recording stays as it is." testid="transcript-edit-sheet">
        <Field id="t-edit" testid="transcript-edit-input" label="Text" multiline value={edit || ""} onChange={setEdit} />
        {err ? <Banner tone="error" text={err} testid="transcript-edit-error" /> : null}
        <Btn testid="transcript-save-button" icon={Save} onClick={async () => { const e = await onSave(edit); setErr(e); if (!e) setEdit(null); }}>Save</Btn>
      </Modal>
    </Card>
  );
}

export default function EvidenceDetail({ ev, visitId, locked, onChanged }) {
  const { isForeman, isAdmin } = useAuth();
  const [an, setAn] = useState(null);
  const [transcripts, setTranscripts] = useState([]);
  const [msg, setMsg] = useState(null);
  const [active, setActive] = useState(null);
  const [manual, setManual] = useState(null);
  const verified = ev.upload_state === "Verified";
  const jobs = Object.values(ev.jobs || {});
  const busyJobs = jobs.some((j) => !TERMINAL.includes(j.status));
  const failed = jobs.find((j) => j.status === "Failed");

  const load = useCallback(async () => {
    if (!verified) return;
    try {
      if (ev.kind === "audio") setTranscripts(await api(`/evidence/${ev.uuid}/transcripts`));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [ev.uuid, ev.kind, verified]);
  useEffect(() => { setAn(null); setTranscripts([]); setMsg(null); }, [ev.uuid]);
  useEffect(() => { load(); }, [load, ev.jobs]);
  useEffect(() => {
    if (!busyJobs) return undefined;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [busyJobs, load]);

  const THANKS = { confirm: "Marked as confirmed.", correct: "Correction saved.", dismiss: "Marked as not an issue.", request_closer_photo: "Saved. The foreman will be asked for a closer photo." };
  async function decide(c, action, extra = {}) {
    setMsg(null);
    try {
      await api(`/candidates/${c.uuid}/decision`, { body: { action, expected_revision: c.revision, ...extra } });
      setMsg({ tone: "success", text: THANKS[action] });
      await load();
      onChanged();
      return true;
    } catch (e) {
      setMsg({ tone: "warning", text: e instanceof ApiError && e.status === 409 ? "Someone answered this a moment ago. Showing the latest answer." : errText(e) });
      load();
      return false;
    }
  }
  async function retry() {
    try {
      await api(`/jobs/${failed.uuid}/retry`, { method: "POST" });
      setMsg({ tone: "info", text: "Trying again. This can take a minute." });
      onChanged();
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }
  async function saveTranscript(text) {
    try {
      await api(`/evidence/${ev.uuid}/transcripts`, { body: { text, base_version: transcripts[transcripts.length - 1].version } });
      setMsg({ tone: "success", text: "Saved." });
      load();
      return null;
    } catch (e) {
      return errText(e);
    }
  }
  async function addManual() {
    try {
      await api(`/visits/${visitId}/observations`, { body: { uuid: newId(), kind: "finding", text: manual.trim() } });
      setManual(null);
      setMsg({ tone: "success", text: "Added to this inspection." });
      onChanged();
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) }); // text kept in the dialog
    }
  }

  const cands = an?.candidates || [];
  const lastRun = an?.runs?.[an.runs.length - 1];
  const errBanner = msg && msg.tone !== "success" ? <Banner tone={msg.tone} text={msg.text} testid="evidence-modal-error" /> : null;
  const outcome = lastRun?.status === "Done" ? (cands.length ? `${cands.length} thing${cands.length > 1 ? "s" : ""} worth a look in this photo.` : OUTCOME[an.outcome_label] || an.outcome_label) : null;
  return (
    <div data-testid="evidence-detail" className="space-y-5">
      <Msg msg={msg} testid="evidence-message" />
      {!verified ? <Banner tone="info" testid="evidence-arriving" text="This item is still on its way from the phone. It will appear here shortly." /> : null}
      {ev.kind === "photo" && verified ? <PhotoReview ev={ev} locked={locked} onChanged={onChanged} /> : null}
      {ev.kind === "video" && verified ? <VideoReview ev={ev} locked={locked} onChanged={onChanged} /> : null}
      {ev.kind === "photo" && verified ? (
        <div className="flex flex-wrap gap-2">
          <Link to={`/office/visits/${visitId}/scene?evidence=${ev.uuid}&mode=3d`} data-testid="evidence-3d-view-link"
            className="rr-focus inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-[#D2D8DD] bg-white px-3 text-sm font-medium text-[#202428] transition-colors hover:bg-[#F3F4F4]"><Box aria-hidden className="h-4 w-4" />3D view</Link>
          <a href={mediaUrl(ev.uuid)} target="_blank" rel="noopener noreferrer" data-testid="evidence-original-link"
            className="rr-focus inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-[#D2D8DD] bg-white px-3 text-sm font-medium text-[#202428] transition-colors hover:bg-[#F3F4F4]"><ImageIcon aria-hidden className="h-4 w-4" />Full-size photo</a>
        </div>
      ) : null}
      {ev.kind === "audio" && verified ? <audio data-testid="audio-player" controls preload="metadata" src={mediaUrl(ev.uuid)} className="w-full" /> : null}
      {ev.kind === "note" ? <Card><p data-testid="evidence-note-text" data-raw="1" className="whitespace-pre-wrap text-[16px] leading-relaxed">{ev.text}</p></Card> : null}
      {ev.kind === "audio" && transcripts.length ? <VoiceText list={transcripts} locked={locked} onSave={saveTranscript} /> : null}
      {failed && !isForeman && ev.kind !== "photo" ? (
        <Banner tone="warning" testid="evidence-retry-banner" text={`We couldn't read this ${ev.kind === "audio" ? "voice note" : ev.kind} automatically. You can still review it yourself.`}>
          <Btn small kind="secondary" icon={RefreshCw} testid="evidence-retry-button" onClick={retry}>Try again</Btn>
        </Banner>
      ) : null}
      {ev.kind !== "photo" && verified ? <Flags evidenceId={ev.uuid} /> : null}
      {ev.kind === "photo" && !locked ? <Btn kind="secondary" icon={Plus} testid="evidence-add-observation-button" onClick={() => setManual("")}>Add something you noticed</Btn> : null}
      {isAdmin ? (
        <Mono label="Technical details" className="block">
          {ev.uuid} | {ev.upload_state} | receipt {ev.receipt_id || "-"} | sha256 {ev.sha256} | {ev.size} B | jobs {jobs.map((j) => `${j.stage || ""}:${j.status}`).join(", ")}
        </Mono>
      ) : null}
      <Modal open={manual !== null} onClose={() => setManual(null)} title="Add something you noticed" testid="manual-observation-sheet">
        <Field id="manual-obs" testid="manual-observation-input" label="What did you notice?" multiline value={manual || ""} onChange={setManual} />
        {errBanner}
        <Btn testid="manual-observation-save" icon={Save} disabled={!manual?.trim()} onClick={addManual}>Save</Btn>
      </Modal>
    </div>
  );
}
