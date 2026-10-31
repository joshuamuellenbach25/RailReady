import { createContext, PropsWithChildren, useCallback, useContext, useEffect, useState } from "react";
import { api, setToken } from "./api";
import { storage } from "./utils/storage";

export type User = { uuid: string; email: string; name: string; role: "foreman" | "estimator" | "admin"; workspace_id: string };
type Ctx = {
  user: User | null | false;
  workspace: any;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};
const AuthCtx = createContext<Ctx>({} as Ctx);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<User | null | false>(null);
  const [workspace, setWorkspace] = useState<any>(null);

  useEffect(() => {
    (async () => {
      const t = await storage.secureGet("auth_token", null);
      const cached = await storage.getItem("auth_user", null);
      if (!t || !cached) return setUser(false);
      setToken(String(t));
      const c = JSON.parse(String(cached));
      setUser(c.user);
      setWorkspace(c.workspace);
      try {
        const me = await api("/auth/me"); // refresh role from server; offline keeps cached session
        setUser(me.user);
        setWorkspace(me.workspace);
      } catch (e: any) {
        if (e?.status === 401) {
          setToken(null);
          await storage.secureRemove("auth_token");
          setUser(false);
        }
      }
    })();
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const r = await api("/auth/login", { body: { email, password } });
    setToken(r.token);
    await storage.secureSet("auth_token", r.token);
    await storage.setItem("auth_user", JSON.stringify({ user: r.user, workspace: r.workspace }));
    setWorkspace(r.workspace);
    setUser(r.user);
  }, []);

  const signOut = useCallback(async () => {
    setToken(null);
    await storage.secureRemove("auth_token");
    await storage.removeItem("auth_user");
    setUser(false);
  }, []);

  // Children mount only after the stored token is restored, so deep links never fire unauthenticated first fetches.
  return <AuthCtx.Provider value={{ user, workspace, signIn, signOut }}>{user === null ? null : children}</AuthCtx.Provider>;
}
