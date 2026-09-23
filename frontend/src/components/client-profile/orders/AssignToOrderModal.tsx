"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, FilePlus2, UserPlus, Users } from "lucide-react";

import { AppModal } from "@/components/ds";
import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type {
  OrderGroupRead,
  OrderLineInput,
  OrderLineTakeoverInput,
} from "@/lib/api/orderGroups";
import {
  contractCostRatePerMd,
  defaultEntryDate,
  freePoolMd,
  joinableGroups,
  mdOverFreePool,
  takeoverSources,
} from "@/lib/order-takeover";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";
import { formatDate } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";
import {
  TakeoverTermsFields,
  emptyTakeoverTerms,
  takeoverTermsError,
  toTakeoverInput,
  type TakeoverTermsValue,
} from "./TakeoverTermsFields";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

type Path = "choose" | "join" | "takeover";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contractor: ContractWithOrdersRead | null;
  groups: readonly OrderGroupRead[];
  submitting: boolean;
  error: string | null;
  onJoin: (groupId: number, values: OrderLineInput) => void;
  onTakeover: (groupId: number, values: OrderLineTakeoverInput) => void;
  /** „Nowe zamówienie" — dotychczasowe „Uzupełnij zamówienie" karty. */
  onNewOrder: () => void;
}

function groupLabel(group: OrderGroupRead): string {
  const executive = group.executive_contract?.number;
  return executive
    ? `${group.order_number} · umowa wykonawcza ${executive}`
    : group.order_number;
}

/** „Przypisz do zamówienia" z karty szkicu (wyłącznie Centrum e-Zdrowia).
 *
 *  Trzy ścieżki: dołącz do aktywnego zamówienia, wejdź za konsultanta
 *  (przejęcie pozostałych MD) albo nowe zamówienie z własną umową wykonawczą.
 *  Okno nie liczy niczego ostatecznie — podgląd MD jest tą samą regułą co
 *  serwer, który decyduje przy zapisie. */
export function AssignToOrderModal({
  open,
  onOpenChange,
  contractor,
  groups,
  submitting,
  error,
  onJoin,
  onTakeover,
  onNewOrder,
}: Props) {
  const today = warsawToday();
  const [path, setPath] = useState<Path>("choose");
  const costSuggestion = contractCostRatePerMd(
    contractor?.rate_candidate ?? null,
    contractor?.rate_unit ?? null,
  );
  const suggestedCost = costSuggestion ? String(costSuggestion.value) : "";

  // Dołącz
  const [joinGroupId, setJoinGroupId] = useState("");
  const [joinStart, setJoinStart] = useState(today);
  const [joinBase, setJoinBase] = useState("");
  const [joinOptional, setJoinOptional] = useState("");
  const [joinCost, setJoinCost] = useState("");
  const [joinRevenue, setJoinRevenue] = useState("");

  // Wejdź za konsultanta
  const [takeoverLineId, setTakeoverLineId] = useState("");
  const [terms, setTerms] = useState<TakeoverTermsValue>(emptyTakeoverTerms(today));

  useEffect(() => {
    if (!open) return;
    setPath("choose");
    setJoinGroupId("");
    setJoinStart(warsawToday());
    setJoinBase("");
    setJoinOptional("");
    setJoinCost(suggestedCost);
    setJoinRevenue("");
    setTakeoverLineId("");
    setTerms(emptyTakeoverTerms(warsawToday(), suggestedCost));
    // Formularz startuje od nowa przy każdym otwarciu dla tej osoby.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, contractor?.contract_id]);

  const contractId = contractor?.contract_id ?? 0;
  const joinable = useMemo(
    () => joinableGroups(groups, contractId),
    [groups, contractId],
  );
  const sources = useMemo(
    () =>
      takeoverSources(groups).filter(
        (source) => source.line.contract_id !== contractId,
      ),
    [groups, contractId],
  );
  const joinGroup = joinable.find((group) => String(group.id) === joinGroupId) ?? null;
  const joinPerPerson =
    joinGroup !== null &&
    !joinGroup.is_cost_based &&
    !joinGroup.is_md_budget_based &&
    joinGroup.md_budget_mode !== "shared";
  const requestedMd =
    (parseDecimalInput(joinBase) ?? 0) + (parseDecimalInput(joinOptional) ?? 0);
  const freeMd = joinGroup && joinPerPerson ? freePoolMd(joinGroup) : 0;
  const overMd = joinPerPerson ? mdOverFreePool(requestedMd, freeMd) : 0;

  const source = sources.find((item) => String(item.line.id) === takeoverLineId) ?? null;
  const incomingName = contractor?.candidate_name ?? "";

  const joinError = !joinGroup
    ? "Wybierz zamówienie."
    : !joinStart
      ? "Podaj datę od."
      : joinPerPerson && (parseDecimalInput(joinBase) ?? 0) <= 0
        ? "Podaj MD dla osoby."
        : parseDecimalInput(joinCost) == null
          ? "Podaj stawkę kosztową."
          : (parseDecimalInput(joinRevenue) ?? 0) <= 0
            ? "Podaj stawkę przychodową."
            : null;
  const takeoverError = takeoverTermsError(terms, source?.line ?? null);

  function submit() {
    if (!contractor) return;
    if (path === "join" && joinGroup && !joinError) {
      onJoin(joinGroup.id, {
        contract_id: contractor.contract_id,
        start_date: joinStart,
        rate_cost: parseDecimalInput(joinCost) as number,
        rate_revenue: parseDecimalInput(joinRevenue) as number,
        ...(joinPerPerson
          ? {
              input_mode: "md" as const,
              input_value: parseDecimalInput(joinBase) as number,
              optional_md: parseDecimalInput(joinOptional),
            }
          : {}),
        job_id: contractor.initial_job_id ?? null,
        assignment: "join",
      });
      return;
    }
    if (path === "takeover" && source && !takeoverError) {
      onTakeover(
        source.group.id,
        toTakeoverInput(terms, contractor.contract_id, source.line),
      );
    }
  }

  const canSubmit =
    !submitting &&
    ((path === "join" && joinError === null) ||
      (path === "takeover" && takeoverError === null));

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Przypisz do zamówienia"
      description={contractor ? contractor.candidate_name : undefined}
      footer={
        path === "choose" ? (
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
          >
            Anuluj
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => setPath("choose")}
              disabled={submitting}
              className="mr-auto inline-flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Wstecz
            </button>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
            >
              Anuluj
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={!canSubmit}
              className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {submitting ? "Zapisywanie…" : "Zapisz"}
            </button>
          </>
        )
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <p
            role="alert"
            className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        {path === "choose" ? (
          <div className="grid gap-2">
            <PathButton
              icon={UserPlus}
              title="Dołącz do aktywnego zamówienia"
              description="Osoba dochodzi jako kolejna do istniejącej umowy wykonawczej."
              disabled={joinable.length === 0}
              disabledNote="Brak aktywnego zamówienia, do którego można dołączyć."
              onClick={() => setPath("join")}
            />
            <PathButton
              icon={Users}
              title="Wejdź za konsultanta"
              description="Osoba przejmuje pozostałe MD osoby odchodzącej i rozlicza się po swojej stawce."
              disabled={sources.length === 0}
              disabledNote="Na zamówieniach nie ma osoby, za którą można wejść."
              onClick={() => setPath("takeover")}
            />
            <PathButton
              icon={FilePlus2}
              title="Nowe zamówienie"
              description="Osobne zamówienie z własną umową wykonawczą."
              onClick={() => {
                onOpenChange(false);
                onNewOrder();
              }}
            />
          </div>
        ) : null}

        {path === "join" ? (
          <div className="flex flex-col gap-4">
            <div>
              <label htmlFor="assign-join-group" className={labelClass}>
                Zamówienie *
              </label>
              <select
                id="assign-join-group"
                value={joinGroupId}
                onChange={(event) => setJoinGroupId(event.target.value)}
                className={inputClass}
              >
                <option value="">— wybierz zamówienie —</option>
                {joinable.map((group) => (
                  <option key={group.id} value={group.id}>
                    {groupLabel(group)}
                  </option>
                ))}
              </select>
              {joinGroup ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Obsada:{" "}
                  {joinGroup.lines
                    .filter((line) => line.is_active)
                    .map((line) => line.consultant_name)
                    .join(", ") || "brak aktywnych osób"}
                </p>
              ) : null}
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div>
                <label htmlFor="assign-join-start" className={labelClass}>
                  Data od *
                </label>
                <input
                  id="assign-join-start"
                  type="date"
                  value={joinStart}
                  onChange={(event) => setJoinStart(event.target.value)}
                  className={inputClass}
                />
              </div>
              {joinPerPerson ? (
                <>
                  <div>
                    <label htmlFor="assign-join-base" className={labelClass}>
                      MD — podstawa *
                    </label>
                    <input
                      id="assign-join-base"
                      inputMode="decimal"
                      value={joinBase}
                      onChange={(event) =>
                        setJoinBase(sanitizeDecimalInput(event.target.value))
                      }
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label htmlFor="assign-join-optional" className={labelClass}>
                      MD — opcja
                    </label>
                    <input
                      id="assign-join-optional"
                      inputMode="decimal"
                      value={joinOptional}
                      onChange={(event) =>
                        setJoinOptional(sanitizeDecimalInput(event.target.value))
                      }
                      className={inputClass}
                    />
                  </div>
                </>
              ) : null}
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="assign-join-cost" className={labelClass}>
                  Stawka koszt (zł/MD) *
                </label>
                <input
                  id="assign-join-cost"
                  inputMode="decimal"
                  value={joinCost}
                  onChange={(event) => setJoinCost(sanitizeDecimalInput(event.target.value))}
                  className={inputClass}
                />
                {costSuggestion ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {costSuggestion.note}
                  </p>
                ) : null}
              </div>
              <div>
                <label htmlFor="assign-join-revenue" className={labelClass}>
                  Stawka przychód (zł/MD) *
                </label>
                <input
                  id="assign-join-revenue"
                  inputMode="decimal"
                  value={joinRevenue}
                  onChange={(event) =>
                    setJoinRevenue(sanitizeDecimalInput(event.target.value))
                  }
                  className={inputClass}
                />
              </div>
            </div>
            {joinPerPerson && joinGroup ? (
              <p className="text-xs text-muted-foreground">
                Wolna pula zamówienia: {formatMd(freeMd)} MD (zwolnione po osobach
                z zakończoną współpracą, bez decyzji o MD).
              </p>
            ) : null}
            {overMd > 0 ? (
              <p
                role="status"
                className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
              >
                {formatMd(overMd)} MD ponad wolną pulę zamówienia. Zapis jest
                możliwy — sprawdź, czy klient zamówił dodatkowe dni.
              </p>
            ) : null}
          </div>
        ) : null}

        {path === "takeover" ? (
          <div className="flex flex-col gap-4">
            <div>
              <label htmlFor="assign-takeover-source" className={labelClass}>
                Za kogo wchodzi *
              </label>
              <select
                id="assign-takeover-source"
                value={takeoverLineId}
                onChange={(event) => {
                  const next = sources.find(
                    (item) => String(item.line.id) === event.target.value,
                  );
                  setTakeoverLineId(event.target.value);
                  setTerms((current) => ({
                    ...current,
                    method: null,
                    entryDate: defaultEntryDate(next?.departureDate ?? null, today),
                  }));
                }}
                className={inputClass}
              >
                <option value="">— wybierz osobę —</option>
                {groupsOf(sources).map(([group, items]) => (
                  <optgroup key={group.id} label={groupLabel(group)}>
                    {items.map((item) => (
                      <option key={item.line.id} value={item.line.id}>
                        {item.line.consultant_name} —{" "}
                        {item.state === "ended"
                          ? `zakończył(a) ${formatDate(item.departureDate)}`
                          : `kończy ${formatDate(item.departureDate)}`}{" "}
                        · pozostało {formatMd(item.remaining)} MD
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            {source ? (
              <TakeoverTermsFields
                idPrefix="assign-takeover"
                departing={source.line}
                incomingName={incomingName}
                value={terms}
                onChange={setTerms}
                costNote={costSuggestion?.note ?? null}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </AppModal>
  );
}

function groupsOf<T extends { group: OrderGroupRead }>(
  items: readonly T[],
): Array<[OrderGroupRead, T[]]> {
  const byGroup = new Map<number, [OrderGroupRead, T[]]>();
  for (const item of items) {
    const entry = byGroup.get(item.group.id) ?? [item.group, []];
    entry[1].push(item);
    byGroup.set(item.group.id, entry);
  }
  return [...byGroup.values()];
}

function PathButton({
  icon: Icon,
  title,
  description,
  disabled = false,
  disabledNote,
  onClick,
}: {
  icon: typeof UserPlus;
  title: string;
  description: string;
  disabled?: boolean;
  disabledNote?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-start gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-border disabled:hover:bg-card"
    >
      <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
      <span>
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        <span className="block text-xs text-muted-foreground">
          {disabled && disabledNote ? disabledNote : description}
        </span>
      </span>
    </button>
  );
}
