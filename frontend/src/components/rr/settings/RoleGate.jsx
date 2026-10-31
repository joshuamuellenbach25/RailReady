import { Lock } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Banner } from "../ui";

/** Hides settings screens from foremen (the server still returns 403 for writes). */
export default function RoleGate({ children }) {
  const { canConfigure } = useAuth();
  if (!canConfigure) return <Banner testid="settings-forbidden" tone="warning" icon={Lock} text="Settings are available to estimators and admins." />;
  return children;
}
