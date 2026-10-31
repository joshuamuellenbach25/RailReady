import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { api, errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Banner, Btn, Card, Empty, fmt, H, Loading, Screen, Sheet, T } from "@/src/ui";
import { useSignOut } from "./home";

function VisitCard({ v }: { v: any }) {
  const miss = v.readiness_counts["Missing required"], rev = v.readiness_counts["Needs review"];
  return (
    <Card testID={`inbox-visit-${v.uuid}`} onPress={() => router.push(`/review/${v.uuid}`)}>
      <T bold size={16}>{v.title}</T>
      <T muted size={13}>{v.site_name} - {v.foreman_name} - {fmt(v.submitted_at || v.updated_at)}</T>
      <T size={13}>
        {[v.status, `${v.evidence_count} items`, v.pending_candidates ? `${v.pending_candidates} candidates to review` : null,
          miss ? `${miss} missing` : null, rev ? `${rev} need review` : null].filter(Boolean).join(" - ")}
      </T>
    </Card>
  );
}

export default function Office() {
  const { user, workspace } = useAuth();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [wos, setWos] = useState<any[]>([]);
  const [menu, setMenu] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const so = useSignOut();
  const load = useCallback(async () => {
    try {
      setData(await api("/office/inbox"));
      setWos(await api("/work-orders"));
      setErr(null);
    } catch (e) {
      setErr(errText(e));
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <Screen testID="office-screen" back={false} title="Office inbox" subtitle={`${user ? user.name : ""} - ${workspace?.name || ""}`}
      right={<Btn small kind="header" title="Account" icon="account-circle-outline" testID="account-menu-button" onPress={() => setMenu(true)} />}
      refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}>
      {err ? <Banner testID="office-error" tone="error" icon="wifi-off" text={err} /> : null}
      {!data && !err ? <Loading /> : null}
      {data ? (
        <>
          <H>Submitted inspections ({data.submitted.length})</H>
          {data.submitted.length ? data.submitted.map((v: any) => <VisitCard key={v.uuid} v={v} />) : <Empty testID="office-empty-submitted" icon="inbox-outline" text="No submitted inspections." />}
          <H>In progress - not submitted ({data.draft_transfers.length})</H>
          <T muted size={13}>Evidence received while the foreman is still capturing. May change.</T>
          {data.draft_transfers.length ? data.draft_transfers.map((v: any) => <VisitCard key={v.uuid} v={v} />) : <Empty icon="progress-clock" text="Nothing in progress." />}
        </>
      ) : null}
      {wos.length ? <H>Work orders ({wos.length})</H> : null}
      {wos.map((w) => (
        <Card key={w.uuid} testID={`office-wo-${w.uuid}`} onPress={() => router.push(`/workorder/${w.uuid}`)}>
          <T bold>{w.number}</T>
          <T muted size={13}>Access {w.access_status} - {w.scheduled_date || "No date"}</T>
        </Card>
      ))}
      <Sheet visible={menu} onClose={() => setMenu(false)} title="Account" testID="account-menu-sheet">
        <Btn testID="office-refresh-button" kind="secondary" title="Refresh" icon="refresh" onPress={() => { setMenu(false); load(); }} />
        <Btn testID="signout-button" kind="danger" title="Sign out" icon="logout" onPress={() => { setMenu(false); so.start(); }} />
      </Sheet>
      {so.sheet}
    </Screen>
  );
}
