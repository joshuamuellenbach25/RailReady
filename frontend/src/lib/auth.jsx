import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, endpoints, getToken, setToken } from "./api";

const AuthCtx = createContext({});
export const useAuth = () => useContext(AuthCtx);

const readJSON = (k) => {
  try {
    return JSON.parse(localStorage.getItem(k) || "null");
  } catch {
    return null;
  }
};

// Demo session responses are read tolerantly.
const sessionIdOf = (r) => r?.session_id ?? r?.demo_session_id ?? r?.session?.session_id ?? r?.session?.uuid ?? r?.session?.id ?? r?.uuid ?? r?.id ?? null;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = restoring, false = signed out
  const [workspace, setWorkspace] = useState(null);
  const [demo, setDemo] = useState(() => readJSON("rr_demo"));

  const store = (u, ws, d) => {
    setUser(u);
    setWorkspace(ws);
    setDemo(d);
    localStorage.setItem("rr_user", JSON.stringify({ user: u, workspace: ws }));
    if (d) localStorage.setItem("rr_demo", JSON.stringify(d));
    else localStorage.removeItem("rr_demo");
  };

  useEffect(() => {
    (async () => {
      const cached = readJSON("rr_user");
      if (!getToken()) return setUser(false);
      if (cached) {
        setUser(cached.user);
        setWorkspace(cached.workspace);
      }
      try {
        const me = await api("/auth/me"); // role and names always from the server
        setUser(me.user);
        setWorkspace(me.workspace);
        localStorage.setItem("rr_user", JSON.stringify({ user: me.user, workspace: me.workspace }));
      } catch (e) {
        if (e?.status === 401) {
          setToken(null);
          localStorage.removeItem("rr_user");
          setUser(false);
        } else if (!cached) setUser(false); // offline with nothing cached: show sign-in, keep the token
      }
    })();
  }, []);

  const apply = useCallback(async (r, demoInfo) => {
    setToken(r.token || r.access_token);
    let u = r.user;
    let ws = r.workspace;
    if (!u) {
      const me = await api("/auth/me");
      u = me.user;
      ws = me.workspace;
    }
    store(u, ws, demoInfo);
  }, []);

  const signIn = useCallback(async (email, password) => apply(await api("/auth/login", { body: { email, password } }), null), [apply]);

  const startDemo = useCallback(async () => {
    const r = await endpoints.createDemo();
    await apply(r, { session_id: sessionIdOf(r), started_at: new Date().toISOString() });
  }, [apply]);

  const resetDemo = useCallback(async () => {
    const r = demo?.session_id ? await endpoints.resetDemo(demo.session_id) : await endpoints.createDemo();
    await apply(r, { session_id: sessionIdOf(r), started_at: new Date().toISOString(), previous: demo?.session_id });
  }, [apply, demo]);

  const signOut = useCallback(() => {
    setToken(null);
    localStorage.removeItem("rr_user");
    localStorage.removeItem("rr_demo");
    setDemo(null);
    setUser(false);
  }, []);

  const isForeman = !!user && user.role === "foreman";
  const isAdmin = !!user && user.role === "admin"; // UI hint only; the server enforces 403
  const canConfigure = !!user && ["admin", "estimator"].includes(user.role);
  const isDemo = !!demo || !!user?.demo_session_id || !!workspace?.demo_session_id || !!workspace?.is_demo;
  return (
    <AuthCtx.Provider value={{ user, workspace, demo, isDemo, isForeman, isAdmin, canConfigure, signIn, startDemo, resetDemo, signOut }}>
      {children}
    </AuthCtx.Provider>
  );
}
