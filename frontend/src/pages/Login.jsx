import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { LogIn, TrainFront } from "lucide-react";
import { errText } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Banner, Btn, Field } from "@/components/rr/ui";

export default function Login() {
  const { signIn } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function go(e) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      nav(loc.state?.from || "/office/jobs", { replace: true });
    } catch (x) {
      setErr(errText(x)); // inputs kept
    } finally {
      setBusy(false);
    }
  }

  return (
    <main data-testid="login-page" className="flex min-h-screen items-start justify-center bg-[#F3F4F4] px-4 py-12 md:items-center">
      <form onSubmit={go} className="w-full max-w-md space-y-5 rounded-lg border border-[#D9DEE2] bg-white p-6 md:p-8">
        <div className="flex items-center gap-3 border-b border-[#B32624] pb-3">
          <TrainFront aria-hidden className="h-9 w-9 text-[#B32624]" />
          <h1 className="text-3xl font-semibold tracking-tight">Sign in</h1>
        </div>
        <p className="text-[#59636B]">Sign in to your RailReady account.</p>
        <Field id="login-email" testid="login-email-input" label="Email" type="email" autoComplete="username" value={email} onChange={setEmail} placeholder="name@example.com" />
        <Field id="login-password" testid="login-password-input" label="Password" type="password" autoComplete="current-password" value={password} onChange={setPassword} />
        {err ? <Banner testid="login-error-message" tone="error" text={err} /> : null}
        <Btn type="submit" testid="login-submit-button" icon={LogIn} loading={busy} disabled={!email || !password} className="w-full">Sign in</Btn>
        <p className="text-sm text-[#59636B]">
          Just exploring? <Link data-testid="login-demo-link" to="/demo" className="font-bold text-[#B32624] underline">Try the demo.</Link>
        </p>
      </form>
    </main>
  );
}
