"use client";

/**
 * „Do dopytania pod formularz klienta” w formularzu screeningu (19.11.2026).
 *
 * Rekruter w oknie formularza CV klienta (CEZ) wysyła braki lat do ściągi
 * screeningu — pola, do których CV nie ma żadnego stanowiska. Tu stoją jako
 * pytania do zadania w rozmowie; odpowiedź z notatki screeningu trafia do
 * formularza przy „Wypełnij ponownie”. U klienta bez formularza i bez pytań
 * blok się nie renderuje. Awaria odczytu też go nie pokazuje — jak inne
 * podpowiedzi formularza screeningu („awaria odczytu profilu nie psuje
 * formularza”); te same pytania stoją w oknie formularza w panelu osoby.
 */

import { useClientForm } from "@/lib/api/clientForms";

export function ClientFormScreeningAsks({ stageId }: { stageId: number }) {
  const query = useClientForm(stageId);
  if (!query.isSuccess || query.data.status !== "filled") return null;
  const asks = query.data.fields.filter((field) => field.years?.ask && !field.value);
  if (!asks.length) return null;
  return (
    <section
      aria-label="Do dopytania pod formularz klienta"
      className="space-y-1.5 rounded-lg border border-border bg-background/40 p-3"
      data-testid="client-form-screening-asks"
    >
      <p className="text-xs font-medium text-foreground">
        Do dopytania pod formularz klienta · {asks.length}
      </p>
      <p className="text-[11px] text-muted-foreground">
        Lat w tych kompetencjach nie ma w CV. Zapisz odpowiedź w notatce — „Wypełnij ponownie” wpisze ją do
        formularza.
      </p>
      <ul className="list-disc space-y-0.5 pl-4 text-xs text-foreground">
        {asks.map((field) => (
          <li key={field.id}>{field.years?.question}</li>
        ))}
      </ul>
    </section>
  );
}

export default ClientFormScreeningAsks;
