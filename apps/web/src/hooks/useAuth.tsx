"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiError, setCsrfToken } from "@/lib/api/client";
import type { AuthUserResponse } from "@/types/api";

interface AuthContextValue {
  user: AuthUserResponse | null;
  isLoadingAuth: boolean;
  isAuthenticated: boolean;
  authError: Error | null;
  login: (username: string, password: string) => Promise<AuthUserResponse>;
  logout: () => Promise<void>;
  switchKitchen: (kitchenId: string) => Promise<AuthUserResponse>;
  refreshAuth: (silent?: boolean) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<AuthUserResponse | null>(null);
  const [isLoadingAuth, setIsLoadingAuth] = useState(true);
  const [authError, setAuthError] = useState<Error | null>(null);

  const refreshAuth = useCallback(async (silent = false) => {
    if (!silent) {
      setIsLoadingAuth(true);
      setAuthError(null);
    }
    try {
      const me = await apiClient.getMe();
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setCsrfToken(null);
        setUser(null);
      } else if (!silent) {
        setAuthError(err instanceof Error ? err : new Error("Sesi belum dapat diperiksa."));
      }
    } finally {
      if (!silent) {
        setIsLoadingAuth(false);
      }
    }
  }, []);

  useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  const login = useCallback(
    async (username: string, password: string) => {
      const loggedIn = await apiClient.login(username, password);
      qc.clear();
      setAuthError(null);
      setUser(loggedIn);
      return loggedIn;
    },
    [qc]
  );

  const logout = useCallback(async () => {
    try {
      await apiClient.logout();
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 401) throw err;
    }
    setCsrfToken(null);
    setUser(null);
    qc.clear();
  }, [qc]);

  const switchKitchen = useCallback(
    async (kitchenId: string) => {
      const updated = await apiClient.switchKitchen(kitchenId);
      qc.clear();
      setUser(updated);
      return updated;
    },
    [qc]
  );

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoadingAuth,
        isAuthenticated: Boolean(user),
        authError,
        login,
        logout,
        switchKitchen,
        refreshAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}
