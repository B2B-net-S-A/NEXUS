"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { usePeople } from "@/lib/api/hr";
import {
  useBonusRules,
  useRefreshProposals,
  useSaveBonusRules,
  type BonusRules,
  type ExtraDlRule,
} from "@/lib/api/hr-payroll";
import { resolveViewState } from "@/lib/view-state";

import { parseAmount } from "./payroll-format";

export const LEAGUE_TYPE_LABELS: Record<string, string> = {
  quarterly_champions_dl: "Liga Mistrzów DL (kwartał)",
  quarterly_champions_recruiter: "Liga Mistrzów rekruterów (kwartał)",
  monthly_recommendations: "Wyścig rekomendacji (miesiąc, voucher)",
  monthly_placements: "Wyścig placementów (miesiąc, voucher)",
};

interface RulesForm {
  boundLow: string;
  boundHigh: string;
  tier1: string;
  tier2: string;
  tier3: string;
  dlPercent: string;
  monthlyHours: string;
  businessDays: string;
  since: string;
  leagueTypes: string[];
  extraDl: ExtraDlRule[];
}

type TextKey = {
  [K in keyof RulesForm]: RulesForm[K] extends string ? K : never;
}[keyof RulesForm];

const plain = (value: string) => String(Number(value)).replace(".", ",");

export function formFromRules(rules: BonusRules): RulesForm {
  return {
    boundLow: plain(rules.recruiter_tier_bounds[0]),
    boundHigh: plain(rules.recruiter_tier_bounds[1]),
    tier1: plain(rules.recruiter_tier_amounts[0]),
    tier2: plain(rules.recruiter_tier_amounts[1]),
    tier3: plain(rules.recruiter_tier_amounts[2]),
    dlPercent: plain(rules.dl_percent),
    monthlyHours: String(rules.monthly_hours),
    businessDays: String(rules.eligible_business_days),
    since: rules.automation_since ?? "",
    leagueTypes: rules.league_types,
    extraDl: rules.extra_dl,
  };
}

/** Formularz → treść `PUT /api/hr/payroll/rules`; zdanie błędu, gdy liczba jest zła. */
export function rulesPayload(
  form: RulesForm,
): { ok: true; payload: Partial<Omit<BonusRules, "currency">> } | { ok: false; error: string } {
  const numbers = [form.boundLow, form.boundHigh, form.tier1, form.tier2, form.tier3, form.dlPercent].map(
    parseAmount,
  );
  if (numbers.some((value) => value === null)) {
    return { ok: false, error: "Progi, kwoty i procent podaj jako liczby (np. 40 albo 12,5)." };
  }
  const [low, high, t1, t2, t3, percent] = numbers as string[];
  if (Number(low) >= Number(high)) {
    return { ok: false, error: "Druga granica marży musi być większa od pierwszej." };
  }
  const hours = Number(form.monthlyHours);
  const days = Number(form.businessDays);
  if (!Number.isInteger(hours) || hours < 1 || !Number.isInteger(days) || days < 1) {
    return { ok: false, error: "Godziny w miesiącu i dni robocze to liczby całkowite większe od zera." };
  }
  return {
    ok: true,
    payload: {
      recruiter_tier_bounds: [low, high],
      recruiter_tier_amounts: [t1, t2, t3],
      dl_percent: percent,
      monthly_hours: hours,
      eligible_business_days: days,
      automation_since: form.since || null,
      league_types: form.leagueTypes,
      extra_dl: form.extraDl.map(({ dl_user_id, recipient_user_id }) => ({
        dl_user_id,
        recipient_user_id,
      })),
    },
  };
}

function RulesEditor({ rules }: { rules: BonusRules }) {
  const { showToast } = useToast();
  const save = useSaveBonusRules();
  const refresh = useRefreshProposals();
  const people = usePeople();
  const [form, setForm] = useState<RulesForm>(() => formFromRules(rules));
  const [error, setError] = useState<string | null>(null);
  const [newDl, setNewDl] = useState("");
  const [newRecipient, setNewRecipient] = useState("");
  const directory = people.data?.items ?? [];
  const nameOf = (id: number, fallback?: string | null) =>
    directory.find((person) => person.user_id === id)?.name ?? fallback ?? `Osoba ${id}`;

  const set = <K extends keyof RulesForm>(key: K, value: RulesForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = () => {
    setError(null);
    const result = rulesPayload(form);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    save.mutate(result.payload, {
      onSuccess: (saved) => {
        setForm(formFromRules(saved));
        showToast("Reguły premii zapisane", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać reguł.")),
    });
  };

  const addExtra = () => {
    if (!newDl || !newRecipient || newDl === newRecipient) {
      setError("Wybierz Delivery Leada i inną osobę, która dostaje dodatkową premię.");
      return;
    }
    if (form.extraDl.some((rule) => rule.dl_user_id === Number(newDl))) {
      setError("Ten Delivery Lead ma już regułę.");
      return;
    }
    setError(null);
    set("extraDl", [
      ...form.extraDl,
      { dl_user_id: Number(newDl), recipient_user_id: Number(newRecipient) },
    ]);
    setNewDl("");
    setNewRecipient("");
  };

  const field = (key: TextKey, label: string, id: string, description?: string) => (
    <FormField label={label} htmlFor={id} description={description}>
      <Input
        id={id}
        inputMode="decimal"
        value={form[key]}
        onChange={(event) => set(key, event.target.value)}
      />
    </FormField>
  );

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {field("boundLow", "Próg I do (zł/h)", "rules-bound-low", "Marża ≤ tej kwoty.")}
        {field("boundHigh", "Próg III od (zł/h)", "rules-bound-high", "Między = próg II.")}
        {field("tier1", "Premia progu I", "rules-tier1")}
        {field("tier2", "Premia progu II", "rules-tier2")}
        {field("tier3", "Premia progu III", "rules-tier3")}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {field("dlPercent", "Premia DL (% marży)", "rules-dl-percent")}
        {field("monthlyHours", "Godzin w miesiącu", "rules-hours", "Marża/h × tyle godzin.")}
        {field("businessDays", "Dni robocze do terminu", "rules-days", "Start + tyle dni roboczych.")}
        <FormField
          label="Automat od daty startu"
          htmlFor="rules-since"
          description="Puste = ostatnie 120 dni."
        >
          <Input
            id="rules-since"
            type="date"
            value={form.since}
            onChange={(event) => set("since", event.target.value)}
          />
        </FormField>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-foreground">Premie z Ligi</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {Object.entries(LEAGUE_TYPE_LABELS).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-sm text-foreground">
              <Checkbox
                checked={form.leagueTypes.includes(key)}
                onCheckedChange={(checked) =>
                  set(
                    "leagueTypes",
                    checked
                      ? [...form.leagueTypes, key]
                      : form.leagueTypes.filter((value) => value !== key),
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-foreground">Dodatkowa premia DL</legend>
        <p className="text-xs text-muted-foreground">
          Gdy placement prowadzi wskazany Delivery Lead, druga osoba dostaje propozycję premii
          w tej samej kwocie co DL.
        </p>
        {form.extraDl.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak reguł.</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {form.extraDl.map((rule) => (
              <li
                key={rule.dl_user_id}
                className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <span className="text-foreground">
                  {nameOf(rule.dl_user_id, rule.dl_name)} →{" "}
                  {nameOf(rule.recipient_user_id, rule.recipient_name)}
                </span>
                <Button
                  size="icon-sm"
                  variant="quiet"
                  aria-label="Usuń regułę"
                  onClick={() =>
                    set(
                      "extraDl",
                      form.extraDl.filter((item) => item.dl_user_id !== rule.dl_user_id),
                    )
                  }
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-end gap-2">
          {(
            [
              ["rules-extra-dl", "Delivery Lead", newDl, setNewDl],
              ["rules-extra-recipient", "Dostaje dodatkową premię", newRecipient, setNewRecipient],
            ] as const
          ).map(([id, label, value, onChange]) => (
            <FormField key={id} label={label} htmlFor={id} className="min-w-[220px]">
              <Select value={value} onValueChange={onChange}>
                <SelectTrigger id={id}>
                  <SelectValue placeholder="Wybierz osobę" />
                </SelectTrigger>
                <SelectContent>
                  {directory.map((person) => (
                    <SelectItem key={person.user_id} value={String(person.user_id)}>
                      {person.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          ))}
          <Button variant="secondary" onClick={addExtra}>
            Dodaj regułę
          </Button>
        </div>
      </fieldset>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Zapisywanie…" : "Zapisz reguły"}
        </Button>
        <Button
          variant="ghost"
          disabled={refresh.isPending}
          onClick={() =>
            refresh.mutate(undefined, {
              onSuccess: (counts) =>
                showToast(
                  `Propozycje przeliczone: nowe ${
                    (counts.placement_created ?? 0) + (counts.league_created ?? 0)
                  }`,
                  "success",
                ),
              onError: (err) =>
                showToast(apiErrorMessage(err, "Nie udało się przeliczyć propozycji."), "error"),
            })
          }
        >
          {refresh.isPending ? "Przeliczanie…" : "Przelicz propozycje teraz"}
        </Button>
      </div>
    </div>
  );
}

/**
 * Ustawienia → Płace: reguły premii z placementów i z Ligi (Płace albo admin).
 * Wartości domyślne to reguły Compassa; osoby wskazuje się tu, nie w kodzie.
 */
export function BonusRulesCard() {
  const rules = useBonusRules();
  const state = resolveViewState({
    isLoading: rules.isLoading,
    isError: rules.isError,
    error: rules.error,
    isSuccess: rules.isSuccess,
  });
  if (state === "forbidden" || state === "not_found") return null;
  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Reguły premii
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Placement to kontrakt NEXUSA: termin premii = start + dni robocze, premia DL = procent
          marży/h × godziny, premia rekrutera według progu marży. Automat proponuje, Płace
          zatwierdzają.
        </p>
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie reguł…</p>
      ) : state === "error" || !rules.data ? (
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          Nie udało się wczytać reguł.
          <Button size="sm" variant="ghost" onClick={() => rules.refetch()}>
            Spróbuj ponownie
          </Button>
        </div>
      ) : (
        <RulesEditor rules={rules.data} />
      )}
    </Card>
  );
}
