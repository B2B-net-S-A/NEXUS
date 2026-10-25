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
  // Od Q4 2026 liga DL nie ma nagród — premie przychodzą tylko z kwartałów do Q3 2026.
  quarterly_champions_dl: "Liga Mistrzów DL (kwartały do Q3 2026, potem bez nagród)",
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

export interface BonusExample {
  tier: 1 | 2 | 3;
  recruiter: number;
  dl: number;
}

/**
 * Przykład „na żywo” z pól formularza (przed zapisem) — lustro
 * `services/hr/bonus_rules.recruiter_tier` i `dl_bonus`: marża ≤ I granicy =
 * próg I, poniżej II granicy = próg II, od II granicy = próg III; DL = marża/h
 * × godziny w miesiącu × procent. Zła liczba w polu albo marża = `null`.
 */
export function bonusExample(form: RulesForm, marginText: string): BonusExample | null {
  const margin = parseAmount(marginText);
  const values = [form.boundLow, form.boundHigh, form.tier1, form.tier2, form.tier3, form.dlPercent].map(
    parseAmount,
  );
  const hours = Number(form.monthlyHours);
  if (margin === null || values.some((value) => value === null) || !Number.isFinite(hours)) return null;
  const [low, high, t1, t2, t3, percent] = (values as string[]).map(Number);
  const m = Number(margin);
  const tier = m <= low ? 1 : m < high ? 2 : 3;
  const dl = Math.round(m * hours * percent) / 100;
  return { tier, recruiter: [t1, t2, t3][tier - 1], dl };
}

const formatPln = (value: number) => {
  const digits = Number.isInteger(value) ? 0 : 2;
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits })} zł`;
};

function RulesEditor({ rules }: { rules: BonusRules }) {
  const { showToast } = useToast();
  const save = useSaveBonusRules();
  const refresh = useRefreshProposals();
  const people = usePeople();
  const [form, setForm] = useState<RulesForm>(() => formFromRules(rules));
  // Stan z serwera, z którym porównujemy formularz — pasek zapisu tylko przy zmianach.
  const [baseline, setBaseline] = useState<RulesForm>(() => formFromRules(rules));
  const [exampleMargin, setExampleMargin] = useState("");
  const dirty = JSON.stringify(form) !== JSON.stringify(baseline);
  const example = bonusExample(form, exampleMargin);
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
        setBaseline(formFromRules(saved));
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

  const input = (key: TextKey, label: string, id: string, className = "w-24") => (
    <Input
      id={id}
      aria-label={label}
      inputMode="decimal"
      value={form[key]}
      onChange={(event) => set(key, event.target.value)}
      className={className}
    />
  );

  const refreshProposals = () =>
    refresh.mutate(undefined, {
      onSuccess: (counts) =>
        showToast(
          `Propozycje przeliczone: nowe ${(counts.placement_created ?? 0) + (counts.league_created ?? 0)}`,
          "success",
        ),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przeliczyć propozycji."), "error"),
    });

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px] xl:items-start">
      <div className="space-y-5">
      {/* Progi jako „marża od → premia” (makieta rundy 2, 21.10.2026), zamiast pięciu pól w rzędzie. */}
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-foreground">Premia rekrutera z placementu</legend>
        <table className="w-full max-w-md text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3 font-medium">Marża (zł/h)</th>
              <th className="py-1 font-medium">Premia</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="py-1 pr-3">
                <span className="mr-2 text-muted-foreground">do</span>
                {input("boundLow", "Próg I do (zł/h)", "rules-bound-low")}
              </td>
              <td className="py-1">{input("tier1", "Premia progu I", "rules-tier1", "w-28")}</td>
            </tr>
            <tr>
              <td className="py-1 pr-3 text-muted-foreground">
                powyżej {form.boundLow || "…"}, poniżej {form.boundHigh || "…"}
              </td>
              <td className="py-1">{input("tier2", "Premia progu II", "rules-tier2", "w-28")}</td>
            </tr>
            <tr>
              <td className="py-1 pr-3">
                <span className="mr-2 text-muted-foreground">od</span>
                {input("boundHigh", "Próg III od (zł/h)", "rules-bound-high")}
              </td>
              <td className="py-1">{input("tier3", "Premia progu III", "rules-tier3", "w-28")}</td>
            </tr>
          </tbody>
        </table>
      </fieldset>
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

      </div>
      <aside className="space-y-3 rounded-lg border border-border bg-muted/30 p-4" aria-label="Przykład">
        <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Na przykładzie
        </p>
        <FormField label="Marża konsultanta (zł/h)" htmlFor="rules-example-margin">
          <Input
            id="rules-example-margin"
            inputMode="decimal"
            placeholder="np. 46"
            value={exampleMargin}
            onChange={(event) => setExampleMargin(event.target.value)}
          />
        </FormField>
        {example ? (
          <p className="text-sm text-foreground" data-testid="rules-example">
            Próg {["I", "II", "III"][example.tier - 1]}: rekruter dostaje{" "}
            <strong>{formatPln(example.recruiter)}</strong>, Delivery Lead{" "}
            <strong>{formatPln(example.dl)}</strong> — po {form.businessDays || "…"} dniach roboczych.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Wpisz marżę, a przykład policzy się z pól obok — jeszcze przed zapisem.
          </p>
        )}
        <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={refreshProposals}>
          {refresh.isPending ? "Przeliczanie…" : "Przelicz propozycje teraz"}
        </Button>
      </aside>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {dirty || save.isPending ? (
        <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-4 py-2 shadow-sm">
          <span className="flex-1 text-sm text-warning-muted-foreground">Niezapisane zmiany w regułach</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setForm(baseline);
              setError(null);
            }}
          >
            Cofnij
          </Button>
          <Button size="sm" onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz reguły"}
          </Button>
        </div>
      ) : null}
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
