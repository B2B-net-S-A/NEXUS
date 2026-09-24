"use client";

import { useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { ConsultantOption, OrderPlanContract } from "@/lib/api/orderGroups";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import {
  backToOptions,
  chooseConsultant,
  chooseContract,
  keepAsHistory,
  rejectMatch,
  replaceWith,
  resumeCooperation,
  sourceLabel,
  undoInactiveDecision,
  type LineSource,
  type OrderLineDraft,
} from "@/lib/order-plan";
import { convertRate, type RateUnit } from "@/lib/rate-unit";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { ConsultantPicker } from "./ConsultantPicker";

const tileInput =
  "w-full min-w-0 bg-transparent text-base font-semibold text-foreground focus:outline-none";

const STATUS_LABELS: Record<string, string> = {
  active: "aktywny",
  ending: "kończący się",
  draft: "szkic",
  ready_for_signature: "do podpisu",
  ended: "zakończony",
};

function unitSuffix(unit: RateUnit, currency: string): string {
  const money = currency === "PLN" ? "zł" : currency;
  return `${money}/${unit === "hour" ? "h" : unit === "month" ? "mc" : "MD"}`;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-");
  return d && m && y ? `${d}.${m}.${y}` : value;
}

/** Odznaka wyniku dopasowania — trzy stany z ticketu + wybór ręczny. */
export function MatchBadge({ draft }: { draft: OrderLineDraft }) {
  if (draft.match === "manual" && draft.person) {
    return draft.replacesName ? (
      <Badge variant="info">Zastępstwo</Badge>
    ) : (
      <Badge variant="info">Wskazano ręcznie</Badge>
    );
  }
  if (draft.match === "inactive") {
    if (draft.inactiveDecision === "history") {
      return <Badge variant="neutral">Zapis historyczny</Badge>;
    }
    if (draft.inactiveDecision === "resume") {
      return <Badge variant="success">Wznowienie współpracy</Badge>;
    }
    return <Badge variant="danger">Zakończył współpracę</Badge>;
  }
  if (draft.match === "auto") {
    return <Badge variant="success">Dopasowano automatycznie</Badge>;
  }
  if (draft.match === "confirm") {
    return draft.confirmed ? (
      <Badge variant="success">Potwierdzono</Badge>
    ) : (
      <Badge variant="warning">Dopasowano — potwierdź</Badge>
    );
  }
  if (draft.match === "ambiguous") {
    return <Badge variant="danger">Kilka osób — wybierz ręcznie</Badge>;
  }
  return <Badge variant="danger">Wymaga ręcznego wskazania</Badge>;
}

interface ValueTileProps {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  source: string | null;
  unit?: RateUnit | null;
  currency?: string;
  onUnitChange?: (unit: RateUnit) => void;
  suffix?: string;
  hint?: string | null;
}

function ValueTile({
  label,
  value,
  onValueChange,
  source,
  unit,
  currency = "PLN",
  onUnitChange,
  suffix,
  hint,
}: ValueTileProps) {
  return (
    <div className="min-w-0 rounded-md border border-border bg-muted/30 px-3 py-2">
      <label className="block text-xs text-muted-foreground">
        {label}
        <div className="mt-0.5 flex items-baseline gap-1">
          <input
            aria-label={label}
            inputMode="decimal"
            value={value}
            placeholder="—"
            onChange={(event) => onValueChange(sanitizeDecimalInput(event.target.value))}
            className={tileInput}
          />
          {onUnitChange ? (
            <select
              aria-label={`${label} — jednostka`}
              value={unit ?? ""}
              onChange={(event) => onUnitChange(event.target.value as RateUnit)}
              className={
                "shrink-0 bg-transparent text-xs focus:outline-none " +
                (unit ? "text-muted-foreground" : "font-semibold text-destructive")
              }
            >
              {unit ? null : (
                <option value="" disabled>
                  jednostka?
                </option>
              )}
              {(["md", "hour", "month"] as RateUnit[]).map((option) => (
                <option key={option} value={option}>
                  {unitSuffix(option, currency)}
                </option>
              ))}
            </select>
          ) : suffix ? (
            <span className="shrink-0 text-xs text-muted-foreground">{suffix}</span>
          ) : null}
        </div>
      </label>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        {source ?? "brak — wpisz ręcznie"}
      </p>
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

interface Props {
  clientId: number;
  draft: OrderLineDraft;
  onChange: (next: OrderLineDraft) => void;
  onRemove: () => void;
  showMd: boolean;
  duplicated: boolean;
  issues: string[];
}

export function OrderPlanLineCard({
  clientId,
  draft,
  onChange,
  onRemove,
  showMd,
  duplicated,
  issues,
}: Props) {
  const [picking, setPicking] = useState(false);
  // „Zastąp kimś innym": wybrana osoba zapisze się jako zastępstwo za osobę
  // z dokumentu (historia zamówienia pokaże to przy niej).
  const [replacing, setReplacing] = useState(false);
  const needsPerson = !draft.person;
  const showPicker =
    picking || replacing || (needsPerson && draft.options.length === 0);
  const inactivePending = draft.match === "inactive" && !draft.inactiveDecision;
  const heldName = draft.documentName ?? draft.person?.name ?? "Ta osoba";

  const edit = (patch: Partial<OrderLineDraft>) => onChange({ ...draft, ...patch });
  const manual: LineSource = "manual";

  const switchUnit = (
    field: "rateCost" | "rateRevenue",
    unitField: "costUnit" | "revenueUnit",
    next: RateUnit,
  ) => {
    const current = draft[unitField];
    if (next === current) return;
    const parsed = parseDecimalInput(draft[field]);
    // Nieznana jednostka (dokument jej nie podał): wybór NIE przelicza kwoty —
    // DL mówi, w jakiej jednostce jest liczba, którą widzi.
    const converted =
      parsed === null || current === null ? null : convertRate(parsed, current, next);
    edit({
      [unitField]: next,
      ...(converted !== null ? { [field]: String(converted) } : {}),
    } as Partial<OrderLineDraft>);
  };

  const heading = draft.documentName ?? draft.person?.name ?? "Nowy konsultant";

  return (
    <article
      aria-label={`Konsultant: ${heading}`}
      className="@container rounded-lg border border-border bg-card p-3 shadow-sm"
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">
            {heading}
            {draft.documentName ? (
              <span className="font-normal text-muted-foreground"> — PDF</span>
            ) : null}
          </p>
          <p className="text-xs text-muted-foreground">
            {draft.person ? (
              <>
                {draft.person.contractId !== null ? "Kontrakt" : "Osoba z bazy"}:{" "}
                „{draft.person.name}”
                {draft.person.status
                  ? ` · ${STATUS_LABELS[draft.person.status] ?? draft.person.status}`
                  : ""}
                {draft.person.contractId === null
                  ? " · zapis założy kontrakt w statusie szkic"
                  : ""}
              </>
            ) : draft.documentName ? (
              "Kontrakt nie został wskazany"
            ) : (
              "Wskaż kontraktora"
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <MatchBadge draft={draft} />
          <button
            type="button"
            aria-label={`Usuń kartę: ${heading}`}
            title="Usuń z zamówienia"
            onClick={onRemove}
            className="hit-area rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </header>

      {/* Container query, nie breakpoint wiewportu: karta żyje w oknie
          (max 672 px), które nie szerzeje razem z ekranem — przy `lg:` cztery
          kafle po ~145 px ściskały etykietę, wartość i jednostkę. */}
      <div className={`mt-3 grid gap-2 ${showMd ? "@lg:grid-cols-2 @2xl:grid-cols-4" : "@lg:grid-cols-2"}`}>
        <ValueTile
          label="Stawka kosztowa"
          value={draft.rateCost}
          onValueChange={(value) => edit({ rateCost: value, costSource: manual })}
          source={sourceLabel(draft.costSource, draft)}
          unit={draft.costUnit}
          currency={draft.costCurrency}
          onUnitChange={(unit) => switchUnit("rateCost", "costUnit", unit)}
        />
        <ValueTile
          label="Stawka przychodowa"
          value={draft.rateRevenue}
          onValueChange={(value) =>
            edit({ rateRevenue: value, revenueSource: manual, revenueGross: null })
          }
          source={sourceLabel(draft.revenueSource, draft)}
          unit={draft.revenueUnit}
          currency={draft.revenueCurrency}
          onUnitChange={(unit) => switchUnit("rateRevenue", "revenueUnit", unit)}
          hint={
            draft.revenueGross !== null
              ? `w PDF brutto ${draft.revenueGross} → netto (÷ 1,23)`
              : null
          }
        />
        {showMd ? (
          <ValueTile
            label="Liczba MD"
            value={draft.md}
            onValueChange={(value) => edit({ md: value, mdSource: manual })}
            source={sourceLabel(draft.mdSource, draft)}
            suffix="MD"
          />
        ) : null}
        {showMd && isEzdrowieClient(clientId) ? (
          // Opcja z umowy wykonawczej — tylko Centrum e-Zdrowia; nie z PDF-a,
          // więc źródło zawsze „ręcznie" albo brak; puste pole = umowa bez opcji.
          <ValueTile
            label="Zakres opcjonalny (MD)"
            value={draft.optionalMd}
            onValueChange={(value) => edit({ optionalMd: value })}
            source={draft.optionalMd ? "wpisano ręcznie" : "brak opcji w umowie"}
            suffix="MD"
          />
        ) : null}
      </div>

      {draft.startDate || draft.endDate ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Okres pozycji wg PDF: {formatDate(draft.startDate)} –{" "}
          {draft.endDate ? formatDate(draft.endDate) : "bezterminowo"}
        </p>
      ) : null}

      {draft.match === "inactive" && draft.person && inactivePending ? (
        <div
          role="alert"
          className="mt-3 rounded-md border border-destructive/30 bg-destructive-muted px-3 py-2 text-xs text-destructive-muted-foreground"
        >
          <p className="font-medium">{draft.matchReason}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onChange(keepAsHistory(draft))}
              className="rounded-md bg-foreground px-2.5 py-1 pointer-coarse:py-2 font-medium text-background"
            >
              Zostaw jako historię
            </button>
            <button
              type="button"
              onClick={() => onChange(resumeCooperation(draft))}
              className="rounded-md border border-border bg-background px-2.5 py-1 pointer-coarse:py-2 font-medium text-foreground"
            >
              Wznów współpracę
            </button>
            <button
              type="button"
              onClick={() => {
                setReplacing(true);
                setPicking(false);
              }}
              className="rounded-md border border-border bg-background px-2.5 py-1 pointer-coarse:py-2 font-medium text-foreground"
            >
              Zastąp kimś innym
            </button>
            <button
              type="button"
              onClick={onRemove}
              className="rounded-md border border-destructive/40 bg-background px-2.5 py-1 pointer-coarse:py-2 font-medium text-destructive"
            >
              Usuń z zamówienia
            </button>
            {draft.options.length > 0 ? (
              <button
                type="button"
                onClick={() => onChange(backToOptions(draft))}
                className="rounded-md px-2.5 py-1 pointer-coarse:py-2 font-medium text-primary underline-offset-2 hover:underline"
              >
                Wybierz inną pozycję z listy
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {draft.match === "inactive" && draft.inactiveDecision ? (
        <div
          role="status"
          className="mt-3 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
        >
          <p>
            {draft.inactiveDecision === "history"
              ? `${heldName} zostanie na zamówieniu jako zakończona współpraca` +
                (draft.contractEndDate
                  ? ` (udział do ${formatDate(draft.contractEndDate)})`
                  : "") +
                " — bez wznawiania kontraktu. Jej wykorzystana kwota i MD nie wrócą do puli."
              : `Zapis zamówienia wznowi współpracę: ${heldName} wraca na aktywną obsadę.`}
          </p>
          <button
            type="button"
            onClick={() => onChange(undoInactiveDecision(draft))}
            className="mt-1 font-medium text-primary underline-offset-2 hover:underline"
          >
            Zmień decyzję
          </button>
        </div>
      ) : null}

      {draft.replacesName && draft.person ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Zastępstwo za: <span className="font-medium">{draft.replacesName}</span>{" "}
          — historia zamówienia zapisze, kto i kiedy dodał tę osobę, a PDF
          zamówienia zostanie podpięty także do jej profilu.
        </p>
      ) : null}

      {draft.match === "confirm" && !draft.confirmed && draft.person ? (
        <div
          role="status"
          className="mt-3 rounded-md border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          <p>{draft.matchReason}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => edit({ confirmed: true })}
              className="rounded-md bg-foreground px-2.5 py-1 pointer-coarse:py-2 font-medium text-background"
            >
              To ta osoba — potwierdzam
            </button>
            <button
              type="button"
              onClick={() => {
                onChange(rejectMatch(draft));
                setPicking(true);
              }}
              className="rounded-md border border-border bg-background px-2.5 py-1 pointer-coarse:py-2 font-medium text-foreground"
            >
              To nie ta osoba
            </button>
          </div>
        </div>
      ) : null}

      {needsPerson && draft.options.length > 0 ? (
        <fieldset className="mt-3 rounded-md border border-destructive/30 bg-destructive-muted px-3 py-2 text-xs text-destructive-muted-foreground">
          <legend className="sr-only">Wybierz właściwy kontrakt</legend>
          <p>{draft.matchReason}</p>
          <div className="mt-2 flex flex-col gap-1.5">
            {draft.options.map((option: OrderPlanContract) => (
              <button
                key={option.contract_id}
                type="button"
                onClick={() => onChange(chooseContract(draft, option))}
                className="rounded-md border border-border bg-background px-2.5 py-1.5 pointer-coarse:py-2.5 text-left text-foreground hover:bg-muted"
              >
                <span className="font-medium">{option.contractor_name}</span>
                <span className="text-muted-foreground">
                  {" "}
                  · kontrakt #{option.contract_id} · od {formatDate(option.start_date)}
                  {option.end_date ? ` do ${formatDate(option.end_date)}` : ""} ·{" "}
                  {STATUS_LABELS[option.status] ?? option.status}
                </span>
              </button>
            ))}
          </div>
        </fieldset>
      ) : null}

      {needsPerson && draft.options.length === 0 && draft.matchReason ? (
        <div
          role="alert"
          className="mt-3 rounded-md border border-destructive/30 bg-destructive-muted px-3 py-2 text-xs text-destructive-muted-foreground"
        >
          <p>{draft.matchReason}</p>
          {draft.nearestNames.length > 0 ? (
            <p className="mt-1">
              Najbliższy zapis w kontraktach:{" "}
              {draft.nearestNames.map((name) => `„${name}”`).join(", ")} — system
              nie przypisuje go sam.
            </p>
          ) : null}
          {draft.documentName ? (
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setReplacing(true);
                  setPicking(false);
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1 pointer-coarse:py-2 font-medium text-foreground"
              >
                Zastąp kimś innym
              </button>
              <button
                type="button"
                onClick={onRemove}
                className="rounded-md border border-destructive/40 bg-background px-2.5 py-1 pointer-coarse:py-2 font-medium text-destructive"
              >
                Usuń z zamówienia
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {showPicker ? (
        <div className="mt-3">
          <span className="mb-1 block text-xs font-semibold text-muted-foreground">
            {replacing
              ? `Kto zastępuje: ${heldName}`
              : draft.documentName && needsPerson
                ? "Wskaż tę osobę ręcznie"
                : "Wybierz kontraktora ręcznie"}
          </span>
          <ConsultantPicker
            clientId={clientId}
            value={null}
            onChange={(option: ConsultantOption | null) => {
              if (!option) return;
              onChange(
                replacing ? replaceWith(draft, option) : chooseConsultant(draft, option),
              );
              setPicking(false);
              setReplacing(false);
            }}
          />
          {replacing ? (
            <button
              type="button"
              onClick={() => setReplacing(false)}
              className="mt-1 text-xs font-medium text-primary underline-offset-2 hover:underline"
            >
              Anuluj zastępstwo
            </button>
          ) : null}
        </div>
      ) : draft.person &&
        !(draft.match === "confirm" && !draft.confirmed) &&
        !inactivePending ? (
        <button
          type="button"
          onClick={() => setPicking(true)}
          className="mt-2 text-xs font-medium text-primary underline-offset-2 hover:underline"
        >
          Zmień osobę
        </button>
      ) : null}

      {duplicated ? (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-warning-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Ta sama osoba jest na zamówieniu więcej niż raz — sprawdź, czy to dwie
          osobne pozycje.
        </p>
      ) : null}
      {draft.warnings.map((warning) => (
        <p
          key={warning}
          className="mt-2 flex items-start gap-1.5 text-xs text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {warning}
        </p>
      ))}
      {issues.length > 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Do uzupełnienia: {issues.join(", ")}
        </p>
      ) : null}
    </article>
  );
}
