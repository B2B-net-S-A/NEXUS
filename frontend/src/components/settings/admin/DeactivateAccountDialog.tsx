"use client";

/**
 * „Wyłącz konto” w Ustawieniach → Osoby i role (decyzja Artura 28.10.2026).
 *
 * Do 28.10 „Dezaktywuj” wyłączało konto jednym kliknięciem w menu, bez okna,
 * a kandydaci tej osoby zostawali bez nikogo. Teraz admin widzi przed
 * wyłączeniem, ilu kandydatów przejmie który Delivery Lead
 * (`GET /api/admin/users/{id}/departure-preview`). Samo przekazanie robi
 * serwer przy wyłączeniu (`services/departure_care.py`), więc awaria podglądu
 * nie blokuje wyłączenia — okno mówi tylko, że listy nie udało się pobrać.
 */

import { AppModal } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  columnsText,
  jobsLocative,
  jobsPhrase,
  peoplePhrase,
  useDeparturePreview,
  type DeparturePreviewCaretaker,
} from "@/lib/departed-care";

const VIA_NOTE: Record<DeparturePreviewCaretaker["via"][number], string | null> = {
  job_dl: null,
  client_dl: "główny DL klienta",
  hor: "Head of Recruitment — rekrutacje bez DL-a",
};

interface Props {
  user: { id: number; name: string | null; email: string } | null;
  loading: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function DeactivateAccountDialog({ user, loading, onConfirm, onCancel }: Props) {
  const preview = useDeparturePreview(user?.id ?? null);
  const data = preview.data;
  const pairs = data?.pairs ?? 0;
  const name = user?.name || user?.email || "";

  return (
    <AppModal
      open={user != null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      title={`Wyłączyć konto: ${name}?`}
      description="Osoba nie zaloguje się do NEXUSA. Historia jej pracy zostaje."
      footer={
        <>
          <Button type="button" variant="outline" onClick={onCancel}>
            Anuluj
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={onConfirm}
            loading={loading}
            disabled={preview.isLoading}
          >
            {pairs > 0 ? "Wyłącz konto i przekaż Delivery Leadom" : "Wyłącz konto"}
          </Button>
        </>
      }
    >
      {preview.isLoading ? (
        <p className="text-sm text-muted-foreground">Sprawdzam, co zostaje po tej osobie…</p>
      ) : preview.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(
            preview.error,
            "Nie udało się sprawdzić, co zostaje po tej osobie.",
          )}{" "}
          Kandydaci i tak przejdą do Delivery Leadów po wyłączeniu.
        </p>
      ) : preview.isSuccess && pairs === 0 ? (
        <p className="text-sm text-muted-foreground">
          Ta osoba nie prowadzi kandydatów w otwartych rekrutacjach.
        </p>
      ) : data ? (
        <div className="space-y-3 text-sm">
          <p>
            Zostaje po tej osobie <strong>{peoplePhrase(pairs)}</strong> w{" "}
            {jobsLocative(data.jobs)} otwartych. Po wyłączeniu przejdą do Delivery Leadów tych rekrutacji — każdy dostanie mail ze
            swoją listą i domknie ją sam.
          </p>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {data.caretakers.map((c) => (
              <li key={c.user_id} className="flex items-start justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="font-medium">
                    {c.name}
                    {c.via
                      .map((v) => VIA_NOTE[v])
                      .filter(Boolean)
                      .map((note) => (
                        <span key={note} className="ml-1.5 text-xs font-normal text-muted-foreground">
                          ({note})
                        </span>
                      ))}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {[c.clients.join(", "), jobsPhrase(c.jobs)].filter(Boolean).join(" · ")}
                  </p>
                  <p className="text-xs text-muted-foreground">{columnsText(c.columns)}</p>
                </div>
                <span className="shrink-0 tabular-nums font-semibold">{c.pairs}</span>
              </li>
            ))}
          </ul>
          {data.unassigned > 0 ? (
            <p role="alert" className="text-xs text-destructive">
              {peoplePhrase(data.unassigned)} nie ma komu przekazać: rekrutacja bez Delivery
              Leada, a w firmie nie ma aktywnego Head of Recruitment.
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            „Prowadzi” zostaje przy tej osobie, więc domknięcie nie liczy się Delivery Leadom do
            Ligi, KPI ani premii. Odchodzi z firmy na dłużej? Lepiej założyć sprawę odejścia
            w „Ludziach” — Kadry dostaną też zadania sprzętu i dostępu.
          </p>
        </div>
      ) : null}
    </AppModal>
  );
}
