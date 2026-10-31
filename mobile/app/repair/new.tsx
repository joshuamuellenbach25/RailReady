// Phase 15 step 1: Open repair. Works offline: creates a local site + inspection carrying the repair details.
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, View } from "react-native";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { syncAll } from "@/src/sync";
import { Banner, Btn, Input, Screen, T } from "@/src/ui";
import { storage } from "@/src/utils/storage";

export default function NewRepair() {
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const [ops, setOps] = useState<{ uuid: string; name: string }[]>([]);
  const [f, setF] = useState({ operator_id: null as string | null, operator_name: "", po: "", railroad: "", track: "", milepost: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const cached = await storage.getItem<string | null>(`operators:${uid}`, null);
      if (cached) setOps(JSON.parse(cached));
      try {
        const o = await api("/operators");
        setOps(o);
        await storage.setItem(`operators:${uid}`, JSON.stringify(o));
      } catch { /* offline: cached list or free text */ }
    })();
  }, [uid]);

  async function open() {
    if (busy) return;
    if (!f.operator_name.trim()) return setErr("Enter the customer or operator.");
    setBusy(true);
    try {
      const name = [f.railroad.trim(), f.milepost.trim() ? `MP ${f.milepost.trim()}` : ""].filter(Boolean).join(" ") || f.operator_name.trim();
      const site = await repo.createSite(uid, { name, address: null, description: `Repair for ${f.operator_name.trim()}`, lat: null, lon: null, location_accuracy_m: null });
      const v = await repo.createVisit(uid, site.uuid, site.name, `Repair - ${name}`);
      const t = (s: string) => s.trim() || null;
      await repo.saveVisit(uid, { ...v, repair: { operator_id: f.operator_id, operator_name: t(f.operator_name), po: t(f.po), railroad: t(f.railroad), track: t(f.track),
        milepost: t(f.milepost), work: [], completion_date: null, finish: false, finished_at_client: null }, repair_sync: "Saved" });
      syncAll(uid).catch(() => {});
      router.replace(`/visit/${v.uuid}`);
    } catch (e: any) {
      setErr(e?.message || "Could not save on this phone.");
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof f) => (s: string) => setF({ ...f, [k]: s });
  return (
    <Screen title="Open repair" testID="repair-new-screen">
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12, paddingBottom: 24 }}>
        {err ? <Banner testID="repair-new-error" tone="error" icon="alert-circle-outline" text={err} /> : null}
        {ops.length ? (
          <View style={{ gap: 8 }}>
            <T bold>Operator</T>
            {ops.map((o) => <Btn key={o.uuid} small testID={`repair-operator-${o.uuid}`} kind={f.operator_id === o.uuid ? "primary" : "secondary"} title={o.name}
              onPress={() => setF({ ...f, operator_id: o.uuid, operator_name: o.name })} />)}
          </View>
        ) : null}
        <Input testID="repair-operator-input" label="Customer or operator" value={f.operator_name} onChangeText={(s) => setF({ ...f, operator_name: s, operator_id: ops.find((o) => o.name === s)?.uuid ?? f.operator_id })} />
        <Input testID="repair-po-input" label="Contract or PO number" value={f.po} onChangeText={set("po")} />
        <Input testID="repair-railroad-input" label="Railroad" value={f.railroad} onChangeText={set("railroad")} />
        <Input testID="repair-track-input" label="Track" value={f.track} onChangeText={set("track")} />
        <Input testID="repair-milepost-input" label="Milepost" value={f.milepost} onChangeText={set("milepost")} />
        <T muted size={13}>Authorized repair: no proposal or customer acceptance needed.</T>
        <Btn testID="repair-open-button" title="Open repair" loading={busy} onPress={open} />
      </ScrollView>
    </Screen>
  );
}
