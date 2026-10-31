// Step guide for an inspection: Capture -> Review -> Details (Finish for repairs), with arrows between the steps.
// A step shows as done only when its real condition is met on this phone:
//   Capture: at least one saved photo, video, recording or note.
//   Review:  everything is backed up, every photo/video check has a result, nothing is waiting for review and no review
//            question is open. If these can't be loaded (offline), Review is not shown as done.
//   Details: the inspection is submitted (repairs: Finish repair confirmed with nothing left open).
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api } from "./api";
import * as repo from "./local/repo";
import { subscribe } from "./sync";
import { useTheme } from "./theme";
import { Icon } from "./ui";

export type Step = "capture" | "review" | "details";
export type StepDone = Record<Step, boolean>;
const ORDER: Step[] = ["capture", "review", "details"];

export function stepDone(v: repo.LocalVisit | null, ev: repo.LocalEvidence[], obs: repo.LocalObs[], proc: Record<string, any> | null,
  openQuestions: number | null): StepDone {
  const capture = ev.length + obs.length > 0;
  const review = capture && !!proc && openQuestions === 0 && ev.every((e) => e.sync.state === "Verified") && obs.every((o) => o.sync.state === "Verified")
    && ev.every((e) => {
      const p = proc[e.uuid];
      if (p?.needs_review) return false;
      return e.kind === "photo" || e.kind === "video" ? !!p && (p.result_state === "complete" || p.result_state === "partial") : true;
    });
  const details = !!v && (v.repair
    ? v.repair.finish && v.repair_sync === "Verified" && !v.repair_finish_blockers?.length
    : v.status === "Submitted");
  return { capture, review, details };
}

// For screens outside the inspection screen (photo review, departure): reads the device copy, plus results when online.
export function useStepProgress(uid: string, visitId?: string | null) {
  const [s, setS] = useState<{ done: StepDone; repair: boolean; known: boolean }>({ done: { capture: false, review: false, details: false }, repair: false, known: false });
  const load = useCallback(async () => {
    if (!uid || !visitId) return;
    const v = await repo.getLocalVisit(uid, visitId);
    if (!v) return;
    const [ev, obs] = await Promise.all([repo.listEvidence(uid, visitId), repo.listObs(uid, visitId)]);
    let proc: Record<string, any> | null = null;
    let openQ: number | null = null;
    if (v.sync.state === "Verified") {
      try {
        const [p, q] = await Promise.all([api(`/visits/${visitId}/processing`), api(`/visits/${visitId}/review-questions`)]);
        proc = p.by_evidence;
        openQ = q.questions.length;
      } catch { /* offline: Review stays not done */ }
    }
    setS({ done: stepDone(v, ev, obs, proc, openQ), repair: !!v.repair, known: true });
  }, [uid, visitId]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => subscribe(load), [load]);
  useEffect(() => {
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);
  return s;
}

// Go to a step of this inspection: back to the inspection screen if it is open, otherwise open it.
export function goToStep(visitId: string, step: Step) {
  router.dismissTo(`/visit/${visitId}?step=${step}`);
}

export function stepLabel(step: Step, repair: boolean) {
  return step === "capture" ? "Capture" : step === "review" ? "Review" : repair ? "Finish" : "Details";
}

export function StepGuide({ current, done, repair = false, onGo, testID = "step-guide" }: {
  current: Step; done: StepDone; repair?: boolean; onGo: (s: Step) => void; testID?: string;
}) {
  const { colors } = useTheme();
  return (
    <View testID={testID} accessibilityRole="tablist" style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      {ORDER.map((k, i) => {
        const on = k === current;
        const ok = done[k];
        const fg = on ? colors.onSurfaceInverse : colors.onSurface;
        return (
          <View key={k} style={{ flex: 1, flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Pressable testID={`${testID}-${k}`} accessibilityRole="tab" accessibilityState={{ selected: on }}
              accessibilityLabel={`${stepLabel(k, repair)}${ok ? ", done" : ""}${on ? ", current step" : ""}`} onPress={() => onGo(k)}
              style={({ pressed }) => ({
                flex: 1, minHeight: 44, borderRadius: 8, borderWidth: 1, borderColor: on ? colors.surfaceInverse : colors.border,
                backgroundColor: on ? colors.surfaceInverse : colors.surface, flexDirection: "row", alignItems: "center", justifyContent: "center",
                gap: 4, paddingHorizontal: 6, opacity: pressed ? 0.8 : 1,
              })}>
              {ok ? <Icon testID={`${testID}-${k}-done`} name="check-circle" size={16} color={on ? colors.onSurfaceInverse : colors.success} /> : null}
              <Text numberOfLines={1} style={{ color: fg, fontSize: 14, fontWeight: on ? "700" : "500", flexShrink: 1 }}>{stepLabel(k, repair)}</Text>
            </Pressable>
            {i < ORDER.length - 1 ? <Icon testID={`${testID}-arrow-${i + 1}`} name="arrow-right" size={18} color={colors.muted} /> : null}
          </View>
        );
      })}
    </View>
  );
}

// Forward button at the bottom of a step: "Next: Review" with an arrow.
export function NextStep({ to, repair = false, onPress, testID }: { to: Step; repair?: boolean; onPress: () => void; testID?: string }) {
  const { colors } = useTheme();
  return (
    <Pressable testID={testID || `step-next-${to}`} accessibilityRole="button" onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 52, borderRadius: 8, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
        flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingHorizontal: 16, opacity: pressed ? 0.8 : 1,
      })}>
      <Text style={{ color: colors.onSurface, fontSize: 16, fontWeight: "600" }}>Next: {stepLabel(to, repair)}</Text>
      <Icon name="arrow-right" size={20} color={colors.onSurface} />
    </Pressable>
  );
}
