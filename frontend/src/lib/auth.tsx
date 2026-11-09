import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError } from "./api";
import type { Meta, User } from "./types";

interface AuthState {
  user: User | null;
  meta: Meta | null;
  loading: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);

  const loadSession = useCallback(async () => {
    try {
      const me = await api.get<User>("/auth/me");
      setUser(me);
      // Enumerations and limits come from the server so the client does not
      // hard-code them; fetched once a session is known to be valid.
      setMeta(await api.get<Meta>("/meta"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      } else {
        throw err;
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const signIn = useCallback(async (username: string, password: string) => {
    const me = await api.post<User>("/auth/login", { username, password });
    setUser(me);
    setMeta(await api.get<Meta>("/meta"));
  }, []);

  const signOut = useCallback(async () => {
    await api.post<void>("/auth/logout", {});
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    setUser(await api.get<User>("/auth/me"));
  }, []);

  return (
    <AuthContext.Provider value={{ user, meta, loading, signIn, signOut, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Enumerations, with safe fallbacks if /meta has not loaded yet. */
export function useMeta(): Meta {
  const { meta } = useAuth();
  return (
    meta ?? {
      app_name: "MediTrack",
      sexes: ["Male", "Female", "Other"],
      appointment_statuses: ["Scheduled", "Completed", "Cancelled", "No show"],
      payment_statuses: ["Unpaid", "Paid", "Waived"],
      slot_minutes: 20,
      max_attachment_bytes: 10 * 1024 * 1024,
      allowed_attachment_types: {},
      storage_backend: "unknown",
    }
  );
}
