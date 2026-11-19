"use client";

/**
 * Siatka „Lata w kompetencjach” w oknie formularza CV klienta (19.11.2026,
 * wariant B z makiet dla DL CEZ: „nie daje rady odczytać lat doświadczenia”).
 *
 * Wiersze to pola lat wzoru (i punkty tabeli punktowej liczone z lat),
 * kolumny — stanowiska z CV. Lata liczy serwer z dat ról; domyślnie liczą się
 * role „wprost” (opis nazywa kompetencję) i „pośrednio” (praca jej wymagała).
 * Klik zdejmuje albo przywraca rolę, kolumna „Lata” zmienia się od razu
 * (`lib/client-form-years`), „Zapisz lata” wysyła wybór, a serwer przelicza.
 *
 * Pod siatką braki: pola bez żadnej roli idą do ściągi screeningu jako
 * pytania (rekruter zadaje je w rozmowie, formularz screeningu je pokazuje).
 */

import { useMemo, useState } from "react";
import { Check, ListPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ClientFormField, ClientFormYears, ClientFormYearsRole } from "@/lib/api/clientForms";
import { currentMonthIndex, monthsText, previewValue } from "@/lib/client-form-years";
import { cn } from "@/lib/utils";

type YearsField = ClientFormField & { years: ClientFormYears };

export interface ClientFormYearsGridProps {
  fields: ClientFormField[];
  readOnly?: boolean;
  saving?: boolean;
  onSaveRoles: (roles: Record<string, string[]>) => Promise<void> | void;
  onAsk: (fieldIds: string[]) => Promise<void> | void;
}

function hasYears(field: ClientFormField): field is YearsField {
  return Boolean(field.years);
}

function selectionOf(field: YearsField): string[] {
  return field.years.basis.filter((role) => role.on).map((role) => role.key);
}

function sameSet(a: string[], b: Set<string>): boolean {
  return a.length === b.size && a.every((key) => b.has(key));
}

/** Kolumny: role ze wszystkich pól, kolejność jak w CV (najpierw łączny staż). */
function rolesOf(fields: YearsField[]): ClientFormYearsRole[] {
  const seen = new Map<string, ClientFormYearsRole>();
  for (const field of [...fields].sort((a, b) =>
    a.years.kind === "total" ? -1 : b.years.kind === "total" ? 1 : 0,
  )) {
    for (const role of field.years.basis) if (!seen.has(role.key)) seen.set(role.key, role);
  }
  return [...seen.values()];
}

export function ClientFormYearsGrid({
  fields,
  readOnly = false,
  saving = false,
  onSaveRoles,
  onAsk,
}: ClientFormYearsGridProps) {
  const withYears = fields.filter(hasYears);
  const rows = withYears.filter((field) => field.years.kind !== "total");
  const total = withYears.find((field) => field.years.kind === "total");
  const roles = rolesOf(withYears);
  const now = currentMonthIndex();

  const serverPicked = useMemo(
    () => Object.fromEntries(rows.map((field) => [field.id, selectionOf(field)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fields],
  );
  const [picked, setPicked] = useState<Record<string, Set<string>>>({});
  const [seen, setSeen] = useState(serverPicked);
  if (seen !== serverPicked) {
    // Zapis albo ponowne wypełnienie — siatka wraca do stanu z serwera.
    setSeen(serverPicked);
    setPicked({});
  }
  const pickedOf = (field: YearsField) => picked[field.id] ?? new Set(serverPicked[field.id]);
  const toggle = (field: YearsField, key: string) =>
    setPicked((prev) => {
      const next = new Set(prev[field.id] ?? serverPicked[field.id]);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return { ...prev, [field.id]: next };
    });
  const changed = rows.filter((field) => !sameSet(serverPicked[field.id] ?? [], pickedOf(field)));

  const gaps = rows.filter(
    (field) => field.years.kind === "competency" && !field.value && !field.years.basis.length,
  );
  const askedIds = gaps.filter((field) => field.years.ask).map((field) => field.id);
  const [askPick, setAskPick] = useState<Set<string> | null>(null);
  const asking = askPick ?? new Set(askedIds.length ? askedIds : gaps.map((field) => field.id));

  if (!rows.length && !total) return null;

  return (
    <section aria-label="Lata w kompetencjach" className="space-y-2" data-testid="client-form-years">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Lata w kompetencjach · z ról w CV
        </h3>
        <p className="text-[11px] text-muted-foreground">
          <span className="font-semibold text-primary">●</span> rola wymienia wprost ·{" "}
          <span className="text-primary">◐</span> pośrednio · klik zdejmuje albo przywraca rolę
        </p>
      </div>
      {rows.length ? (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50 text-[11px] text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5 text-left font-medium">Kompetencja z formularza</th>
                {roles.map((role) => (
                  <th key={role.key} className="w-[92px] px-1 py-1.5 text-center font-medium leading-tight">
                    <span className="block truncate text-foreground" title={`${role.title} · ${role.employer}`}>
                      {role.employer || role.title}
                    </span>
                    <span className="block whitespace-nowrap">{role.period}</span>
                  </th>
                ))}
                <th className="w-[96px] px-2 py-1.5 text-right font-medium">Wartość</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((field) => {
                const on = pickedOf(field);
                const value = previewValue(field.years, on, now);
                const points = field.years.kind === "points";
                return (
                  <tr key={field.id}>
                    <td className="max-w-[320px] px-2 py-1 leading-tight text-foreground">
                      <span className="line-clamp-2" title={field.row_label ?? field.label}>
                        {field.row_label ?? field.label}
                      </span>
                      {field.years.skills && !field.years.basis.length ? (
                        <span className="block text-[10px] text-muted-foreground">
                          tylko lista umiejętności: „{field.years.skills}”
                        </span>
                      ) : null}
                      {field.years.minimum_months ? (
                        <span className="block text-[10px] text-muted-foreground">
                          ponad minimum {monthsText(field.years.minimum_months)}
                        </span>
                      ) : field.years.minimum_unknown ? (
                        <span className="block text-[10px] text-warning-muted-foreground">
                          minimum z wymagań nieznane — wpisz ręcznie
                        </span>
                      ) : null}
                    </td>
                    {roles.map((role) => {
                      const proof = field.years.basis.find((item) => item.key === role.key);
                      if (!proof) {
                        return (
                          <td key={role.key} className="px-1 py-1 text-center text-muted-foreground/40">
                            ·
                          </td>
                        );
                      }
                      const active = on.has(role.key);
                      return (
                        <td key={role.key} className="px-1 py-1 text-center">
                          <button
                            type="button"
                            disabled={readOnly || saving}
                            aria-pressed={active}
                            aria-label={`${role.employer || role.title}: ${active ? "liczy się" : "nie liczy się"}`}
                            title={proof.evidence ? `„${proof.evidence}”` : proof.quote}
                            onClick={() => toggle(field, role.key)}
                            className={cn(
                              "h-6 w-8 rounded text-sm leading-none",
                              active
                                ? "bg-primary/10 font-semibold text-primary"
                                : "text-primary/70 hover:bg-primary/10",
                            )}
                          >
                            {active ? (proof.level === "implied" ? "◐" : "●") : "○"}
                          </button>
                        </td>
                      );
                    })}
                    <td
                      className={cn(
                        "whitespace-nowrap px-2 py-1 text-right font-medium",
                        value ? "text-foreground" : "text-warning-muted-foreground",
                      )}
                    >
                      {value
                        ? points
                          ? `${value} z ${field.years.max_points} pkt`
                          : value
                        : field.years.basis.length
                          ? "—"
                          : "dopytaj"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          {total?.value
            ? `Łączny staż ${total.value} — z dat ${total.years.basis.length} stanowisk, nakładki liczone raz.`
            : "Łączny staż liczy się z dat wszystkich stanowisk."}
        </p>
        {readOnly || !rows.length ? null : (
          <Button
            type="button"
            size="sm"
            loading={saving}
            disabled={saving || changed.length === 0}
            onClick={() =>
              void onSaveRoles(Object.fromEntries(changed.map((field) => [field.id, [...pickedOf(field)]])))
            }
          >
            {changed.length ? `Zapisz lata · ${changed.length}` : "Lata zapisane"}
          </Button>
        )}
      </div>
      {gaps.length ? (
        <div className="space-y-1.5 rounded-md border border-border px-2.5 py-2" aria-label="Do dopytania">
          <p className="text-xs font-medium text-foreground">
            Lat nie ma w CV · {gaps.length} — zapytaj na screeningu
          </p>
          <ul className="space-y-1">
            {gaps.map((field) => (
              <li key={field.id} className="flex gap-2 text-xs">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  disabled={readOnly || saving}
                  checked={asking.has(field.id)}
                  aria-label={field.row_label ?? field.label}
                  onChange={() => {
                    const next = new Set(asking);
                    if (next.has(field.id)) next.delete(field.id);
                    else next.add(field.id);
                    setAskPick(next);
                  }}
                />
                <span className="min-w-0 text-muted-foreground">
                  {field.years.question}
                  {field.years.ask ? (
                    <span className="ml-1 inline-flex items-center gap-0.5 text-success-muted-foreground">
                      <Check className="h-3 w-3" aria-hidden /> w ściądze
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          {readOnly ? null : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={saving || sameSet(askedIds, asking)}
              onClick={() => {
                void onAsk([...asking]);
                setAskPick(null);
              }}
            >
              <ListPlus className="h-4 w-4" aria-hidden />
              {sameSet(askedIds, asking) && askedIds.length
                ? `W ściądze screeningu · ${askedIds.length}`
                : `Dodaj do ściągi screeningu · ${asking.size}`}
            </Button>
          )}
        </div>
      ) : null}
    </section>
  );
}

export default ClientFormYearsGrid;
