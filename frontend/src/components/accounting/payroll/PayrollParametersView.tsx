"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useConfirmParameters,
  usePayrollParameters,
  useSaveCompany,
  useSaveParameters,
  useWithdrawParameters,
  type CompanyInput,
  type ParamVersion,
  type ParametersOverview,
  type PayrollCompany,
} from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "../AccountingShell";
import { datePl } from "../ledger-model";
import {
  changedParams,
  companyMissing,
  nextMonth,
  paramField,
  paramGroups,
  paramProblems,
  paramText,
  paramValue,
} from "./parameters-model";

const CONTROL = "h-8 w-full min-w-0 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const CHANGES_SHOWN = 6;

const VERSION_STATUS: Record<ParamVersion["status"], { label: string; tone: "warning" | "success" }> = {
  to_confirm: { label: "Do potwierdzenia", tone: "warning" },
  confirmed: { label: "Potwierdzone", tone: "success" },
};

/** „Parametry”: stawki ZUS, PIT, PPK i limity w wersjach od daty, dane płatnika. */
export function PayrollParametersView({ today }: { today: string }) {
  const overview = usePayrollParameters();
  if (overview.isError) return <QueryStateNotice state="error" onRetry={() => overview.refetch()} />;
  if (!overview.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie parametrów płac…</p>;
  const data = overview.data;
  const current = data.versions.find((version) => version.id === data.current_id) ?? null;
  return (
    <div className="space-y-3.5">
      <CurrentParameters data={data} current={current} today={today} />
      <div className="grid gap-3.5 xl:grid-cols-2">
        {data.company ? <CompanyCard company={data.company} /> : null}
        <VersionsCard data={data} />
      </div>
    </div>
  );
}

function CurrentParameters({
  data,
  current,
  today,
}: {
  data: ParametersOverview;
  current: ParamVersion | null;
  today: string;
}) {
  const { showToast } = useToast();
  const confirm = useConfirmParameters();
  const [adding, setAdding] = useState(false);
  const status = current ? VERSION_STATUS[current.status] : null;

  const doConfirm = (version: ParamVersion) =>
    confirm.mutate(version.id, {
      onSuccess: () => showToast(`Potwierdzono parametry od ${datePl(version.effective_from)}.`),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się potwierdzić parametrów."), "error"),
    });

  return (
    <SectionCard
      title={current ? `Parametry płac od ${datePl(current.effective_from)}` : "Parametry płac"}
      aside={status ? <StatusDot tone={status.tone}>{status.label}</StatusDot> : "brak wersji na dziś"}
    >
      {current?.status === "to_confirm" ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 bg-warning-muted px-3.5 py-2 text-[13px] text-warning-muted-foreground">
          <span className="min-w-0">
            Parametry czekają na potwierdzenie przez Rozliczenia — dopóki ich nie potwierdzisz, listy płac nie da się zatwierdzić.
            {current.note ? ` ${current.note}` : ""}
          </span>
          <Button size="sm" loading={confirm.isPending} onClick={() => doConfirm(current)}>
            Potwierdź
          </Button>
        </div>
      ) : current?.note ? (
        <p className="border-b border-border/70 px-3.5 py-2 text-[12.5px] text-muted-foreground">{current.note}</p>
      ) : null}
      {current ? (
        <div className="gap-x-8 px-3.5 py-2 xl:columns-2">
          {paramGroups(data.catalog).map((group) => (
            <div key={group.group} className="mb-3 break-inside-avoid">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">{group.group}</h3>
              <dl className="mt-1 divide-y divide-border/60">
                {group.items.map((item) => (
                  <div key={item.key} className="flex items-baseline justify-between gap-3 py-1 text-[13px]">
                    <dt className="min-w-0">{item.label}</dt>
                    <dd className="shrink-0 tabular-nums font-medium">{paramText(current.params[item.key], item.unit)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">
          Nie ma parametrów obowiązujących dziś — dodaj wersję, inaczej lista płac się nie policzy.
        </p>
      )}
      <div className="border-t border-border/70 px-3.5 py-3">
        {adding ? (
          <NewVersionForm data={data} current={current} today={today} onDone={() => setAdding(false)} />
        ) : (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            Nowa wersja od…
          </Button>
        )}
      </div>
    </SectionCard>
  );
}

function NewVersionForm({
  data,
  current,
  today,
  onDone,
}: {
  data: ParametersOverview;
  current: ParamVersion | null;
  today: string;
  onDone: () => void;
}) {
  const { showToast } = useToast();
  const save = useSaveParameters();
  const [month, setMonth] = useState(nextMonth(today));
  const [note, setNote] = useState("");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(data.catalog.map((item) => [item.key, paramField(current?.params[item.key])])),
  );
  const problems = paramProblems(data.catalog, values);
  const changed = changedParams(data.catalog, current?.params ?? {}, values);
  const monthOk = /^\d{4}-(0[1-9]|1[0-2])$/.test(month);

  const submit = () => {
    if (problems.length || !monthOk) return;
    save.mutate(
      {
        effective_from: `${month}-01`,
        params: Object.fromEntries(data.catalog.map((item) => [item.key, paramValue(values[item.key] ?? "")])),
        note: note.trim() || null,
      },
      {
        onSuccess: () => {
          showToast(`Zapisano parametry od ${datePl(`${month}-01`)} — czekają na potwierdzenie.`);
          onDone();
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać parametrów."), "error"),
      },
    );
  };

  return (
    <div className="space-y-3 text-[13px]">
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1">
          <span className="font-medium">Obowiązuje od</span>
          <input
            type="month"
            aria-label="Nowa wersja od"
            className={cn(CONTROL, "w-44")}
            value={month}
            onChange={(event) => setMonth(event.target.value)}
          />
        </label>
        <label className="grid min-w-0 flex-1 gap-1">
          <span className="font-medium">Uwaga</span>
          <input
            aria-label="Uwaga do wersji"
            className={cn(CONTROL, "w-full")}
            maxLength={500}
            placeholder="np. stopa wypadkowa z zawiadomienia ZUS"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
      </div>
      <p className="text-[12px] text-muted-foreground">
        Wersja obowiązuje od pierwszego dnia miesiąca; lista płac bierze wersję z dnia wypłaty. Wersja z tą samą datą
        zastępuje poprzednią, jeśli nie policzyła zatwierdzonej listy. Nowa wersja czeka na potwierdzenie.
      </p>
      <div className="gap-x-8 xl:columns-2">
        {paramGroups(data.catalog).map((group) => (
          <fieldset key={group.group} className="mb-3 min-w-0 break-inside-avoid">
            <legend className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              {group.group}
            </legend>
            <div className="mt-1 space-y-1">
              {group.items.map((item) => {
                const differs = Number(current?.params[item.key]) !== Number(paramValue(values[item.key] ?? ""));
                return (
                  <label key={item.key} className="grid grid-cols-[minmax(0,1fr)_7.5rem_2rem] items-center gap-2">
                    <span className={cn("min-w-0", differs && "font-medium text-primary")}>{item.label}</span>
                    <input
                      aria-label={item.label}
                      inputMode="decimal"
                      className={cn(CONTROL, "text-right tabular-nums")}
                      value={values[item.key] ?? ""}
                      onChange={(event) => setValues((state) => ({ ...state, [item.key]: event.target.value }))}
                    />
                    <span className="text-[12px] text-muted-foreground">{item.unit}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>
      {problems.length ? (
        <ul className="space-y-0.5 text-[12px] text-destructive">
          {problems.slice(0, 4).map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
          {problems.length > 4 ? <li>i jeszcze {problems.length - 4}</li> : null}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={problems.length > 0 || !monthOk} loading={save.isPending} onClick={submit}>
          Zapisz wersję
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <span className="text-[12px] text-muted-foreground">
          {current ? `Zmiany względem obecnej wersji: ${changed.length}` : "Pierwsza wersja parametrów"}
        </span>
      </div>
    </div>
  );
}

function VersionsCard({ data }: { data: ParametersOverview }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const confirm = useConfirmParameters();
  const withdraw = useWithdrawParameters();
  const units = Object.fromEntries(data.catalog.map((item) => [item.key, item.unit]));

  const doWithdraw = async (version: ParamVersion) => {
    const ok = await askConfirm({
      title: `Wycofać parametry od ${datePl(version.effective_from)}?`,
      description:
        "Listy płac wezmą wtedy wcześniejszą wersję. Wersji użytej przez zatwierdzoną listę wycofać się nie da.",
      confirmLabel: "Wycofaj",
      variant: "destructive",
    });
    if (!ok) return;
    withdraw.mutate(version.id, {
      onSuccess: () => showToast(`Wycofano parametry od ${datePl(version.effective_from)}.`),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się wycofać parametrów."), "error"),
    });
  };

  return (
    <SectionCard title="Historia wersji" aside="najnowsze najpierw">
      {data.versions.length ? (
        <ul>
          {data.versions.map((version) => {
            const status = VERSION_STATUS[version.status];
            const shown = version.changes.slice(0, CHANGES_SHOWN);
            return (
              <li key={version.id} className={cn(CALM_ROW, "space-y-1 px-3.5 py-2 last:border-0", !version.live && "opacity-70")}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <span className="text-[13px] font-medium">od {datePl(version.effective_from)}</span>
                    <span className={CALM_SUBLINE}>
                      {version.source === "seed" ? "zasiew z ustaw i obwieszczeń" : "wpisana w NEXUSIE"}
                      {version.created_at ? ` · ${datePl(version.created_at)}` : ""}
                      {version.in_use ? " · użyta na zatwierdzonej liście" : ""}
                      {version.id === data.current_id ? " · obowiązuje dziś" : ""}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {version.live ? (
                      <StatusDot tone={status.tone}>{status.label}</StatusDot>
                    ) : (
                      <StatusDot tone="neutral">wycofana {datePl(version.replaced_at)}</StatusDot>
                    )}
                    {version.live && version.status === "to_confirm" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={confirm.isPending}
                        onClick={() =>
                          confirm.mutate(version.id, {
                            onSuccess: () => showToast(`Potwierdzono parametry od ${datePl(version.effective_from)}.`),
                            onError: (error) =>
                              showToast(apiErrorMessage(error, "Nie udało się potwierdzić parametrów."), "error"),
                          })
                        }
                      >
                        Potwierdź
                      </Button>
                    ) : null}
                    {version.live && !version.in_use ? (
                      <Button size="sm" variant="quiet" disabled={withdraw.isPending} onClick={() => void doWithdraw(version)}>
                        Wycofaj
                      </Button>
                    ) : null}
                  </div>
                </div>
                {version.note ? <p className="text-[12.5px] text-muted-foreground">{version.note}</p> : null}
                {version.changes.length ? (
                  <ul className="space-y-0.5 text-[12.5px]">
                    {shown.map((change) => (
                      <li key={change.key} className="flex flex-wrap gap-x-1.5">
                        <span className="text-muted-foreground">{change.label}:</span>
                        <span className="tabular-nums">
                          {change.before ? paramText(change.before, units[change.key] ?? change.unit) : "—"} →{" "}
                          {change.after ? paramText(change.after, units[change.key] ?? change.unit) : "—"}
                        </span>
                      </li>
                    ))}
                    {version.changes.length > CHANGES_SHOWN ? (
                      <li className="text-muted-foreground">i jeszcze {version.changes.length - CHANGES_SHOWN}</li>
                    ) : null}
                  </ul>
                ) : (
                  <p className="text-[12.5px] text-muted-foreground">Pierwsza wersja — bez zmian do porównania.</p>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">Nie ma jeszcze wersji parametrów.</p>
      )}
      {confirmDialog}
    </SectionCard>
  );
}

const COMPANY_FIELDS: { key: keyof CompanyInput; label: string; hint: string; placeholder: string }[] = [
  { key: "regon", label: "REGON", hint: "9 albo 14 cyfr — do KEDU", placeholder: "9 cyfr" },
  { key: "short_name", label: "Nazwa skrócona", hint: "do ZUS, najwyżej 31 znaków", placeholder: "nazwa skrócona" },
  { key: "tax_office_code", label: "Kod urzędu skarbowego płatnika", hint: "4 cyfry — do PIT-4R, PIT-8AR, PIT-11", placeholder: "4 cyfry" },
  { key: "zus_account", label: "Rachunek składkowy ZUS (NRS)", hint: "do przelewu składek", placeholder: "26 cyfr" },
  { key: "tax_account", label: "Mikrorachunek podatkowy", hint: "do przelewu PIT-4 i PIT-8AR", placeholder: "26 cyfr" },
];

function companyValues(company: PayrollCompany): Record<keyof CompanyInput, string> {
  return {
    regon: company.regon ?? "",
    short_name: company.short_name ?? "",
    tax_office_code: company.tax_office_code ?? "",
    zus_account: company.zus_account ?? "",
    tax_account: company.tax_account ?? "",
  };
}

function CompanyCard({ company }: { company: PayrollCompany }) {
  const { showToast } = useToast();
  const save = useSaveCompany();
  const [values, setValues] = useState(() => companyValues(company));
  useEffect(() => setValues(companyValues(company)), [company]);
  const saved = companyValues(company);
  const dirty = COMPANY_FIELDS.some((field) => values[field.key].trim() !== saved[field.key]);
  const missing = companyMissing(company);

  const submit = () =>
    save.mutate(
      Object.fromEntries(COMPANY_FIELDS.map((field) => [field.key, values[field.key].trim() || null])) as unknown as CompanyInput,
      {
        onSuccess: () => showToast("Zapisano dane płatnika."),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać danych płatnika."), "error"),
      },
    );

  return (
    <SectionCard title="Dane płatnika" aside={`NIP ${company.nip}`}>
      <div className="space-y-2.5 px-3.5 py-3 text-[13px]">
        <p className="text-muted-foreground">{company.name}</p>
        {missing ? (
          <p className="rounded-md bg-warning-muted px-3 py-2 text-warning-muted-foreground">
            Brakuje: {missing} — bez tego nie powstanie KEDU ani PIT.
          </p>
        ) : null}
        {COMPANY_FIELDS.map((field) => (
          <label key={field.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,15rem)] items-center gap-x-3 gap-y-0.5">
            <span className="min-w-0">
              <span className="block font-medium">{field.label}</span>
              <span className={CALM_SUBLINE}>{field.hint}</span>
            </span>
            <input
              aria-label={field.label}
              className={cn(CONTROL, "tabular-nums")}
              placeholder={field.placeholder}
              value={values[field.key]}
              onChange={(event) => setValues((state) => ({ ...state, [field.key]: event.target.value }))}
            />
          </label>
        ))}
        <div className="flex justify-end pt-1">
          <Button size="sm" disabled={!dirty} loading={save.isPending} onClick={submit}>
            Zapisz dane płatnika
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
