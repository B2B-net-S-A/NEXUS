"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  HR_MODULE_LABELS,
  useAddDayOff,
  useCompanyDaysOff,
  useAvailabilitySource,
  useRemoveDayOff,
  useSetAvailabilitySource,
  useSetHrModules,
  type HrConfig,
  type HrModuleKey,
} from "@/lib/api/hr";
import { formatIsoDatePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { LifecycleTemplatesCard } from "@/components/hr/lifecycle/LifecycleTemplatesCard";

import { M365Card } from "./M365Card";
import { canEditPayrollSettings } from "./PayrollSettings";

function warsawYear(): number {
  return Number(
    new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw", year: "numeric" }).format(
      new Date(),
    ),
  );
}

function DaysOffCard() {
  const { showToast } = useToast();
  const [year, setYear] = useState(warsawYear);
  const days = useCompanyDaysOff(year);
  const add = useAddDayOff();
  const remove = useRemoveDayOff();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [day, setDay] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const state = resolveViewState({
    isLoading: days.isLoading,
    isError: days.isError,
    error: days.error,
    isSuccess: days.isSuccess,
    isEmpty: (days.data ?? []).length === 0,
  });

  const submit = () => {
    setError(null);
    if (!day || !name.trim()) {
      setError("Podaj datę i nazwę dnia wolnego.");
      return;
    }
    add.mutate(
      { day, name: name.trim(), kind: "company" },
      {
        onSuccess: () => {
          setDay("");
          setName("");
          showToast("Dzień wolny dodany", "success");
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się dodać dnia.")),
      },
    );
  };

  const removeDay = async (id: number, label: string) => {
    const ok = await askConfirm({
      title: "Usunąć dzień wolny?",
      description: `${label} wróci do dni roboczych w urlopach i timesheetach.`,
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(id, {
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się usunąć dnia."), "error"),
    });
  };

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Dni wolne firmy</h2>
          <p className="text-sm text-muted-foreground">
            Poza świętami ustawowymi (te NEXUS zna sam). Liczą się w urlopach,
            timesheetach i tempie celów.
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" aria-label="Poprzedni rok" onClick={() => setYear((y) => y - 1)}>
            ‹
          </Button>
          <span className="w-12 text-center text-sm font-medium tabular-nums">{year}</span>
          <Button variant="ghost" size="sm" aria-label="Następny rok" onClick={() => setYear((y) => y + 1)}>
            ›
          </Button>
        </div>
      </div>
      {state === "forbidden" || state === "error" || state === "not_found" ? (
        <QueryStateNotice state={state} onRetry={() => days.refetch()} />
      ) : state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">Brak dni wolnych w {year}.</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {(days.data ?? []).map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span>
                <span className="font-medium tabular-nums">{formatIsoDatePl(item.day)}</span>{" "}
                · {item.name}
              </span>
              <Button
                variant="quiet"
                size="sm"
                aria-label={`Usuń ${item.name}`}
                onClick={() => removeDay(item.id, `${formatIsoDatePl(item.day)} (${item.name})`)}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
        <FormField label="Data" htmlFor="hr-dayoff-date">
          <Input
            id="hr-dayoff-date"
            type="date"
            value={day}
            onChange={(event) => setDay(event.target.value)}
          />
        </FormField>
        <FormField label="Nazwa" htmlFor="hr-dayoff-name">
          <Input
            id="hr-dayoff-name"
            value={name}
            maxLength={120}
            placeholder="np. Dzień firmy"
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <Button
          className="justify-self-end sm:col-span-2"
          onClick={submit}
          disabled={add.isPending}
        >
          Dodaj dzień
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {confirmDialog}
    </Card>
  );
}

function ModulesCard({ config }: { config: HrConfig }) {
  const { showToast } = useToast();
  const save = useSetHrModules();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const keys = useMemo(() => Object.keys(HR_MODULE_LABELS) as HrModuleKey[], []);

  const source = useAvailabilitySource(config.me.is_admin);
  const setSource = useSetAvailabilitySource();

  const toggleSource = async (local: boolean) => {
    const ok = await askConfirm({
      title: local ? "Zastępstwa z urlopów NEXUSA?" : "Wrócić do urlopów z Compassa?",
      description: local
        ? "Zastępcy przejmą pracę osób na urlopie według wniosków z NEXUSA, a cele i dni pracy policzą się z tych urlopów. Przełącz dopiero po imporcie kartotek i urlopów z Compassa."
        : "Zastępstwa i dni pracy znów będą liczone z danych Compassa.",
      confirmLabel: local ? "Przełącz na NEXUS" : "Wróć do Compassa",
      variant: "default",
    });
    if (!ok) return;
    setSource.mutate(local ? "local" : "compass", {
      onSuccess: () => showToast("Źródło urlopów zmienione", "success"),
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się zmienić źródła urlopów."), "error"),
    });
  };

  const toggle = async (key: HrModuleKey, next: boolean) => {
    const ok = await askConfirm({
      title: next ? "Włączyć moduł dla wszystkich?" : "Wyłączyć moduł?",
      description: next
        ? `„${HR_MODULE_LABELS[key]}” zobaczą wszyscy uprawnieni. Wcześniej zaimportuj dane z Compassa i przełącz Compass w tryb tylko do odczytu.`
        : `„${HR_MODULE_LABELS[key]}” zniknie wszystkim poza administratorem. Dane zostają.`,
      confirmLabel: next ? "Włącz" : "Wyłącz",
      variant: next ? "default" : "destructive",
    });
    if (!ok) return;
    save.mutate(
      { [key]: next },
      {
        onSuccess: () => showToast(next ? "Moduł włączony" : "Moduł wyłączony", "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zmienić modułu."), "error"),
      },
    );
  };

  return (
    <Card className="space-y-3 p-5">
      <div>
        <h2 className="text-base font-semibold text-foreground">Moduły</h2>
        <p className="text-sm text-muted-foreground">
          Moduł wyłączony widzi tylko administrator. Włączaj według planu przełączenia
          z Compassa.
        </p>
      </div>
      <ul className="divide-y divide-border/60">
        {keys.map((key) => (
          <li key={key} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span>{HR_MODULE_LABELS[key]}</span>
            <Switch
              checked={config.modules[key]}
              disabled={save.isPending}
              aria-label={HR_MODULE_LABELS[key]}
              onCheckedChange={(next) => toggle(key, next)}
            />
          </li>
        ))}
        {source.isSuccess ? (
          <li className="flex items-center justify-between gap-3 py-2 text-sm">
            <span>
              Zastępstwa i dni pracy z urlopów NEXUSA
              <span className="block text-xs text-muted-foreground">
                {source.data === "local" ? "Teraz: NEXUS" : "Teraz: Compass"}
              </span>
            </span>
            <Switch
              checked={source.data === "local"}
              disabled={setSource.isPending}
              aria-label="Zastępstwa i dni pracy z urlopów NEXUSA"
              onCheckedChange={(next) => toggleSource(next)}
            />
          </li>
        ) : null}
      </ul>
      {confirmDialog}
    </Card>
  );
}

/**
 * Reguły premii mieszkają od 17.10.2026 w Ustawienia → Płace — Kadry, które
 * szukały ich tutaj, dostają drogowskaz (link tylko z uprawnieniem „Płace”).
 */
function BonusRulesMovedCard({ config }: { config: HrConfig }) {
  return (
    <Card className="space-y-1 p-5">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        Reguły premii
      </h2>
      {canEditPayrollSettings(config) ? (
        <p className="text-sm text-foreground">
          Reguły premii są w{" "}
          <Link href="/settings/payroll" className="font-medium text-primary hover:underline">
            Ustawienia → Płace
          </Link>
          .
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">
          Reguły premii są w Ustawienia → Płace — zmienia je osoba z uprawnieniem „Płace”.
        </p>
      )}
    </Card>
  );
}

/**
 * Ustawienia → Kadry: dni wolne firmy i szablony wejścia/odejścia (Kadry),
 * przełączniki modułów i źródło urlopów (admin), M365. Reguły premii są
 * w Ustawienia → Płace (`PayrollSettings`).
 */
export function HrSettings({ config }: { config: HrConfig }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {config.me.people_admin ? <DaysOffCard /> : null}
      {config.me.is_admin ? <ModulesCard config={config} /> : null}
      {config.open_modules.lifecycle &&
      (config.me.people_admin || config.me.is_admin || config.me.back_office_head) ? (
        <div className="lg:col-span-2">
          <LifecycleTemplatesCard config={config} />
        </div>
      ) : null}
      {config.open_modules.payroll ? <BonusRulesMovedCard config={config} /> : null}
      {config.me.people_admin ? (
        <div className="lg:col-span-2">
          <M365Card />
        </div>
      ) : null}
    </div>
  );
}
