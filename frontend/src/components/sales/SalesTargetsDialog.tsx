"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useSalesTargets,
  useSetCompanyTarget,
  useSetPersonTarget,
  type SalesPersonTarget,
  type SalesPersonTargetInput,
} from "@/lib/api/sales";

/**
 * Admin ustawia cele: firmowy (netto MRR z terminem) i tygodniowe per osoba
 * z „Sprzedaż: edycja” (spotkania, leady, wejścia na etap „Oferta wysłana”),
 * plus opcjonalny cel marży i drużyna. Kwot nie ma w kodzie — wpisuje admin.
 */
export function SalesTargetsDialog({ onClose }: { onClose: () => void }) {
  const targets = useSalesTargets();
  const setCompany = useSetCompanyTarget();
  const { showError, showSuccess } = useToast();
  const [goal, setGoal] = useState("");
  const [deadline, setDeadline] = useState("");

  useEffect(() => {
    if (!targets.data) return;
    setGoal(targets.data.company.net_mrr_goal ?? "");
    setDeadline(targets.data.company.goal_deadline ?? "");
  }, [targets.data]);

  const saveCompany = () =>
    setCompany.mutate(
      { net_mrr_goal: goal.trim() || null, goal_deadline: deadline || null },
      {
        onSuccess: () => showSuccess("Zapisano cel firmy."),
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać celu firmy.")),
      },
    );

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Cele sprzedaży"
      description="Cele tygodniowe liczą się dla każdego tygodnia w tabeli KPI. „Oferty (etap)” to firmy, których szansa weszła na etap „Oferta wysłana”."
      size="xl"
      footer={
        <Button variant="outline" onClick={onClose}>
          Zamknij
        </Button>
      }
    >
      {targets.isLoading ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : targets.isError ? (
        <p className="text-sm text-destructive">{apiErrorMessage(targets.error, "Nie udało się wczytać celów.")}</p>
      ) : targets.data ? (
        <div className="space-y-5">
          <section className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col text-xs text-muted-foreground">
              Cel firmy — netto MRR (zł)
              <Input
                className="mt-1 w-44"
                inputMode="decimal"
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                aria-label="Cel firmy — netto MRR"
              />
            </label>
            <label className="flex flex-col text-xs text-muted-foreground">
              Termin
              <Input
                className="mt-1 w-40"
                type="date"
                value={deadline}
                onChange={(event) => setDeadline(event.target.value)}
                aria-label="Termin celu firmy"
              />
            </label>
            <Button size="sm" onClick={saveCompany} disabled={setCompany.isPending}>
              Zapisz cel firmy
            </Button>
          </section>
          <section>
            <div className="hidden grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_4.5rem_8rem_7rem_9rem_5rem] gap-2 px-1 pb-1 text-[11px] font-medium text-muted-foreground lg:grid">
              <span>Osoba</span>
              <span>Spotkania</span>
              <span>Leady</span>
              <span>Oferty</span>
              <span>Drużyna</span>
              <span>Marża (zł)</span>
              <span>Termin marży</span>
              <span />
            </div>
            {targets.data.people.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nikt nie ma jeszcze uprawnienia „Sprzedaż: edycja”.</p>
            ) : (
              <ul className="divide-y divide-border">
                {targets.data.people.map((person) => (
                  <PersonTargetRow key={person.user_id} person={person} />
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : null}
    </AppModal>
  );
}

function toInput(person: SalesPersonTarget): SalesPersonTargetInput {
  return {
    meetings: person.meetings,
    qualified: person.qualified,
    offers_stage: person.offers_stage,
    team: person.team ?? "",
    margin_goal_amount: person.margin_goal_amount ?? "",
    margin_goal_deadline: person.margin_goal_deadline ?? "",
  };
}

function PersonTargetRow({ person }: { person: SalesPersonTarget }) {
  const save = useSetPersonTarget();
  const { showError, showSuccess } = useToast();
  const [form, setForm] = useState<SalesPersonTargetInput>(() => toInput(person));
  const count = (key: "meetings" | "qualified" | "offers_stage") => (
    <Input
      type="number"
      min={0}
      max={1000}
      className="h-8"
      value={form[key]}
      onChange={(event) => setForm((current) => ({ ...current, [key]: Math.max(0, Number(event.target.value) || 0) }))}
      aria-label={`${person.name}: ${key === "meetings" ? "spotkania" : key === "qualified" ? "leady" : "oferty (etap)"} na tydzień`}
    />
  );

  const submit = () =>
    save.mutate(
      {
        userId: person.user_id,
        ...form,
        team: form.team?.trim() || null,
        margin_goal_amount: form.margin_goal_amount?.toString().trim() || null,
        margin_goal_deadline: form.margin_goal_deadline || null,
      },
      {
        onSuccess: () => showSuccess(`Zapisano cele: ${person.name}.`),
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać celów.")),
      },
    );

  return (
    <li className="grid grid-cols-2 items-center gap-2 py-2 lg:grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_4.5rem_8rem_7rem_9rem_5rem]">
      <div className="col-span-2 min-w-0 text-sm lg:col-span-1">
        <p className="truncate font-medium text-foreground">{person.name}</p>
        <p className="text-[11px] text-muted-foreground">
          {person.has_targets ? "ma cele" : "bez celów"}
          {person.is_active ? "" : " · konto nieaktywne"}
        </p>
      </div>
      {count("meetings")}
      {count("qualified")}
      {count("offers_stage")}
      <Input
        className="h-8"
        maxLength={60}
        value={form.team ?? ""}
        onChange={(event) => setForm((current) => ({ ...current, team: event.target.value }))}
        aria-label={`${person.name}: drużyna`}
      />
      <Input
        className="h-8"
        inputMode="decimal"
        value={form.margin_goal_amount ?? ""}
        onChange={(event) => setForm((current) => ({ ...current, margin_goal_amount: event.target.value }))}
        aria-label={`${person.name}: cel marży netto MRR`}
      />
      <Input
        className="h-8"
        type="date"
        value={form.margin_goal_deadline ?? ""}
        onChange={(event) => setForm((current) => ({ ...current, margin_goal_deadline: event.target.value }))}
        aria-label={`${person.name}: termin celu marży`}
      />
      <Button size="sm" variant="outline" onClick={submit} disabled={save.isPending}>
        Zapisz
      </Button>
    </li>
  );
}
