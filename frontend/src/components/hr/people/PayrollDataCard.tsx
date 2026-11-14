"use client";

import { useState } from "react";

import { PersonDataDialog } from "@/components/accounting/payroll/PersonDataDialog";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { usePersonData } from "@/lib/api/payroll-lists";
import { isForbiddenError, isNotFoundError } from "@/lib/view-state";

/**
 * Dane do listy płac (K7a) w zakładce „Rozliczenia” kartoteki: wejście dla
 * Administracji współpracy, która bez „Modułu Finanse” nie otwiera Księgowości.
 * Serwer odpowiada 404/403, gdy moduł płac Księgowości jest wyłączony albo
 * osoba nie ma prawa — wtedy karty nie ma. PESEL tylko jako maska z API.
 */
export function PayrollDataCard({
  userId,
  kind,
  enabled,
}: {
  userId: number;
  kind: string | null;
  enabled: boolean;
}) {
  const subject = { userId };
  const person = usePersonData(subject, enabled);
  const [open, setOpen] = useState(false);

  if (!enabled) return null;
  if (person.isError) {
    if (isForbiddenError(person.error) || isNotFoundError(person.error)) return null;
    return (
      <Card className="p-4">
        <QueryStateNotice
          state="error"
          description={apiErrorMessage(person.error, "Nie udało się wczytać danych do listy płac.")}
          onRetry={() => person.refetch()}
        />
      </Card>
    );
  }
  if (!person.isSuccess) return null;
  const data = person.data;
  const missing = data.missing_labels ?? [];

  return (
    <Card className="space-y-2 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <h3 className="text-sm font-semibold">Dane do listy płac (ZUS i PIT)</h3>
          <p className="text-[13px] text-muted-foreground">
            {data.pesel_masked ? `PESEL ${data.pesel_masked}` : "Bez PESEL-u"}
            {data.exists ? "" : " · jeszcze nie uzupełnione"}
          </p>
        </div>
        {data.can_edit ? (
          <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
            {data.exists ? "Zmień" : "Uzupełnij"}
          </Button>
        ) : null}
      </div>
      {missing.length > 0 ? (
        <p className="text-[13px] text-warning-muted-foreground">Brakuje: {missing.join(", ")}.</p>
      ) : (
        <p className="text-[13px] text-muted-foreground">Komplet danych do listy płac, KEDU i PIT-11.</p>
      )}
      {!data.can_edit ? (
        <p className="text-[13px] text-muted-foreground">
          Swoich danych płacowych nie zmieniasz sam — zrobi to druga osoba z Administracji współpracy albo
          Rozliczeń.
        </p>
      ) : null}
      <PersonDataDialog subject={subject} kind={kind} open={open} onOpenChange={setOpen} />
    </Card>
  );
}
