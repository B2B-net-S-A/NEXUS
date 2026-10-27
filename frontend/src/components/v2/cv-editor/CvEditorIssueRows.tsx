"use client";

/**
 * Wiersze panelu „Do poprawy” w edytorze CV (wariant A, decyzje Artura D1–D7,
 * 17.10.2026). Rekruter: „panel mówi, co jest nie tak, i jednym guzikiem
 * wprowadza zmianę”. Jeden wiersz = problem, podgląd zmiany (przekreślone →
 * zielone) i jeden przycisk; szczegóły (dowód, „Pokaż w CV”, „To nieprawda”)
 * rozwijają się po kliknięciu w tytuł, który też pokazuje miejsce na kartce.
 *
 * Okno QC na Tablicy ma dalej swoje karty (`recruitment/cv-qc-cards.tsx`) —
 * wiersze biorą z nich tylko wspólne kawałki: formularz „To nieprawda”,
 * „Szukałem w” i przycisk zgody RODO / generatora.
 *
 * Treść CV, dowodów i propozycji to TEKST — nic nie trafia na stronę jako HTML.
 */

import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Ban, Copy, Loader2, LocateFixed, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ConsentAttachButton } from "@/components/v2/cv-generator/ConsentAttachButton";
import {
  DismissForm,
  ItemAction,
  SearchedChips,
  type ActionContext,
  type DismissFormValue,
} from "@/components/v2/recruitment/cv-qc-cards";
import type { CvIssueDismissBody, CvReviewFinding } from "@/lib/api/cvEditorIssues";
import type { QcCheck, QcFix, QcItem } from "@/lib/api/cvQc";
import {
  ISSUE_SOURCE_LABEL,
  REVIEW_FINDING_LABEL,
  consentTarget,
  itemQuickFix,
  itemSentence,
  yearsPreview,
  type IssueRow,
} from "@/lib/cv-editor-issues";
import type { ClassifiedCvWarning } from "@/lib/cv-generator";
import { humanizeCvWarning } from "@/lib/cv-warning-text";
import {
  QC_DISMISS_QUOTE_MAX,
  QC_TASK_TAG,
  canDismissItem,
  countForm,
  dismissNeedsQuote,
  itemTarget,
  notePreview,
  originalDescribesSkill,
  parseBoldMarkup,
  qcDismissError,
  taskTitle,
  type IssueTarget,
  type QcTask,
} from "@/lib/cv-qc";
import { cn } from "@/lib/utils";

/** „To nieprawda” i „OK” / „Zostaw” przy uwadze generatora albo kontroli AI (tylko CV etapu). */
export interface IssueDismiss {
  submit: (issue: Pick<CvIssueDismissBody, "source" | "text" | "status">, value: DismissFormValue, onSaved: () => void) => void;
  /** Jedno kliknięcie: sprawdzone, treść zostaje (powód `kept`, 17.10.2026). */
  keep: (issue: Pick<CvIssueDismissBody, "source" | "text" | "status">) => void;
  pending: boolean;
}

/** Wszystko, czego wiersze potrzebują od panelu. */
export interface RowContext {
  /** Akcje QC (te same co w oknie QC). `null` = brak wyniku QC dla tej treści. */
  qc: ActionContext | null;
  /** Pokazuje miejsce na kartce; `quiet` = bez komunikatu, gdy miejsca już nie ma. */
  locate: (target: IssueTarget, quiet?: boolean) => void;
  /** Nakłada zdanie AI (z własnym tekstem po edycji). */
  applyFix: (fix: QcFix, text?: string) => void;
  /** Chowa propozycję AI na czas tej sesji. */
  rejectFix: (id: string) => void;
  /** Propozycje AI: liczą się, nie odpowiadają (z „Ponów”) albo są. */
  fixesState: "ready" | "loading" | "failed";
  retryFixes: () => void;
  dismiss: IssueDismiss;
  reviewVersion: number | null;
  /** QC od nowa — po dołączeniu zrzutu zgody RODO, który nie zmienia treści CV. */
  refreshQc: () => void;
}

const SMALL = "h-7 px-1.5 text-xs";

// ── Wspólny kształt wiersza ─────────────────────────────────────────────────

interface RowShellProps {
  kind: string;
  blocking?: boolean;
  title: ReactNode;
  sub?: ReactNode;
  /** Przyciski po prawej (krótkie) albo pod tytułem (`actionsBelow`). */
  actions?: ReactNode;
  actionsBelow?: boolean;
  /** Formularz w wierszu (potwierdzenie, fragment, edycja zdania) — zawsze widoczny, gdy jest. */
  form?: ReactNode;
  details?: ReactNode;
  /** Miejsce na kartce — pokazujemy je przy rozwinięciu wiersza. */
  target?: IssueTarget | null;
  ctx: RowContext;
}

function RowShell({ kind, blocking = false, title, sub, actions, actionsBelow = false, form, details, target, ctx }: RowShellProps) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && target) ctx.locate(target, true);
  };
  return (
    <li
      data-issue-row={kind}
      className={cn(
        "space-y-1.5 px-2.5 py-2",
        blocking && "rounded-lg border border-destructive/30 bg-destructive/5",
      )}
    >
      <div className="flex items-start gap-2">
        {blocking ? <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden /> : null}
        <div className="min-w-0 flex-1 space-y-0.5">
          <button
            type="button"
            aria-expanded={details ? open : undefined}
            aria-controls={details && open ? detailsId : undefined}
            onClick={toggle}
            className={cn(
              "block w-full text-left text-sm leading-snug [overflow-wrap:anywhere] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm",
              blocking ? "font-semibold" : "font-medium",
            )}
          >
            {title}
          </button>
          {sub ? <div className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{sub}</div> : null}
        </div>
        {actions && !actionsBelow ? <div className="flex shrink-0 flex-wrap justify-end gap-1">{actions}</div> : null}
      </div>
      {/* Bez wcięcia pod ikoną: trzy odpowiedzi przy treści spoza oryginału mieszczą się w jednym rzędzie (360 px). */}
      {actions && actionsBelow ? <div className="flex flex-wrap gap-1">{actions}</div> : null}
      {form ? <div className={cn(blocking && "pl-6")}>{form}</div> : null}
      {details && open ? (
        <div id={detailsId} className={cn("space-y-1.5 text-xs", blocking && "pl-6")}>
          {details}
        </div>
      ) : null}
    </li>
  );
}

/** Przyciski drugiego rzędu w rozwiniętym wierszu. */
function DetailActions({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-1">{children}</div>;
}

function LocateButton({ target, ctx }: { target: IssueTarget | null; ctx: RowContext }) {
  if (!target) return null;
  return (
    <Button size="sm" variant="ghost" className={SMALL} onClick={() => ctx.locate(target)}>
      <LocateFixed className="size-3.5" aria-hidden />
      Pokaż w CV
    </Button>
  );
}

// ── Podgląd zdania AI ───────────────────────────────────────────────────────

function Bolded({ text }: { text: string }) {
  return (
    <>
      {parseBoldMarkup(text).map((run, i) =>
        run.b ? (
          <strong key={i} className="font-semibold">
            {run.t}
          </strong>
        ) : (
          <span key={i}>{run.t}</span>
        ),
      )}
    </>
  );
}

/** Skąd jest zdanie AI — „z oryginalnego CV”, „z notatki rekrutera”. */
const FIX_SOURCE_FROM: Record<QcFix["source"], string> = {
  original: "z oryginalnego CV",
  answers: "z odpowiedzi kandydata",
  notes: "z notatki rekrutera",
};

/** „+ zdanie” na zielono i skąd jest — podgląd zmiany przed kliknięciem. */
function ProposalPreview({ fix }: { fix: QcFix }) {
  return (
    <span className="block space-y-0.5">
      {fix.current_text ? <del className="block text-muted-foreground">{fix.current_text}</del> : null}
      <ins className="block rounded-sm bg-success-muted px-1 text-foreground no-underline">
        {fix.current_text ? null : "+ "}
        <Bolded text={fix.proposed_text} />
      </ins>
      <span className="block">{FIX_SOURCE_FROM[fix.source] ?? FIX_SOURCE_FROM.original}</span>
    </span>
  );
}

function proposalTarget(fix: QcFix): IssueTarget | null {
  if (fix.current_text?.trim()) return { kind: "line", text: fix.current_text };
  const label = fix.cv_role_label || fix.role || null;
  const roleIndex = typeof fix.role_index === "number" ? fix.role_index : null;
  return roleIndex != null || label ? { kind: "role", roleIndex, label } : null;
}

/** Edycja zdania AI przed dopisaniem — rozwinięte szczegóły wiersza. */
function EditProposal({ fix, ctx, onClose }: { fix: QcFix; ctx: RowContext; onClose: () => void }) {
  const [text, setText] = useState(fix.proposed_text);
  const fieldId = useId();
  const busy = !ctx.qc || ctx.qc.busy;
  return (
    <form
      className="space-y-1"
      onSubmit={(event) => {
        event.preventDefault();
        if (text.trim()) ctx.applyFix(fix, text.trim());
      }}
    >
      <label htmlFor={fieldId} className="block font-medium">
        Treść zdania
      </label>
      <textarea
        id={fieldId}
        className="min-h-16 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <DetailActions>
        <Button type="submit" size="sm" className={SMALL} disabled={busy || !text.trim()}>
          Dopisz edytowane
        </Button>
        <Button type="button" size="sm" variant="ghost" className={SMALL} onClick={onClose}>
          Anuluj
        </Button>
      </DetailActions>
    </form>
  );
}

/** Przyciski i szczegóły jednej propozycji AI (wiersz pozycji albo luźnej propozycji). */
function useProposal(fix: QcFix | null, ctx: RowContext) {
  const [editing, setEditing] = useState(false);
  if (!fix) return { action: null, details: null };
  const busy = !ctx.qc || ctx.qc.busy || !ctx.qc.editable;
  return {
    action: (
      <Button
        size="sm"
        className={SMALL}
        disabled={busy}
        aria-label={`Dopisz: ${fix.requirement ?? "zdanie"}`}
        onClick={() => ctx.applyFix(fix)}
      >
        Dopisz
      </Button>
    ),
    details: editing ? (
      <EditProposal fix={fix} ctx={ctx} onClose={() => setEditing(false)} />
    ) : (
      <>
        {fix.source_quote ? (
          <p className="border-l-2 border-border pl-2 text-muted-foreground">
            Źródło — <q className="italic">{fix.source_quote}</q>
          </p>
        ) : null}
        <DetailActions>
          <Button size="sm" variant="outline" className={SMALL} disabled={busy} onClick={() => setEditing(true)}>
            Edytuj zdanie
          </Button>
          <Button size="sm" variant="ghost" className={SMALL} onClick={() => ctx.rejectFix(fix.id)}>
            Odrzuć propozycję
          </Button>
          <LocateButton target={proposalTarget(fix)} ctx={ctx} />
        </DetailActions>
      </>
    ),
  };
}

/** Jedno z kilku zdań AI do tej samej uwagi — każde z „Dopisz”, „Edytuj”, „Odrzuć” i „Pokaż w CV”. */
function ProposalLine({ fix, ctx }: { fix: QcFix; ctx: RowContext }) {
  const [editing, setEditing] = useState(false);
  const busy = !ctx.qc || ctx.qc.busy || !ctx.qc.editable;
  const role = fix.cv_role_label || fix.role || "";
  return (
    <li className="space-y-1">
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1">
          {role ? <span className="block font-medium text-foreground">{role}</span> : null}
          <ProposalPreview fix={fix} />
        </span>
        <Button
          size="sm"
          className={SMALL}
          disabled={busy}
          aria-label={`Dopisz: ${fix.requirement ?? "zdanie"}${role ? ` · ${role}` : ""}`}
          onClick={() => ctx.applyFix(fix)}
        >
          Dopisz
        </Button>
      </div>
      {editing ? (
        <EditProposal fix={fix} ctx={ctx} onClose={() => setEditing(false)} />
      ) : (
        <DetailActions>
          <Button size="sm" variant="ghost" className={SMALL} disabled={busy} onClick={() => setEditing(true)}>
            Edytuj zdanie
          </Button>
          <Button size="sm" variant="ghost" className={SMALL} onClick={() => ctx.rejectFix(fix.id)}>
            Odrzuć propozycję
          </Button>
          <LocateButton target={proposalTarget(fix)} ctx={ctx} />
        </DetailActions>
      )}
    </li>
  );
}

/** „Przygotowuję zdanie…” albo „Propozycje AI niedostępne · Ponów” przy pozycji z poprawką AI. */
function PendingFix({ ctx }: { ctx: RowContext }) {
  if (ctx.fixesState === "failed") {
    return (
      <span className="flex flex-wrap items-center gap-1">
        Propozycje AI są chwilowo niedostępne.
        <button type="button" className="font-medium text-primary hover:underline" onClick={ctx.retryFixes}>
          Ponów
        </button>
      </span>
    );
  }
  if (ctx.fixesState === "loading") {
    return (
      <span aria-live="polite" className="flex items-center gap-1">
        <Loader2 className="size-3 animate-spin" aria-hidden />
        Przygotowuję zdanie…
      </span>
    );
  }
  return null;
}

// ── Formularze w wierszu: „Kandydat to ma” i „Jest w oryginale” (D5) ─────────

const CONFIRM_TEXT_MAX = 1000;

function ConfirmInline({ term, qc, onClose }: { term: string; qc: ActionContext; onClose: () => void }) {
  const [text, setText] = useState("");
  const fieldId = useId();
  return (
    <form
      className="space-y-1 rounded-md border border-border bg-card px-2 py-1.5 text-xs"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        const said = text.trim();
        qc.confirm(said ? { term, text: said } : { term }, onClose);
      }}
    >
      <label htmlFor={fieldId} className="block font-medium">
        Co powiedział kandydat? (opcjonalnie)
      </label>
      <div className="flex items-start gap-1">
        <textarea
          id={fieldId}
          rows={1}
          maxLength={CONFIRM_TEXT_MAX}
          className="min-h-8 w-0 flex-1 resize-y rounded-md border border-input bg-background px-2 py-1 text-sm"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Button type="submit" size="sm" className={SMALL} disabled={qc.confirming}>
          {qc.confirming ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
          Zapisz w notatkach
        </Button>
      </div>
      <p className="text-muted-foreground">
        Zapisze się notatka „Potwierdzone z kandydatem: {term}” — QC przyjmie ją jako źródło.{" "}
        <button type="button" className="font-medium text-foreground hover:underline" onClick={onClose}>
          Anuluj
        </button>
      </p>
    </form>
  );
}

function QuoteInline({
  check,
  item,
  qc,
  onClose,
}: {
  check: QcCheck;
  item: QcItem;
  qc: ActionContext;
  onClose: () => void;
}) {
  const [quote, setQuote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fieldId = useId();
  return (
    <form
      className="space-y-1 rounded-md border border-border bg-card px-2 py-1.5 text-xs"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        const problem = qcDismissError("other_name", "", quote);
        setError(problem);
        if (problem) return;
        qc.dismiss({ check_key: check.key, key: item.key ?? "", reason: "other_name", quote: quote.trim() }, onClose);
      }}
    >
      <label htmlFor={fieldId} className="block font-medium">
        Jak to brzmi w oryginale? Wklej fragment
      </label>
      <div className="flex items-start gap-1">
        <textarea
          id={fieldId}
          rows={1}
          maxLength={QC_DISMISS_QUOTE_MAX}
          className="min-h-8 w-0 flex-1 resize-y rounded-md border border-input bg-background px-2 py-1 text-sm"
          value={quote}
          onChange={(event) => setQuote(event.target.value)}
        />
        <Button type="submit" size="sm" className={SMALL} disabled={qc.dismissing}>
          {qc.dismissing ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
          Pomiń uwagę
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}
      <p className="text-muted-foreground">
        Serwer sprawdzi, czy ten fragment stoi w oryginale, notatkach albo odpowiedziach.{" "}
        <button type="button" className="font-medium text-foreground hover:underline" onClick={onClose}>
          Anuluj
        </button>
      </p>
    </form>
  );
}

/** „To nieprawda” przy pozycji QC — klucz pozycji idzie do serwera bez zmian. */
function QcDismiss({ check, item, qc, label }: { check: QcCheck; item: QcItem; qc: ActionContext; label: string }) {
  const [open, setOpen] = useState(false);
  if (!canDismissItem(check, item, qc.canDismissBlocking)) return null;
  if (!open) {
    return (
      <Button size="sm" variant="ghost" className={SMALL} onClick={() => setOpen(true)} disabled={qc.dismissing}>
        <Ban className="size-3.5" aria-hidden />
        To nieprawda
      </Button>
    );
  }
  return (
    <div className="w-full">
      <DismissForm
        subject={label}
        needsQuote={(reason) => dismissNeedsQuote(check.key, reason)}
        blocking={check.severity === "blocking"}
        hint={
          check.key === "no_unsupported"
            ? "Kandydat powiedział o tym w rozmowie? Użyj „Kandydat to ma” — zapisze potwierdzenie w notatkach."
            : undefined
        }
        pending={qc.dismissing}
        onSubmit={(value) => qc.dismiss({ check_key: check.key, key: item.key ?? "", ...value }, () => setOpen(false))}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

function CopyQuestion({ item, qc }: { item: QcItem; qc: ActionContext }) {
  return (
    <Button size="sm" variant="outline" className={SMALL} onClick={() => qc.copyQuestion(item)}>
      <Copy className="size-3.5" aria-hidden />
      Skopiuj pytanie
    </Button>
  );
}

function itemName(item: QcItem): string {
  return (item.requirement ?? item.term ?? "").trim();
}

// ── Blokady ─────────────────────────────────────────────────────────────────

function TaskRow({ task, fixes, ctx }: { task: QcTask; fixes: QcFix[]; ctx: RowContext }) {
  const qc = ctx.qc;
  const [form, setForm] = useState<"confirm" | "quote" | null>(null);
  const proposal = useProposal(fixes.length === 1 ? fixes[0] : null, ctx);
  if (!qc) return null;
  const { check, items, name } = task;
  const first = items[0];
  const title = taskTitle(task);
  const tag = QC_TASK_TAG[check.key];
  const roleItems = items.filter((item) => item.role);
  const target = first ? itemTarget(first) : null;
  const busy = qc.busy || !qc.editable;
  const consent =
    first?.fix === "upload_consent" || first?.fix === "replace_consent" ? consentTarget(qc.data) : null;

  let actions: ReactNode = null;
  let body: ReactNode = null;
  let formNode: ReactNode = null;
  if (check.key === "no_unsupported" && first) {
    const term = (first.term ?? name ?? "").trim();
    const canSkip = canDismissItem(check, first, qc.canDismissBlocking);
    actions = (
      <>
        {term ? (
          <Button
            size="sm"
            variant="outline"
            className={SMALL}
            disabled={busy}
            aria-label={`Usuń z CV: ${term}`}
            onClick={() => qc.apply({ action: "remove_term", term }, `Usunięto „${term}” z CV.`)}
          >
            Usuń z CV
          </Button>
        ) : null}
        {term ? (
          <Button size="sm" variant={form === "confirm" ? "primary" : "outline"} className={SMALL} onClick={() => setForm("confirm")}>
            Kandydat to ma
          </Button>
        ) : null}
        {canSkip ? (
          <Button size="sm" variant={form === "quote" ? "primary" : "outline"} className={SMALL} onClick={() => setForm("quote")}>
            Jest w oryginale
          </Button>
        ) : null}
      </>
    );
    formNode =
      form === "confirm" && term ? (
        <ConfirmInline term={term} qc={qc} onClose={() => setForm(null)} />
      ) : form === "quote" ? (
        <QuoteInline check={check} item={first} qc={qc} onClose={() => setForm(null)} />
      ) : null;
  } else if (fixes.length === 1) {
    actions = proposal.action;
    body = <ProposalPreview fix={fixes[0]} />;
  } else if (fixes.length > 1) {
    body = (
      <ul className="space-y-2" aria-label={`Propozycje: ${name ?? check.label}`}>
        {fixes.map((fix) => (
          <ProposalLine key={fix.id} fix={fix} ctx={ctx} />
        ))}
      </ul>
    );
  } else if (check.key === "critical_skills" && roleItems.length > 0) {
    if (originalDescribesSkill(roleItems)) body = <PendingFix ctx={ctx} />;
    else actions = <CopyQuestion item={roleItems[0]} qc={qc} />;
  } else if (first?.fix === "ai") {
    body = <PendingFix ctx={ctx} />;
  } else if (first?.fix === "ask_candidate") {
    actions = <CopyQuestion item={first} qc={qc} />;
  } else if (first?.fix === "remove_term" && itemName(first)) {
    const term = itemName(first);
    actions = (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        aria-label={`Usuń z CV: ${term}`}
        onClick={() => qc.apply({ action: "remove_term", term }, `Usunięto „${term}” z CV.`)}
      >
        Usuń z CV
      </Button>
    );
  } else if (consent) {
    // Zrzut wgrywa się tu, bez generatora i bez ponownej generacji (PR 4, 17.10.2026).
    actions = (
      <ConsentAttachButton
        compact
        hasConsent={first?.fix === "replace_consent"}
        {...consent}
        onAttached={ctx.refreshQc}
      />
    );
  } else if (first?.fix === "upload_consent" || first?.fix === "generate_cv") {
    actions = <ItemAction item={first} ctx={qc} />;
  } else if (first && itemQuickFix(check, first)?.action === "strip_client_rules") {
    // Stawka i kontakt kandydata: serwer usuwa jednym razem wszystko, co łamie regułę (PR 2).
    const rate = itemSentence(first).startsWith("Stawka");
    actions = (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        onClick={() => qc.apply({ action: "strip_client_rules" }, "Usunięto stawkę i kontakt kandydata z CV.")}
      >
        {rate ? "Usuń stawkę" : "Usuń dane kontaktowe"}
      </Button>
    );
  }

  const details = (
    <>
      {name && first?.detail ? <p className="text-muted-foreground">{first.detail}</p> : null}
      {first ? <SearchedChips searched={first.searched} /> : null}
      {roleItems.length > 1 ? (
        // Każda rola osobno: QC może się mylić tylko co do jednej z nich.
        <ul className="space-y-0.5 text-muted-foreground" aria-label={`Role: ${name ?? check.label}`}>
          {roleItems.map((item, i) => (
            <li key={item.key ?? i} className="flex flex-wrap items-center gap-1">
              <span className="text-foreground">{item.role}</span>
              <LocateButton target={itemTarget(item)} ctx={ctx} />
              <QcDismiss check={check} item={item} qc={qc} label={`${itemName(item) || title} · ${item.role}`} />
            </li>
          ))}
        </ul>
      ) : null}
      {proposal.details}
      <DetailActions>
        {roleItems.length > 1 ? null : <LocateButton target={target} ctx={ctx} />}
        {check.key === "no_unsupported" && first ? <CopyQuestion item={first} qc={qc} /> : null}
        {first && roleItems.length <= 1 ? (
          <QcDismiss
            check={check}
            item={first}
            qc={qc}
            label={itemName(first) ? (first.role ? `${itemName(first)} · ${first.role}` : itemName(first)) : title}
          />
        ) : null}
      </DetailActions>
    </>
  );

  return (
    <RowShell
      kind="task"
      blocking
      title={title}
      sub={
        <>
          {tag ? <span>{tag}</span> : null}
          {body ? <div className="mt-0.5">{body}</div> : null}
        </>
      }
      actions={actions}
      actionsBelow={check.key === "no_unsupported" || roleItems.length > 1}
      form={formNode}
      details={details}
      target={target}
      ctx={ctx}
    />
  );
}

// ── Do poprawy i do decyzji ─────────────────────────────────────────────────

const NAMES_SHOWN = 3;

function namesOf(items: QcItem[]): string {
  const names: string[] = [];
  for (const item of items) {
    const name = itemName(item);
    if (name && !names.includes(name)) names.push(name);
  }
  const rest = names.length - NAMES_SHOWN;
  const head = names.slice(0, NAMES_SHOWN).join(", ");
  return rest > 0 ? `${head} i ${countForm(rest, ["inne", "inne", "innych"])}` : head;
}

function CheckFixRow({ row, ctx }: { row: Extract<IssueRow, { kind: "check-fix" }>; ctx: RowContext }) {
  const qc = ctx.qc;
  if (!qc) return null;
  const { check, fix, items } = row;
  const busy = qc.busy || !qc.editable;
  const scope = check.key === "nice_bolded" ? "nice" : "must";
  const title =
    fix === "bold_all" ? (
      <>Pogrub: {namesOf(items)}</>
    ) : (
      <>
        Pisownia:{" "}
        {items
          .map((item) => item.detail?.trim() || itemName(item))
          .filter(Boolean)
          .join(", ")}
      </>
    );
  const action =
    fix === "bold_all" ? (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        aria-label={`Pogrub wszystkie: ${namesOf(items)}`}
        onClick={() => qc.apply({ action: "bold_all", scope }, "Pogrubiono wszystkie wystąpienia.")}
      >
        Pogrub
      </Button>
    ) : (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        aria-label="Popraw pisownię"
        onClick={() => qc.apply({ action: "spelling" }, "Poprawiono pisownię technologii.")}
      >
        Popraw
      </Button>
    );
  return (
    <RowShell
      kind={fix}
      title={title}
      sub={fix === "bold_all" ? (scope === "nice" ? "Mile widziane bez pogrubienia" : "Wymagania klienta bez pogrubienia") : null}
      actions={action}
      details={
        <ul className="space-y-1">
          {items.map((item, i) => (
            <li key={item.key ?? i} className="flex flex-wrap items-center gap-1">
              <span className="font-medium">{itemName(item) || item.detail}</span>
              <LocateButton target={itemTarget(item)} ctx={ctx} />
              <QcDismiss check={check} item={item} qc={qc} label={itemName(item) || check.label} />
            </li>
          ))}
        </ul>
      }
      target={items[0] ? itemTarget(items[0]) : null}
      ctx={ctx}
    />
  );
}

function ItemRow({ row, ctx }: { row: Extract<IssueRow, { kind: "item" }>; ctx: RowContext }) {
  const qc = ctx.qc;
  const proposal = useProposal(row.fixes[0] ?? null, ctx);
  if (!qc) return null;
  const { check, item, fixes } = row;
  const busy = qc.busy || !qc.editable;
  const name = itemName(item);
  const target = itemTarget(item);
  const label = name ? (item.role ? `${name} · ${item.role}` : name) : item.detail?.trim() || check.label;
  const quick = itemQuickFix(check, item);

  let title: ReactNode = label;
  let sub: ReactNode = item.detail && name ? item.detail : check.label;
  let action: ReactNode = null;
  let extra: ReactNode = null;
  if (item.fix === "role_order") {
    title = "Stanowiska nie od najnowszego";
    sub = item.detail;
    action = (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        onClick={() => qc.apply({ action: "role_order" }, "Ułożono stanowiska od najnowszego.")}
      >
        Ułóż od najnowszego
      </Button>
    );
    // Kolejność to wybór rekrutera, nie „nieprawda” — jedno kliknięcie (D6, 16.10.2026).
    extra = item.key ? (
      <Button
        size="sm"
        variant="ghost"
        className={SMALL}
        disabled={qc.dismissing}
        onClick={() => qc.dismiss({ check_key: check.key, key: item.key ?? "", reason: "kept_order" })}
      >
        Zostaw tę kolejność
      </Button>
    ) : null;
  } else if (item.fix === "remove_term" && name) {
    title = `„${name}”`;
    // api-detail-ok: `QcItem.detail` to zdanie uwagi QC (tekst z kontraktu), nie `detail` błędu API.
    sub = item.detail ?? check.label;
    action = (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        aria-label={`Usuń z CV: ${name}`}
        onClick={() => qc.apply({ action: "remove_term", term: name }, `Usunięto „${name}” z CV.`)}
      >
        Usuń z CV
      </Button>
    );
  } else if (item.fix === "ai") {
    sub = fixes[0] ? <ProposalPreview fix={fixes[0]} /> : <PendingFix ctx={ctx} />;
    action = proposal.action;
  } else if (item.fix === "ask_candidate") {
    action = <CopyQuestion item={item} qc={qc} />;
  } else if (quick?.action === "years") {
    // Liczba z dat historii — ta sama reguła co uwaga QC (PR 2, 17.10.2026).
    const preview = yearsPreview(item);
    title = preview ? (
      <>
        <del>{preview.before}</del> <ins className="rounded-sm bg-success-muted px-0.5 no-underline">{preview.after}</ins>
      </>
    ) : (
      label
    );
    sub = preview ? "Lata w nagłówku · z dat w historii" : item.detail;
    action = (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        aria-label="Zmień lata według historii"
        onClick={() => qc.apply({ action: "years" }, "Lata doświadczenia według historii.")}
      >
        Zmień
      </Button>
    );
  } else if (check.key === "dates" && item.role) {
    // „Rola bez dat.” nie mówi, o którą rolę chodzi (PR 4, 17.10.2026).
    title = `${item.role}: brak dat`;
    sub = check.label;
  } else if (quick?.action === "title") {
    title = (
      <>
        Tytuł CV: <ins className="rounded-sm bg-success-muted px-0.5 no-underline">{name}</ins>
      </>
    );
    sub = "Początek CV nie mówi stanowiska z rekrutacji";
    action = (
      <Button
        size="sm"
        variant="outline"
        className={SMALL}
        disabled={busy}
        aria-label={`Wpisz tytuł: ${name}`}
        onClick={() => qc.apply({ action: "title" }, "Tytuł CV z rekrutacji.")}
      >
        Wpisz
      </Button>
    );
  }

  return (
    <RowShell
      kind={item.fix ?? quick?.action ?? "note"}
      title={title}
      sub={sub}
      actions={action}
      details={
        <>
          {item.fix === "ai" && item.detail ? <p className="text-muted-foreground">{item.detail}</p> : null}
          <SearchedChips searched={item.searched} />
          {proposal.details}
          <DetailActions>
            {extra}
            {fixes[0] ? null : <LocateButton target={target} ctx={ctx} />}
            {item.fix === "role_order" ? null : <QcDismiss check={check} item={item} qc={qc} label={label} />}
          </DetailActions>
        </>
      }
      target={target}
      ctx={ctx}
    />
  );
}

function CheckNoteRow({ check, ctx }: { check: QcCheck; ctx: RowContext }) {
  const qc = ctx.qc;
  if (!qc) return null;
  const preview = notePreview(check) ?? check.summary;
  return (
    <RowShell
      kind="check"
      title={check.label}
      sub={check.status === "manual" ? `Sprawdź ręcznie${preview ? ` · ${preview}` : ""}` : preview}
      details={
        check.items.length > 0 ? (
          <ul className="space-y-1">
            {check.items.map((item, i) => (
              <li key={item.key ?? i} className="space-y-0.5">
                <p>
                  {item.role ? <span className="text-muted-foreground">{item.role} · </span> : null}
                  {itemName(item) ? <span className="font-medium">{itemName(item)}</span> : null}
                  {item.detail ? <span className="text-muted-foreground"> — {item.detail}</span> : null}
                </p>
                <DetailActions>
                  <LocateButton target={itemTarget(item)} ctx={ctx} />
                  <QcDismiss check={check} item={item} qc={qc} label={itemName(item) || check.label} />
                </DetailActions>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">{check.summary ?? "Bez szczegółów."}</p>
        )
      }
      ctx={ctx}
    />
  );
}

function LooseProposalRow({ fix, ctx }: { fix: QcFix; ctx: RowContext }) {
  const proposal = useProposal(fix, ctx);
  const role = fix.cv_role_label || fix.role;
  return (
    <RowShell
      kind="proposal"
      title={[fix.requirement, role].filter(Boolean).join(" · ") || "Zdanie z oryginału"}
      sub={<ProposalPreview fix={fix} />}
      actions={proposal.action}
      details={proposal.details}
      target={proposalTarget(fix)}
      ctx={ctx}
    />
  );
}

/** „To nieprawda” przy uwadze generatora albo kontroli AI — formularz w szczegółach. */
function IssueDismissForm({
  issue,
  subject,
  ctx,
}: {
  issue: Pick<CvIssueDismissBody, "source" | "text" | "status">;
  subject: string;
  ctx: RowContext;
}) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <Button size="sm" variant="ghost" className={SMALL} onClick={() => setOpen(true)} disabled={ctx.dismiss.pending}>
        <Ban className="size-3.5" aria-hidden />
        To nieprawda
      </Button>
    );
  }
  return (
    <div className="w-full">
      <DismissForm
        subject={subject}
        pending={ctx.dismiss.pending}
        onSubmit={(value) => ctx.dismiss.submit(issue, value, () => setOpen(false))}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

function WarningRow({ warning, ctx }: { warning: ClassifiedCvWarning; ctx: RowContext }) {
  const issue = { source: "generator" as const, text: warning.text, status: null };
  // Zdanie po polsku do pokazania; surowy tekst zostaje kluczem pominięcia (18.10.2026).
  const shown = humanizeCvWarning(warning.text);
  return (
    <RowShell
      kind="generator"
      title={shown}
      sub={`Uwaga generatora · ${warning.kind}`}
      actions={
        <Button
          size="sm"
          variant="outline"
          className={SMALL}
          disabled={ctx.dismiss.pending}
          aria-label={`OK, sprawdzone: ${shown}`}
          onClick={() => ctx.dismiss.keep(issue)}
        >
          OK
        </Button>
      }
      details={
        <DetailActions>
          <IssueDismissForm issue={issue} subject={shown} ctx={ctx} />
        </DetailActions>
      }
      ctx={ctx}
    />
  );
}

function FindingRow({ finding, ctx }: { finding: CvReviewFinding; ctx: RowContext }) {
  const issue = { source: "review" as const, text: finding.text, status: finding.status };
  const target: IssueTarget = { kind: "line", text: finding.text };
  const source = ctx.reviewVersion != null ? `${ISSUE_SOURCE_LABEL.review} v${ctx.reviewVersion}` : ISSUE_SOURCE_LABEL.review;
  return (
    <RowShell
      kind="review"
      title={`„${finding.text}”`}
      sub={`${source} · ${REVIEW_FINDING_LABEL[finding.status] ?? "do sprawdzenia"}`}
      actions={
        <>
          {/* „Prawie to samo jest w źródłach” (D1-A) — usuwanie jednym kliknięciem skasowałoby prawdę. */}
          {ctx.qc && finding.status !== "weak" ? (
            <Button
              size="sm"
              variant="outline"
              className={SMALL}
              disabled={ctx.qc.busy || !ctx.qc.editable}
              aria-label={`Usuń zdanie: „${finding.text}”`}
              onClick={() =>
                ctx.qc?.apply({ action: "remove_line", text: finding.text }, "Usunięto zdanie bez pokrycia.")
              }
            >
              Usuń zdanie
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            className={SMALL}
            disabled={ctx.dismiss.pending}
            aria-label={`Zostaw: „${finding.text}”`}
            onClick={() => ctx.dismiss.keep(issue)}
          >
            Zostaw
          </Button>
        </>
      }
      details={
        <DetailActions>
          <LocateButton target={target} ctx={ctx} />
          <IssueDismissForm issue={issue} subject={`„${finding.text}”`} ctx={ctx} />
        </DetailActions>
      }
      target={target}
      ctx={ctx}
    />
  );
}

/** Jeden wiersz listy po rodzaju. */
export function IssueRowView({ row, ctx }: { row: IssueRow; ctx: RowContext }) {
  switch (row.kind) {
    case "task":
      return <TaskRow task={row.task} fixes={row.fixes} ctx={ctx} />;
    case "check-fix":
      return <CheckFixRow row={row} ctx={ctx} />;
    case "item":
      return <ItemRow row={row} ctx={ctx} />;
    case "check":
      return <CheckNoteRow check={row.check} ctx={ctx} />;
    case "proposal":
      return <LooseProposalRow fix={row.fix} ctx={ctx} />;
    case "warning":
      return <WarningRow warning={row.warning} ctx={ctx} />;
    case "finding":
      return <FindingRow finding={row.finding} ctx={ctx} />;
  }
}
