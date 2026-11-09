import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Me } from "./api";

interface MeState {
  me: Me | null;
  refresh: () => Promise<Me | null>;
  setMe: (me: Me) => void;
  toast: (text: string) => void;
}

const Ctx = createContext<MeState>({
  me: null,
  refresh: async () => null,
  setMe: () => undefined,
  toast: () => undefined,
});

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [toastText, setToastText] = useState("");

  const refresh = useCallback(async () => {
    try {
      const data = await api.get<Me>("/api/me");
      setMe(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    void refresh().then(() => {
      const inv = new URLSearchParams(window.location.search).get("inv");
      if (inv) void api.post("/api/me/invite", { code: inv }).catch(() => undefined);
    });
  }, [refresh]);

  const toast = useCallback((text: string) => {
    setToastText(text);
    window.setTimeout(() => setToastText((t) => (t === text ? "" : t)), 2600);
  }, []);

  return (
    <Ctx.Provider value={{ me, refresh, setMe, toast }}>
      {children}
      <div className={`toast ${toastText ? "toast-on" : ""}`} role="status" aria-live="polite">
        {toastText}
      </div>
    </Ctx.Provider>
  );
}

export function useApp() {
  return useContext(Ctx);
}
