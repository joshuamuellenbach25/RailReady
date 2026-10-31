import { useCallback, useEffect, useRef, useState } from "react";
import { errText, isAbort } from "./api";
import { loadReview } from "./photoReview";

const TERMINAL = ["complete", "partial", "failed", "unavailable", "needs_review"];
const FAST = 4000;
const SLOW = 15000;

/**
 * Reads /evidence/{id}/analysis (+ visual candidates) and polls per the Phase 12 contract: every 4 s while
 * `checking` (or `null` within 2 min of verify), stops on a terminal state, 15 s after 3 failed polls, and aborts the
 * in-flight request when the evidence changes or the view unmounts. Decisions are never cached: every read is fresh.
 */
export default function useReview(ev, { forcePoll = false } = {}) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const ac = useRef(null);

  const load = useCallback(async () => {
    ac.current?.abort();
    const mine = new AbortController();
    ac.current = mine;
    try {
      const r = await loadReview(ev.uuid, mine.signal);
      if (mine.signal.aborted) return true;
      setD(r);
      setErr(null);
      return true;
    } catch (e) {
      if (isAbort(e)) return true;
      setErr(errText(e));
      return false;
    }
  }, [ev.uuid]);

  useEffect(() => {
    setD(null);
    setErr(null);
    load();
    return () => ac.current?.abort();
  }, [load]);

  const verifiedAt = Date.parse(ev.verified_at || ev.updated_at || "") || 0;
  const recent = Date.now() - verifiedAt < 120000;
  const poll = forcePoll || d?.state === "checking" || (!!d && d.state == null && recent && !TERMINAL.includes(d.state));
  useEffect(() => {
    if (!poll) return undefined;
    let fails = 0;
    let t;
    let stop = false;
    const tick = async () => {
      const ok = await load();
      if (stop) return;
      fails = ok ? 0 : fails + 1;
      t = setTimeout(tick, fails >= 3 ? SLOW : FAST);
    };
    t = setTimeout(tick, FAST);
    return () => { stop = true; clearTimeout(t); ac.current?.abort(); };
  }, [poll, load]);

  return { d, err, load, polling: poll };
}
