import { router } from "expo-router";
import { useState } from "react";
import { Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Banner, Btn, Icon, Input, T } from "@/src/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const insets = useSafeAreaInsets();
  const s = useStyles();
  const { colors } = useTheme();

  async function go() {
    setErr(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      router.replace("/");
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={s.root}>
      <KeyboardAwareScrollView bottomOffset={24} keyboardShouldPersistTaps="handled" contentContainerStyle={[s.content, { paddingTop: insets.top + 32, paddingBottom: insets.bottom + 24 }]}>
        <View style={s.brand}>
          <Icon name="train-variant" size={32} color={colors.onSurface} />
          <Text style={s.title}>RailReady</Text>
        </View>
        <T muted size={16}>Field inspections for track work. Sign in with your work account.</T>
        <View style={s.form}>
          <Input testID="login-email-input" label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" placeholder="name@example.com" />
          <PasswordInput value={password} onChangeText={setPassword} />
          {err ? <Banner testID="login-error-message" tone="error" icon="alert-circle-outline" text={err} /> : null}
          <Btn testID="login-submit-button" title="Sign in" icon="login" loading={busy} disabled={!email || !password} onPress={go} />
          <Btn testID="login-camera-check-button" kind="ghost" small title="Camera check" icon="camera-outline" onPress={() => router.push("/camera-smoke")} />
        </View>
      </KeyboardAwareScrollView>
    </View>
  );
}

function PasswordInput({ value, onChangeText }: { value: string; onChangeText: (s: string) => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>Password</Text>
      <TextInput testID="login-password-input" accessibilityLabel="Password" secureTextEntry value={value} onChangeText={onChangeText}
        autoCapitalize="none" returnKeyType="done" submitBehavior="blurAndSubmit" style={s.input} placeholderTextColor={colors.muted} />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  content: { paddingHorizontal: 20, gap: 16 },
  brand: { flexDirection: "row", alignItems: "center", gap: 12, paddingBottom: 4 },
  title: { fontSize: 28, fontWeight: "600", color: c.onSurface },
  form: { gap: 16, marginTop: 8 },
  label: { color: c.onSurface, fontSize: 14, fontWeight: "500" },
  input: { minHeight: 48, borderWidth: 1, borderColor: c.border, borderRadius: 8, paddingHorizontal: 12, fontSize: 16, color: c.onSurface, backgroundColor: c.surface },
}));
