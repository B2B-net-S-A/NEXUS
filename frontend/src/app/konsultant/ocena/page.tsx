"use client";

/**
 * `/konsultant/ocena#<token>` — ocena rozmowy z linku w mailu, bez sesji.
 * Token we fragmencie adresu, jak przy logowaniu. Link ważny 7 dni i tylko raz.
 */
import { useEffect, useState } from "react";

import { slotLabel } from "@/components/consultant-portal/portal-model";
import { PortalNotice, PortalShell } from "@/components/consultant-portal/PortalShell";
import { RatingFields } from "@/components/consultant-portal/RatingFields";
import { apiErrorMessage } from "@/lib/api-error";
import {
  PortalApiError,
  portalApi,
  type PortalRatingForm,
  type PortalRatingInput,
} from "@/lib/api/consultant-portal";

export default function ConsultantPortalRatingPage() {
  const [token, setToken] = useState<string | null>(null);
  const [form, setForm] = useState<PortalRatingForm | null>(null);
  const [state, setState] = useState<"loading" | "form" | "done" | "invalid" | "unavailable">("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const raw = window.location.hash.replace(/^#/, "");
    window.history.replaceState(null, "", window.location.pathname);
    if (!raw) {
      setState("invalid");
      return;
    }
    setToken(raw);
    portalApi
      .ratingForm(raw)
      .then((loaded) => {
        setForm(loaded);
        setState("form");
      })
      .catch((failure: unknown) => {
        const refused = failure instanceof PortalApiError && failure.status < 500 && failure.status !== 429;
        setState(refused ? "invalid" : "unavailable");
      });
  }, []);

  const submit = async (input: PortalRatingInput) => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await portalApi.rateByLink(token, input);
      setState("done");
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się zapisać oceny. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PortalShell>
      {state === "loading" ? <p className="text-sm text-muted-foreground">Wczytujemy…</p> : null}
      {state === "invalid" ? (
        <PortalNotice title="Link nieprawidłowy lub wygasły">
          <p>Link do oceny działa 7 dni i tylko raz. Rozmowę ocenisz też w strefie konsultanta.</p>
        </PortalNotice>
      ) : null}
      {state === "unavailable" ? (
        <PortalNotice tone="error" title="Nie udało się otworzyć linku">
          <p>To chwilowy problem po naszej stronie. Spróbuj ponownie za kilka minut.</p>
        </PortalNotice>
      ) : null}
      {state === "done" ? <PortalNotice title="Dziękujemy za ocenę" /> : null}
      {state === "form" && form ? (
        <section className="mx-auto max-w-lg space-y-5">
          <div className="text-center">
            <h1 className="text-xl font-semibold">Jak oceniasz tę rozmowę?</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {form.host ? `${form.host} · ` : ""}
              {slotLabel(form.start_at)} · {form.topic_label}
            </p>
          </div>
          <RatingFields
            busy={busy}
            error={error}
            footnote="Link ważny 7 dni. Ocena idzie do kierownika back office, a nie wprost do osoby prowadzącej."
            onSubmit={submit}
          />
        </section>
      ) : null}
    </PortalShell>
  );
}
