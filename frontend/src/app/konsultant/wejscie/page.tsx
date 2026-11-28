"use client";

/**
 * `/konsultant/wejscie#<token>` — link z maila. Token idzie we fragmencie adresu, więc nie
 * trafia do logów serwera ani do nagłówka Referer. Sesję zakłada POST, bo skanery poczty
 * otwierają adresy same, a fragment czyta dopiero skrypt w przeglądarce.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { PortalNotice, PortalShell } from "@/components/consultant-portal/PortalShell";
import { Button } from "@/components/ui/button";
import {
  PortalApiError,
  portalApi,
  savePortalSession,
  trainerPortalApi,
} from "@/lib/api/consultant-portal";

/** Link trenera z rynku (0808) ma we fragmencie `trener=<token>`. */
const TRAINER_PREFIX = "trener=";

export default function ConsultantPortalEntryPage() {
  const router = useRouter();
  const started = useRef(false);
  const [state, setState] = useState<"working" | "invalid" | "unavailable">("working");

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const fragment = window.location.hash.replace(/^#/, "");
    window.history.replaceState(null, "", window.location.pathname);
    const trainer = fragment.startsWith(TRAINER_PREFIX);
    const token = trainer ? fragment.slice(TRAINER_PREFIX.length) : fragment;
    if (!token) {
      setState("invalid");
      return;
    }
    (trainer ? trainerPortalApi : portalApi)
      .openSession(token)
      .then((opened) => {
        savePortalSession(opened.session_token, trainer ? "trainer" : "consultant");
        router.replace(trainer ? "/konsultant/szkolenia" : "/konsultant");
      })
      .catch((failure: unknown) => {
        const refused = failure instanceof PortalApiError && failure.status < 500 && failure.status !== 429;
        setState(refused ? "invalid" : "unavailable");
      });
  }, [router]);

  return (
    <PortalShell>
      {state === "working" ? <p className="text-sm text-muted-foreground">Otwieramy strefę konsultanta…</p> : null}
      {state === "invalid" ? (
        <PortalNotice title="Link nieprawidłowy lub wygasły">
          <p>Link działa 30 minut i tylko raz. Poproś o nowy.</p>
          <Button size="sm" className="mt-2" onClick={() => router.replace("/konsultant")}>
            Poproś o nowy link
          </Button>
        </PortalNotice>
      ) : null}
      {state === "unavailable" ? (
        <PortalNotice tone="error" title="Nie udało się otworzyć linku">
          <p>To chwilowy problem po naszej stronie. Spróbuj ponownie za kilka minut.</p>
        </PortalNotice>
      ) : null}
    </PortalShell>
  );
}
