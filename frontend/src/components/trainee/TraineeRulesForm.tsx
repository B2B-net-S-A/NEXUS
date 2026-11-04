"use client";

import { useEffect, useMemo, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useSaveTraineeRules,
  useTraineeRules,
  useTraineeRulesPreview,
  type TraineeRules,
} from "@/lib/api/trainee";
import {
  draftFromRules,
  rulesFromDraft,
  type BoolRuleKey,
  type NumberRuleKey,
  type TraineeRulesDraft,
} from "@/lib/trainee-panel";

const NUMBER = new Intl.NumberFormat("pl-PL");

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

interface RuleInputProps {
  name: NumberRuleKey;
  label: string;
  draft: TraineeRulesDraft;
  error: string | undefined;
  onChange: (name: NumberRuleKey, value: string) => void;
}

/** Liczba wpisana w zdanie („Pasuje do co najmniej [2] rekrutacji…”). */
function RuleInput({ name, label, draft, error, onChange }: RuleInputProps) {
  return (
    <>
      <input
        type="text"
        inputMode="numeric"
        aria-label={label}
        aria-invalid={error ? true : undefined}
        title={error}
        value={draft[name]}
        onChange={(e) => onChange(name, e.target.value)}
        className="mx-1 inline-block h-10 w-16 rounded-lg border border-border bg-card px-2 text-center text-sm tabular-nums text-foreground focus:border-primary focus:outline-hidden aria-[invalid=true]:border-destructive"
      />
      {error ? <span className="sr-only">{error}</span> : null}
    </>
  );
}

function RuleCheck({
  name,
  draft,
  onChange,
  children,
}: {
  name: BoolRuleKey;
  draft: TraineeRulesDraft;
  onChange: (name: BoolRuleKey, value: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex min-h-11 items-start gap-3 text-sm text-foreground">
      <input
        type="checkbox"
        checked={draft[name]}
        onChange={(e) => onChange(name, e.target.checked)}
        className="mt-1 h-4 w-4 shrink-0 rounded border-border accent-[hsl(var(--primary))]"
      />
      <span className="leading-relaxed">{children}</span>
    </label>
  );
}

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex gap-3 rounded-xl border border-border bg-card p-4">
      <span
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary"
        aria-hidden
      >
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {children}
      </div>
    </section>
  );
}

function RulesEditor({ saved }: { saved: TraineeRules }) {
  const [draft, setDraft] = useState<TraineeRulesDraft>(() => draftFromRules(saved));
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = useSaveTraineeRules();
  const { rules, errors } = useMemo(() => rulesFromDraft(draft), [draft]);
  // Każdy podgląd to świeże liczenie puli (~kilka–kilkanaście s CPU po stronie
  // serwera). 1,5 s zamiast 0,5 s, bo pisanie liczby cyfra po cyfrze wysyłało
  // podgląd dla każdej cyfry (runda 6 audytu).
  const previewRules = useDebounced(rules, 1500);
  const preview = useTraineeRulesPreview(previewRules);

  const setNumber = (name: NumberRuleKey, value: string) => {
    setMessage(null);
    setDraft((d) => ({ ...d, [name]: value }));
  };
  const setBool = (name: BoolRuleKey, value: boolean) => {
    setMessage(null);
    setDraft((d) => ({ ...d, [name]: value }));
  };
  const input = (name: NumberRuleKey, label: string) => (
    <RuleInput name={name} label={label} draft={draft} error={errors[name]} onChange={setNumber} />
  );
  const errorList = Object.values(errors);
  const max = Math.max(1, ...(preview.data?.by_category.map((c) => c.count) ?? [1]));

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          Kandydat musi spełnić wszystkie trzy warunki.
        </p>
        <Step n={1} title="Jest na niego popyt">
          <p className="text-sm leading-loose text-foreground">
            Pasuje do co najmniej {input("min_fits", "Minimalna liczba rekrutacji")} rekrutacji z
            ostatnich {input("window_months", "Okno w miesiącach")} miesięcy
          </p>
          <p className="text-xs text-muted-foreground">
            „Pasuje” = ta sama kategoria kompetencji i pokrycie must-have, ta sama miara co
            w „Podobnych rekrutacjach”.
          </p>
        </Step>

        <Step n={2} title="Brakuje o nim danych">
          <div className="flex flex-col">
            <RuleCheck name="missing_rate" draft={draft} onChange={setBool}>
              brak minimalnej stawki albo starsza niż{" "}
              {input("rate_stale_months", "Stawka nieaktualna po miesiącach")} miesięcy
            </RuleCheck>
            <RuleCheck name="missing_availability" draft={draft} onChange={setBool}>
              brak dostępności
            </RuleCheck>
            <RuleCheck name="missing_work_mode" draft={draft} onChange={setBool}>
              brak trybu pracy
            </RuleCheck>
            <RuleCheck name="missing_consents" draft={draft} onChange={setBool}>
              brak odpowiedzi „dzwonić poniżej stawki / przy większej liczbie dni w biurze”
            </RuleCheck>
            <RuleCheck name="missing_b2b" draft={draft} onChange={setBool}>
              nie wiemy, czy pracuje na B2B albo przejdzie na B2B
            </RuleCheck>
            <RuleCheck name="missing_work_time" draft={draft} onChange={setBool}>
              nie wiemy, czy chce full-time, czy też part-time
            </RuleCheck>
          </div>
          <p className="text-xs leading-loose text-muted-foreground">
            Wystarczy jeden brak. Osoby zweryfikowane telefonicznie w ostatnich{" "}
            {input("verified_recently_days", "Karencja po weryfikacji w dniach")} dniach nigdy nie
            trafiają na listę.
          </p>
        </Step>

        <Step n={3} title="Telefon nikomu nie zaszkodzi">
          <ul className="flex flex-col gap-2 text-sm leading-loose text-foreground">
            <li>
              nie jest w procesie z ruchem w ostatnich{" "}
              {input("process_active_days", "Proces aktywny w dniach")} dniach
            </li>
            <li>
              nie ma go w „Moich ludziach” rekrutera z kontaktem w ostatnich{" "}
              {input("my_people_contact_days", "Kontakt rekrutera w dniach")} dniach
            </li>
            <li>
              nikt z praktykantów nie dzwonił w ostatnich{" "}
              {input("trainee_recall_days", "Przerwa między telefonami praktykantów w dniach")} dniach
            </li>
          </ul>
          <p className="text-xs text-muted-foreground">
            Zawsze: ma telefon, nie pracuje u nas, nie jest na czarnej liście, nie prosił o brak
            kontaktu, nie odpowiedział „tylko etat”.
          </p>
        </Step>

        {errorList.length > 0 ? (
          <p role="alert" className="text-sm text-destructive">
            Popraw pola zaznaczone na czerwono: liczby całkowite, „pasuje do” i okna — co najmniej 1.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {message ? (
          <p role="status" className="text-sm text-success-muted-foreground">
            {message}
          </p>
        ) : null}
        <div>
          <Button
            size="lg"
            className="min-h-11"
            disabled={!rules || save.isPending}
            loading={save.isPending}
            onClick={() => {
              if (!rules) return;
              setError(null);
              save.mutate(rules, {
                onSuccess: () => setMessage("Zapisano. Nowe reguły obowiązują od najbliższej listy."),
                onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać reguł.")),
              });
            }}
          >
            Zapisz reguły
          </Button>
        </div>
      </div>

      <aside aria-label="Podgląd na dziś" className="flex flex-col gap-3 self-start rounded-xl border border-border bg-card p-4">
        <h2 className="text-sm font-semibold text-foreground">Podgląd na dziś</h2>
        {preview.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">
            Nie udało się policzyć podglądu.
            <Button variant="outline" size="sm" onClick={() => preview.refetch()}>
              Ponów
            </Button>
          </div>
        ) : preview.data ? (
          <>
            <div>
              <span className="text-3xl font-bold tabular-nums text-foreground">
                {NUMBER.format(preview.data.size)}
              </span>
              <p className="text-sm text-muted-foreground">
                osób spełnia reguły · {NUMBER.format(preview.data.open_fit)} pasuje do otwartych
                rekrutacji
              </p>
            </div>
            <ul className="flex flex-col gap-2">
              {preview.data.by_category.map((c) => (
                <li key={c.name} className="flex flex-col gap-1 text-sm">
                  <span className="flex justify-between gap-2">
                    <span className="text-muted-foreground">{c.name}</span>
                    <span className="tabular-nums text-foreground">{NUMBER.format(c.count)}</span>
                  </span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                    <span
                      className="block h-full rounded-full bg-primary"
                      style={{ width: `${Math.round((c.count / max) * 100)}%` }}
                    />
                  </span>
                </li>
              ))}
            </ul>
            {preview.isFetching ? (
              <p className="text-xs text-muted-foreground" role="status">
                Przeliczam…
              </p>
            ) : null}
          </>
        ) : rules ? (
          <p className="text-sm text-muted-foreground" role="status">
            Liczę pulę…
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">Popraw reguły, żeby zobaczyć podgląd.</p>
        )}
      </aside>
    </div>
  );
}

/** Reguły listy telefonów praktykantów (makieta „Reguly”). */
export function TraineeRulesForm() {
  const rules = useTraineeRules();
  if (rules.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać reguł listy. Spróbuj ponownie."
        onRetry={() => rules.refetch()}
      />
    );
  }
  if (!rules.isSuccess) {
    return (
      <p className="py-6 text-sm text-muted-foreground" role="status">
        Wczytuję reguły…
      </p>
    );
  }
  return <RulesEditor saved={rules.data} />;
}
