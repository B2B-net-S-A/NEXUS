"use client";

/**
 * `/konsultant/*` — panel konsultanta. Bez sesji prośba o link, z sesją menu i ekrany.
 * Wyłączony portal (`app_settings['consultant_portal']`) odpowiada 404 i tu mówi to
 * zdaniem. Awaria sieci jest osobnym stanem: nie wygląda jak wyłączony portal.
 */
import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { LoginForm } from "@/components/consultant-portal/LoginForm";
import { PanelNav, trainerMayOpen } from "@/components/consultant-portal/PanelNav";
import { PortalNotice, PortalShell } from "@/components/consultant-portal/PortalShell";
import { Button } from "@/components/ui/button";
import {
  PortalApiError,
  clearPortalSession,
  portalApi,
  portalKeys,
  portalKind,
  portalSession,
  trainerPortalApi,
  usePortalQuery,
  type PortalKind,
} from "@/lib/api/consultant-portal";

export default function ConsultantPanelLayout({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  // `sessionStorage` istnieje dopiero w przeglądarce, więc pierwszy render jest bez sesji.
  const [mounted, setMounted] = useState(false);
  const [session, setSession] = useState<string | null>(null);
  const [kind, setKind] = useState<PortalKind>("consultant");
  const pathname = usePathname();
  const router = useRouter();
  useEffect(() => {
    setSession(portalSession());
    setKind(portalKind());
    setMounted(true);
  }, []);

  // Dwa wejścia na jednym ekranie: panel konsultanta i panel trenera z rynku (0807),
  // każde z własnym włącznikiem. Zamknięte oba = komunikat „niedostępny”.
  const consultantStatus = usePortalQuery(["consultant-portal", "status"], portalApi.status, mounted);
  const trainerStatus = usePortalQuery(
    ["consultant-portal", "trainer-status"],
    trainerPortalApi.status,
    mounted,
  );
  const status = kind === "trainer" ? trainerStatus : consultantStatus;
  const anyOpen = consultantStatus.isSuccess || trainerStatus.isSuccess;
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

  const isClosed = (query: typeof status) =>
    query.error instanceof PortalApiError && query.error.status === 404;
  const closed = isClosed(consultantStatus) && isClosed(trainerStatus);
  const failed = !anyOpen && !closed && (consultantStatus.isError || trainerStatus.isError);
  const loading = consultantStatus.isLoading || trainerStatus.isLoading;
  const marketTrainer = me.isSuccess && me.data.kind === "trainer";
  const wrongScreen = marketTrainer && !trainerMayOpen(pathname);
  useEffect(() => {
    if (wrongScreen) router.replace("/konsultant/szkolenia");
  }, [router, wrongScreen]);
  return (
    <PortalShell
      onLogout={me.isSuccess ? logout : undefined}
      nav={me.isSuccess ? <PanelNav me={me.data} /> : undefined}
    >
      {!mounted || (loading && !anyOpen) ? <p className="text-sm text-muted-foreground">Wczytujemy…</p> : null}
      {closed ? (
        <PortalNotice title="Panel konsultanta nie jest jeszcze dostępny">
          <p>W sprawach bieżących napisz do swojego opiekuna.</p>
        </PortalNotice>
      ) : null}
      {failed ? (
        <PortalNotice tone="error" title="Nie udało się otworzyć panelu konsultanta">
          <p>To chwilowy problem po naszej stronie. Spróbuj ponownie za kilka minut.</p>
          <Button
            size="sm"
            variant="outline"
            className="mt-2"
            onClick={() => {
              void consultantStatus.refetch();
              void trainerStatus.refetch();
            }}
          >
            Spróbuj ponownie
          </Button>
        </PortalNotice>
      ) : null}
      {anyOpen && (session === null || expired || isClosed(status)) ? (
        <>
          {expired ? <PortalNotice title="Sesja wygasła">Poproś o nowy link.</PortalNotice> : null}
          <LoginForm consultantOpen={consultantStatus.isSuccess} trainerOpen={trainerStatus.isSuccess} />
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
          {me.isSuccess && !wrongScreen ? children : null}
        </>
      ) : null}
    </PortalShell>
  );
}
