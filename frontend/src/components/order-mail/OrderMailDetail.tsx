"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Building2,
  Check,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  RotateCcw,
  ScanSearch,
  UserCog,
  UserPlus,
  Users,
  UserX,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import {
  ORDER_MAIL_ACTION_LABEL,
  needsPersonDecision,
  orderMailApi,
  orderWindowHref,
  type OrderMailDocument,
  type OrderMailProposalRow,
} from "@/lib/api/orderMail";
import { openAuthenticatedFile } from "@/lib/authenticated-files";
import { errorOutsideReasons } from "@/lib/order-mail-sync";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import {
  applyButtonLabel,
  effectiveOverlapChoices,
  overlapApplyPayload,
  overlapOptionLabel,
  overlapRows,
  previousRateNote,
  type OverlapApplyChoices,
  type OverlapChoices,
} from "@/lib/order-mail-overlap";
import {
  applyBlockedReason,
  awaitsDecision,
  canActOn,
  checkPoints,
  failedRetryNote,
  identLabel,
  recheckLine,
  rowReasonsOutsideGate,
  senderLabel,
  type CheckPoint,
  type CheckPointKind,
} from "@/lib/order-mail-points";

/**
 * Szczegół wpisu kolejki zamówień z maila (przebudowa 20.11.2026, wariant A):
 * co odczytano (klient, numer, okres, osoby ze stawką i planem), „Do
 * sprawdzenia” jako punkty z ikoną i podpowiedzią zamiast żółtej ściany tekstu,
 * a na dole jedna główna akcja i ciche „Odrzuć”.
 *
 * Reguły, które łatwo zgubić:
 *  - powód z bramki jest treścią ekranu — każdy trafia do punktów, także ten,
 *    którego rodzaju nie rozpoznamy (`lib/order-mail-points.ts`);
 *  - kwoty renderują się jako „—”, gdy backend je zredagował; front nie decyduje;
 *  - podpowiedź „co zrobić” widzi tylko ten, kto może decyzję podjąć.
 */

export const SECTION_LABEL = "text-[10.5px] font-semibold uppercase tracking-[0.06em] text-muted-foreground";

export const POINT_ICON: Record<CheckPointKind, LucideIcon> = {
  client: Building2,
  new_person: UserPlus,
  namesake: Users,
  return: RotateCcw,
  decide_person: UserCog,
  no_people: UserX,
  uncertain: ScanSearch,
  other: CircleAlert,
};

export function orderMailNumber(doc: Pick<OrderMailDocument, "extraction" | "proposal">): string | null {
  return doc.extraction?.title ?? doc.proposal?.order_number ?? null;
}

function period(a: string | null | undefined, b: string | null | undefined): string {
  return `${formatIsoDatePl(a ?? null)} – ${b ? formatIsoDatePl(b) : "bezterminowo"}`;
}

function CheckItem({ point, showHint, deciding }: { point: CheckPoint; showHint: boolean; deciding: boolean }) {
  const [open, setOpen] = useState(false);
  const Icon = POINT_ICON[point.kind];
  const collapsible = Boolean(point.collapsible) && point.details.length > 0;
  const details = collapsible && !open ? [] : point.details;
  return (
    <li className="flex gap-2.5" data-testid={point.kind === "decide_person" ? "person-decision" : undefined}>
      <span
        aria-hidden
        className={cn(
          "mt-px flex size-6 shrink-0 items-center justify-center rounded-md",
          deciding ? "bg-warning-muted text-warning-muted-foreground" : "bg-muted text-muted-foreground",
        )}
      >
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1 text-[12.5px] leading-[18px]">
        <p className="text-[13px] font-medium leading-5 text-foreground">{point.title}</p>
        {details.map((d, i) => (
          <p key={`${i}-${d}`} className="text-muted-foreground">
            {d}
          </p>
        ))}
        {collapsible ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="text-primary underline-offset-2 hover:underline"
          >
            {open ? "Ukryj uwagi odczytu" : `Uwagi odczytu (${point.details.length})`}
          </button>
        ) : null}
        {showHint && point.hint ? (
          <p className="mt-0.5 text-muted-foreground">
            <span className="font-medium text-foreground">Co zrobić: </span>
            {point.hint}
          </p>
        ) : null}
        {point.links?.length ? (
          <p className="mt-0.5 flex flex-wrap gap-x-3">
            {point.links.map((l) => (
              <Link key={l.href} href={l.href} className="font-medium text-primary underline-offset-2 hover:underline">
                {l.label}
              </Link>
            ))}
          </p>
        ) : null}
      </div>
    </li>
  );
}

/** Kolumna „Po zastosowaniu” — co zrobi „Zastosuj” z tą osobą. */
function PlanCell({ row, doc }: { row: OrderMailProposalRow; doc: OrderMailDocument }) {
  // Powody osoby do rozstrzygnięcia mówi punkt „Do sprawdzenia”; pozostałe
  // tylko te, których bramka nie powtórzyła w punktach.
  const reasons = row.action === "decide_person" ? [] : rowReasonsOutsideGate(row, doc.gate_reasons ?? []);
  if ((row.existing_person_ids?.length ?? 0) > 0) {
    // Plan nadal zakłada szkic, ale domyślną odpowiedzią nie jest „nowy
    // kontraktor”: osoba o tym imieniu i nazwisku JEST w bazie.
    return (
      <div data-testid="person-already-in-base">
        <div className="font-medium text-warning-muted-foreground">Osoba jest już w bazie — potwierdź tożsamość</div>
        {reasons.map((x) => (
          <div key={x} className="text-xs text-warning-muted-foreground">
            {x}
          </div>
        ))}
        <div className="mt-0.5 text-xs text-muted-foreground">Po potwierdzeniu: {ORDER_MAIL_ACTION_LABEL[row.action]}</div>
      </div>
    );
  }
  if ((row.overlap_options?.length ?? 0) > 0) {
    return (
      <>
        <div>{`Przedłużenie #${row.target_order_id} — wybierz niżej`}</div>
        <div className="text-xs text-muted-foreground">
          #{row.target_order_id}: {period(row.previous_start_date, row.previous_end_date)}
        </div>
      </>
    );
  }
  return (
    <>
      <div>{ORDER_MAIL_ACTION_LABEL[row.action]}</div>
      {reasons.map((x) => (
        <div key={x} className="text-xs text-muted-foreground">
          {x}
        </div>
      ))}
    </>
  );
}

/** Osoby z planu zapisu: stawka klienta i to, co zrobi „Zastosuj”. */
function PlanTable({ doc }: { doc: OrderMailDocument }) {
  const ex = doc.extraction;
  const rows = doc.proposal?.rows ?? [];
  const extracted = ex?.consultant_rows ?? [];
  if (rows.length === 0 && extracted.length === 0) {
    return <p className="text-[13px] text-muted-foreground">Z PDF-a nie udało się odczytać żadnej osoby.</p>;
  }
  // Okres osoby równy okresowi dokumentu stoi już wyżej — kolumna tylko przy różnicy.
  const docPeriod = period(ex?.start_date, ex?.end_date);
  const showPeriod = [...rows, ...extracted].some((r) => period(r.start_date, r.end_date) !== docPeriod);
  return (
    // Kwoty z twardą spacją — na telefonie tabela przewija się w bok.
    <div className="overflow-x-auto">
      <table className="w-full min-w-[360px] text-[13px]">
        <thead>
          <tr className="border-b border-border">
            <th className={cn(CALM_HEAD, "py-1.5 pr-3 text-left")}>Osoba</th>
            {showPeriod ? <th className={cn(CALM_HEAD, "py-1.5 pr-3 text-left")}>Okres</th> : null}
            <th className={cn(CALM_HEAD, "whitespace-nowrap py-1.5 pr-3 text-right")}>Stawka klienta</th>
            <th className={cn(CALM_HEAD, "py-1.5 text-left")}>
              {doc.outcome === "needs_review" ? "Po zastosowaniu" : "Plan zapisu"}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const rateNote = previousRateNote(r, ex?.currency);
            const gross = ex?.consultant_rows[r.row_index]?.rate_client_gross ?? null;
            return (
              <tr key={r.row_index} className={cn(CALM_ROW, "align-top last:border-b-0")}>
                <td className="py-2 pr-3 font-medium text-foreground">{r.row_name}</td>
                {showPeriod ? (
                  <td className="py-2 pr-3 tabular-nums">{period(r.start_date, r.end_date)}</td>
                ) : null}
                <td className={cn(CALM_AMOUNT, "py-2 pr-3")}>
                  {/* Waluta z odczytu dokumentu — 110 EUR nie jest „110 zł” (audyt 24.09, S5). */}
                  {formatMoney(r.rate_client, ex?.currency, r.rate_unit)}
                  {gross != null ? (
                    <>
                      {" netto"}
                      <div className="text-xs text-muted-foreground">
                        {formatMoney(gross, ex?.currency, r.rate_unit)} brutto ÷ 1,23
                      </div>
                    </>
                  ) : null}
                  {rateNote ? (
                    // Przedłużenie: stawka poprzedniego zamówienia, nie rekrutacji (27.10.2026).
                    <div className="mt-0.5 text-xs text-muted-foreground" data-testid="previous-rate">
                      {rateNote.text}
                      {rateNote.change ? (
                        <span className="ml-1 rounded bg-info-muted px-1 font-medium text-info-muted-foreground">
                          {rateNote.change}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </td>
                <td className="py-2">
                  <PlanCell row={r} doc={doc} />
                </td>
              </tr>
            );
          })}
          {rows.length === 0
            ? extracted.map((r, i) => (
                <tr key={i} className={cn(CALM_ROW, "align-top last:border-b-0")}>
                  <td className="py-2 pr-3 font-medium text-foreground">{r.consultant_name}</td>
                  {showPeriod ? (
                    <td className="py-2 pr-3 tabular-nums">{period(r.start_date, r.end_date)}</td>
                  ) : null}
                  <td className={cn(CALM_AMOUNT, "py-2 pr-3")}>{formatMoney(r.rate_client, ex?.currency, r.rate_unit)}</td>
                  <td className="py-2 text-muted-foreground">bez planu zapisu</td>
                </tr>
              ))
            : null}
        </tbody>
      </table>
    </div>
  );
}

export interface OrderMailDetailProps {
  doc: OrderMailDocument;
  /** `overlapChoices` — tylko gdy dokument ma wiersz `overlap` z wyborem. */
  onApply: (overlapChoices?: OverlapApplyChoices) => void;
  onDismiss: () => void;
  onRefreshPlan?: () => void;
  busy: boolean;
  applyError: string | null;
  /** Przełącznik podglądu PDF — tylko gdy jest plik i źródło podglądu. */
  preview?: { open: boolean; onToggle: () => void };
}

export function OrderMailDetail({ doc, onApply, onDismiss, onRefreshPlan, busy, applyError, preview }: OrderMailDetailProps) {
  const ex = doc.extraction;
  const number = orderMailNumber(doc);
  const review = doc.outcome === "needs_review";
  const [fileError, setFileError] = useState<string | null>(null);
  // Wybór dla nakładającego się okresu (27.10.2026): domyślnie pierwsza
  // możliwość planu; po „Przelicz plan” wybór spoza nowego planu odpada.
  const [pickedOverlap, setPickedOverlap] = useState<OverlapChoices>({});
  const planRows = doc.proposal?.rows ?? [];
  const pendingOverlap = review ? overlapRows(planRows) : [];
  const overlapChoices = effectiveOverlapChoices(planRows, pickedOverlap);
  const points = checkPoints(doc);
  const deciding = awaitsDecision(doc);
  const canAct = canActOn(doc);
  const recheck = recheckLine(doc);
  const blocked = review ? applyBlockedReason(doc) : null;
  // „Błąd:” tylko, gdy mówi coś, czego nie ma w punktach (UAT B49).
  const distinctError = errorOutsideReasons(doc.error, doc.gate_reasons);
  // Osoba nieaktywna/nieznaleziona na zamówieniu MD/kosztowym: decyzja w oknie
  // zamówienia klienta (ten sam mechanizm co przy ręcznym wgraniu PDF-a).
  const windowHref = orderWindowHref(doc);
  const decideHref = review && needsPersonDecision(doc) && windowHref && doc.can_apply && doc.has_file ? windowHref : null;
  const canDismissOther =
    (doc.outcome === "failed" || doc.outcome === "unrecognized_client") && doc.can_dismiss === true;
  return (
    <section
      className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-xs"
      data-testid="order-mail-detail"
      data-help="contracts.order_mail.detail"
      data-tour="order-mail.detail"
    >
      <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-border/60 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold leading-5 text-foreground">
            {doc.client_name ?? "Nierozpoznany klient"}
            {number ? <span className="font-normal text-muted-foreground"> · zamówienie {number}</span> : null}
          </h2>
          <p
            className="mt-0.5 truncate text-xs text-muted-foreground"
            title={[doc.sender_email, doc.subject].filter(Boolean).join(" · ") || undefined}
          >
            Wpłynęło {formatDateTimePl(doc.received_at)} od {senderLabel(doc.sender_email)}
            {doc.subject ? ` · „${doc.subject}”` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {doc.has_file ? (
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              {preview ? (
                <Button size="sm" variant="ghost" onClick={preview.onToggle} aria-pressed={preview.open}>
                  {preview.open ? <EyeOff className="size-3.5" aria-hidden /> : <Eye className="size-3.5" aria-hidden />}
                  {preview.open ? "Ukryj podgląd" : "Pokaż podgląd"}
                </Button>
              ) : null}
              {/* Plik idzie z backendu z tokenem (Bearer) i otwiera się jako blob —
                  zwykły `<a href>` na hoście frontendu kończył się stroną 404. */}
              <Button
                size="sm"
                variant="outline"
                title={doc.attachment_name ?? undefined}
                onClick={() => {
                  setFileError(null);
                  openAuthenticatedFile(
                    orderMailApi.fileUrl(doc.id),
                    "application/pdf",
                    doc.attachment_name ?? `zamowienie-${doc.id}.pdf`,
                  ).catch(() => setFileError("Nie udało się otworzyć pliku PDF."));
                }}
              >
                <FileText className="size-3.5" aria-hidden /> PDF <ExternalLink className="size-3" aria-hidden />
              </Button>
            </div>
          ) : (
            <span className="py-1.5 text-xs text-muted-foreground">Bez zapisanego pliku PDF</span>
          )}
          {fileError ? <span className="text-xs text-destructive">{fileError}</span> : null}
        </div>
      </header>

      <div className="space-y-4 px-4 py-3">
        <div>
          <h3 className={SECTION_LABEL}>Co odczytano</h3>
          <dl className="mt-1.5 grid grid-cols-1 gap-x-3 gap-y-0.5 text-[13px] leading-5 sm:grid-cols-[8.5rem_minmax(0,1fr)]">
            <dt className="text-muted-foreground">Klient</dt>
            <dd className="min-w-0">
              {doc.client_name ? (
                <>
                  <span className="font-medium text-foreground">{doc.client_name}</span>
                  <span className="text-muted-foreground"> · {identLabel(doc)}</span>
                </>
              ) : (
                <span className="text-muted-foreground">nie rozpoznano</span>
              )}
            </dd>
            <dt className="text-muted-foreground">Okres zamówienia</dt>
            <dd className="tabular-nums text-foreground">{ex ? period(ex.start_date, ex.end_date) : "—"}</dd>
            <dt className="text-muted-foreground">Plik</dt>
            <dd className="min-w-0 truncate text-foreground" title={doc.attachment_name ?? undefined}>
              {doc.attachment_name ?? "—"}
            </dd>
          </dl>
          <div className="mt-2.5">
            <PlanTable doc={doc} />
          </div>
        </div>

        {pendingOverlap.map((row) => (
          <fieldset key={row.row_index} className="space-y-1.5" data-testid="overlap-choice">
            <legend className={cn(SECTION_LABEL, "mb-1.5")}>
              {pendingOverlap.length > 1 ? `${row.row_name}: ` : ""}okres nachodzi na #{row.target_order_id} — co zrobić?
            </legend>
            {(row.overlap_options ?? []).map((option) => (
              <label
                key={option}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2 text-[13px]",
                  overlapChoices[row.row_index] === option ? "border-primary bg-primary/5" : "border-border",
                )}
              >
                <input
                  type="radio"
                  name={`overlap-${doc.id}-${row.row_index}`}
                  value={option}
                  checked={overlapChoices[row.row_index] === option}
                  onChange={() => setPickedOverlap((prev) => ({ ...prev, [row.row_index]: option }))}
                  disabled={!doc.can_apply || busy}
                  className="mt-0.5 accent-primary"
                />
                <span>{overlapOptionLabel(row, option)}</span>
              </label>
            ))}
          </fieldset>
        ))}

        {points.length > 0 ? (
          <div data-testid="gate-reasons">
            <h3 className={SECTION_LABEL}>
              {deciding ? `Do sprawdzenia · ${points.length}` : "Dlaczego czekało na sprawdzenie"}
            </h3>
            <ul className="mt-2 space-y-3">
              {points.map((p, i) => (
                <CheckItem key={`${p.kind}-${i}`} point={p} showHint={deciding && canAct} deciding={deciding} />
              ))}
            </ul>
            {deciding && !canAct ? (
              <p className="mt-2.5 text-xs text-muted-foreground">Decyzję podejmuje admin albo Delivery Lead klienta.</p>
            ) : null}
            {recheck ? <p className="mt-2.5 text-xs text-muted-foreground">{recheck}</p> : null}
          </div>
        ) : recheck ? (
          <p className="text-xs text-muted-foreground">{recheck}</p>
        ) : null}

        {distinctError ? <p className="text-[13px] text-destructive">Błąd: {distinctError}</p> : null}
        {doc.outcome === "failed" ? (
          <p role="status" className="text-[13px] text-muted-foreground" data-testid="failed-retry-note">
            {failedRetryNote(doc)}
          </p>
        ) : null}

        {doc.applied_order_id ? (
          <p className="flex flex-wrap items-center gap-x-1.5 text-[13px] text-foreground">
            <CircleCheck className="size-3.5 text-success" aria-hidden />
            Zapisane jako zamówienie #{doc.applied_order_id}
            {doc.applied_at ? <span className="text-muted-foreground">({formatDateTimePl(doc.applied_at)})</span> : null}
            {doc.client_id ? (
              <Link
                href={`/clients/${doc.client_id}?tab=zamowienia`}
                className="font-medium text-primary underline-offset-2 hover:underline"
              >
                Zamówienia klienta
              </Link>
            ) : null}
          </p>
        ) : null}
        {doc.proposal?.resolved_in_order ? (
          <p className="text-[13px] text-foreground">
            Rozstrzygnięte w oknie zamówienia — zamówienie nr{" "}
            {doc.proposal.resolved_in_order.order_number ??
              `#${doc.proposal.resolved_in_order.order_group_id ?? doc.proposal.resolved_in_order.order_id}`}
            {doc.proposal.resolved_in_order.resolved_at
              ? ` (${formatDateTimePl(doc.proposal.resolved_in_order.resolved_at)})`
              : ""}
            .
          </p>
        ) : null}
        {applyError ? (
          <p role="alert" className="text-[13px] text-destructive">
            {applyError}
          </p>
        ) : null}
      </div>

      {/* Stopka akcji: jedna główna po lewej, „Odrzuć” cicho po prawej. */}
      {review ? (
        <footer className="mt-auto flex flex-wrap items-center gap-2 border-t border-border/60 bg-muted/30 px-4 py-2.5">
          {decideHref ? (
            <Link href={decideHref} className={buttonVariants({ size: "sm" })}>
              <UserCog className="size-3.5" aria-hidden /> Rozstrzygnij w oknie zamówienia
            </Link>
          ) : null}
          <Button
            size="sm"
            variant={decideHref ? "outline" : "primary"}
            onClick={() => onApply(pendingOverlap.length > 0 ? overlapApplyPayload(planRows, overlapChoices) : undefined)}
            disabled={blocked != null || busy}
            title={blocked ?? undefined}
          >
            <Check className="size-3.5" aria-hidden /> {applyButtonLabel(planRows, overlapChoices)}
          </Button>
          {onRefreshPlan && doc.can_apply && doc.has_file ? (
            <Button
              size="sm"
              variant="outline"
              onClick={onRefreshPlan}
              disabled={busy}
              title="Sprawdź stawki z PDF i dopasuj osoby do aktualnej listy konsultantów klienta"
            >
              Przelicz plan
            </Button>
          ) : null}
          {/* Przy „Rozstrzygnij w oknie zamówienia” powód mówi sam przycisk — zdanie zostaje w `title`. */}
          {blocked && !decideHref ? <span className="min-w-0 text-xs text-muted-foreground">{blocked}</span> : null}
          <Button size="sm" variant="quiet" className="ml-auto" onClick={onDismiss} disabled={!doc.can_apply || busy}>
            <X className="size-3.5" aria-hidden /> Odrzuć
          </Button>
        </footer>
      ) : canDismissOther ? (
        // Wpis „Nieudane” wprowadzony ręcznie w oknie zamówienia i dokument bez
        // rozpoznanego klienta też muszą dać się zdjąć z kolejki (audyt N2,
        // runda 2 audytu 25.09.2026) — bez klienta odrzuca admin.
        <footer className="mt-auto flex flex-wrap items-center gap-2 border-t border-border/60 bg-muted/30 px-4 py-2.5">
          <Button size="sm" variant="quiet" className="ml-auto" onClick={onDismiss} disabled={busy}>
            <X className="size-3.5" aria-hidden /> Odrzuć
          </Button>
        </footer>
      ) : null}
    </section>
  );
}
