"use client";

/**
 * `/konsultant/*` — panel konsultanta. Bez sesji prośba o link, z sesją menu i ekrany.
 * Wyłączony portal (`app_settings['consultant_portal']`) odpowiada 404 i tu mówi to
 * zdaniem. Awaria sieci jest osobnym stanem: nie wygląda jak wyłączony portal.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { LoginForm } from "@/components/consultant-portal/LoginForm";
import { PanelNav } from "@/components/consultant-portal/PanelNav";
import { PortalNotice, PortalShell } from "@/components/consultant-portal/PortalShell";
import { Button } from "@/components/ui/button";
import {
  PortalApiError,
  clearPortalSession,
  portalApi,
  portalKeys,
  portalSession,
  usePortalQuery,
} from "@/lib/api/consultant-portal";

export default function ConsultantPanelLayout({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  // `sessionStorage` istnieje dopiero w przeglądarce, więc pierwszy render jest bez sesji.
  const [mounted, setMounted] = useState(false);
  const [session, setSession] = useState<string | null>(null);
  useEffect(() => {
    setSession(portalSession());
    setMounted(true);
  }, []);

  const status = usePortalQuery(["consultant-portal", "status"], portalApi.status, mounted);
  const me = usePortalQuery(portalKeys.me, portalApi.me, mounted && session !== null && status.isSuccess);
  const expired = me.error instanceof PortalApiError && me.error.status === 401;

  const endSession = () => {
    clearPortalSession();
    client.removeQueries({ queryKey: ["consultant-portal"] });
    setSession(null);
  };
  useEffect(() => {
    if (expired) clearPortalSession();
  }, [expired]);

  const logout = async () => {
    try {
      await portalApi.logout();
    } catch {
      // Lokalnie i tak kończymy: token znika z karty, a na serwerze wygasa sam.
    }
    endSession();
  };

  const closed = status.error instanceof PortalApiError && status.error.status === 404;
  return (
    <PortalShell
      onLogout={me.isSuccess ? logout : undefined}
      nav={me.isSuccess ? <PanelNav me={me.data} /> : undefined}
    >
      {!mounted || status.isLoading ? <p className="text-sm text-muted-foreground">Wczytujemy…</p> : null}
      {closed ? (
        <PortalNotice title="Panel konsultanta nie jest jeszcze dostępny">
          <p>W sprawach bieżących napisz do swojego opiekuna.</p>
        </PortalNotice>
      ) : null}
      {status.isError && !closed ? (
        <PortalNotice tone="error" title="Nie udało się otworzyć panelu konsultanta">
          <p>To chwilowy problem po naszej stronie. Spróbuj ponownie za kilka minut.</p>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => status.refetch()}>
            Spróbuj ponownie
          </Button>
        </PortalNotice>
      ) : null}
      {status.isSuccess && (session === null || expired) ? (
        <>
          {expired ? <PortalNotice title="Sesja wygasła">Poproś o nowy link.</PortalNotice> : null}
          <LoginForm />
        </>
      ) : null}
      {status.isSuccess && session !== null && !expired ? (
        <>
          {me.isLoading ? <p className="text-sm text-muted-foreground">Wczytujemy…</p> : null}
          {me.isError ? (
            <PortalNotice tone="error" title="Nie udało się wczytać Twoich danych">
              <Button size="sm" variant="outline" className="mt-2" onClick={() => me.refetch()}>
                Spróbuj ponownie
              </Button>
            </PortalNotice>
          ) : null}
          {me.isSuccess ? children : null}
        </>
      ) : null}
    </PortalShell>
  );
}
