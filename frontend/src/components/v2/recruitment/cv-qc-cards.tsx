"use client";

/**
 * Karty QC CV — wspólne dla okna QC (`CvQcDialog`) i panelu „Do poprawy”
 * w edytorze CV (`cv-editor/CvEditorIssuesPanel`, Edytor CV 2, PR 2).
 *
 * Karty nie wiedzą, kto nakłada poprawkę: dostają `ActionContext`. Okno QC
 * zapisuje ją w szkicu na serwerze (`qc/apply`), edytor liczy ją na treści
 * z ekranu i nakłada jednym cofalnym krokiem (`qc/transform`). „Pokaż w CV”
 * pojawia się tylko tam, gdzie kontekst podaje `locate`.
 *
 * Propozycje AI (D5, 14.10.2026) ładują się same, gdy jest pozycja z poprawką
 * AI — serwer liczy je zaraz po automacie, więc zwykle to odczyt z pamięci.
 * Przycisku „Zaproponuj poprawki (AI)” już nie ma; zostaje „Ponów” po awarii.
 *
 * „To nieprawda” (D5, 13.10.2026): przy pozycji, którą da się pominąć, jest
 * przycisk z formularzem powodu; pominięte pozycje stoją zwinięte w „Pominięte”
 * z „Przywróć”. Uwagę blokującą pomija tylko osoba z prawem obejścia
 * (`canDismissBlocking`), brak CV i reguł klienta — nikt. Uwagi wyciszone
 * w „Jakość QC” (D6) stoją osobno jako informacja.
 *
 * Treść CV, dowodów i propozycji to TEKST — nic nie trafia na stronę jako HTML.
 */

import Link from "next/link";
import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronDown,
  Copy,
  HelpCircle,
  Info,
  Loader2,
  LocateFixed,
  MinusCircle,
  RefreshCw,
  Sparkles,
  Undo2,
  XCircle,
} from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConsentAttachButton } from "@/components/v2/cv-generator/ConsentAttachButton";
import { CvGeneratorDialog } from "@/components/v2/cv-generator/CvGeneratorDialog";
import { ConsentScreenshotThumb } from "@/components/v2/cv/ConsentScreenshotThumb";
import type {
  QcCheck,
  QcConfirmBody,
  QcConfirmation,
  QcDismissal,
  QcDismissBody,
  QcDismissReason,
  QcFix,
  QcFixAction,
  QcFixesResponse,
  QcItem,
  QcResult,
  QcSearch,
} from "@/lib/api/cvQc";
import { cvQcQueryKey } from "@/lib/api/cvQc";
import {
  CV_NOT_EDITABLE_MESSAGE,
  QC_DISMISS_NOTE_MAX,
  QC_DISMISS_QUOTE_MAX,
  QC_DISMISS_REASONS,
  QC_FIX_SOURCE_LABEL,
  QC_ROLE_STATE_LABEL,
  QC_SEARCH_SOURCE_LABEL,
  QC_TASK_TAG,
  canDismissItem,
  checkLevelFixes,
  companyCvRoleState,
  dismissNeedsQuote,
  dismissedQcItems,
  groupRoleStates,
  itemTarget,
  notePreview,
  originalDescribesSkill,
  parseBoldMarkup,
  qcDismissError,
  taskTitle,
  type IssueTarget,
  type QcTask,
} from "@/lib/cv-qc";
import { consentTarget } from "@/lib/cv-editor-issues";
import { cn, formatDate } from "@/lib/utils";

export const SECTION_TITLE = "text-xs font-semibold uppercase tracking-wider text-muted-foreground";

/** Uwaga wyciszona w „Jakość QC”, która nadal coś zgłasza — informacja, nie uwaga. */
const isMutedNote = (check: QcCheck) => check.muted === true && (check.status === "fail" || check.status === "manual");

function StatusIcon({ status, muted = false }: { status: QcCheck["status"]; muted?: boolean }) {
  if (muted) return <Info className="size-4 text-info" aria-label="Informacja" />;
  if (status === "pass") return <CheckCircle2 className="size-4 text-success" aria-label="Przechodzi" />;
  if (status === "fail") return <AlertTriangle className="size-4 text-warning" aria-label="Warto poprawić" />;
  if (status === "manual")
    return <HelpCircle className="size-4 text-info" aria-label="Do sprawdzenia ręcznie" />;
  return <MinusCircle className="size-4 text-muted-foreground" aria-label="Nie dotyczy" />;
}

function statusBadge(check: QcCheck) {
  if (isMutedNote(check)) return <Badge variant="info" size="sm">informacja</Badge>;
  if (check.status === "pass") return <Badge variant="success" size="sm">{check.summary || "OK"}</Badge>;
  if (check.status === "manual") return <Badge variant="info" size="sm">sprawdź ręcznie</Badge>;
  if (check.status === "skip") return <Badge variant="outline" size="sm">nie dotyczy</Badge>;
  const n = check.items.length;
  return (
    <Badge variant="warning" size="sm">
      {check.summary || (n === 1 ? "1 pozycja" : `${n} pozycje`)}
    </Badge>
  );
}

export interface ActionContext {
  data: QcResult;
  editable: boolean;
  busy: boolean;
  apply: (body: QcFixAction, success: string, onApplied?: () => void) => void;
  /** „Potwierdzone z kandydatem” — działa także, gdy CV nie da się edytować. */
  confirm: (body: QcConfirmBody, onSaved?: () => void) => void;
  confirming: boolean;
  /** Przewija do sekcji „Propozycje AI” (propozycje ładują się same). */
  requestAiFixes: () => void;
  copyQuestion: (item: QcItem) => void;
  /** Edytor sprawdzanego CV — `null`, gdy tego CV nie da się edytować w NEXUSIE. */
  openEditor: (() => void) | null;
  /** „Pokaż w CV” — tylko w edytorze CV, gdzie tekst stoi obok listy. */
  locate?: (target: IssueTarget) => void;
  /** Odnośniki poza listę otwierają nową kartę (edytor CV zostaje otwarty). */
  linksInNewTab?: boolean;
  /** „To nieprawda” — pominięcie pozycji dla pary; świeży wynik QC zastępuje listę. */
  dismiss: (body: QcDismissBody, onSaved?: () => void) => void;
  dismissing: boolean;
  /** Czy ta osoba pomija uwagi blokujące (`can_override` z wyniku) — działa to jak obejście. */
  canDismissBlocking: boolean;
  /** „Przywróć” przy pominiętej pozycji (id pominięcia). */
  restore: (dismissalId: number) => void;
  restoring: boolean;
}

const newTab = (ctx: ActionContext) => (ctx.linksInNewTab ? { target: "_blank", rel: "noreferrer" } : {});

function LocateButton({ target, ctx }: { target: IssueTarget | null; ctx: ActionContext }) {
  const locate = ctx.locate;
  if (!locate || !target) return null;
  return (
    <Button size="sm" variant="ghost" onClick={() => locate(target)}>
      <LocateFixed className="size-3.5" aria-hidden />
      Pokaż w CV
    </Button>
  );
}

/**
 * Generator CV w oknie, z osobą i rekrutacją z QC. Osobnego ekranu
 * `/cv-generator` nie ma w menu od 13.10.2026 (CV powstaje w ścieżce
 * rekrutacji), więc QC nie wyprowadza na niego, tylko otwiera to samo okno
 * co karta „CV do klienta” w panelu osoby.
 */
function GeneratorOpener({ data, children }: { data: QcResult; children: (open: () => void) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const { showSuccess } = useToast();
  return (
    <>
      {children(() => setOpen(true))}
      {open ? (
        <CvGeneratorDialog
          open
          onOpenChange={setOpen}
          candidateId={data.candidate_id}
          candidateName={data.candidate_name}
          jobId={data.job_id}
          onEnqueued={() => {
            setOpen(false);
            showSuccess(
              "CV generuje się w tle. Gdy etap nie ma jeszcze CV do klienta, gotowy dokument zostanie do niego podpięty.",
            );
          }}
        />
      ) : null}
    </>
  );
}

function CheckActions({ check, ctx }: { check: QcCheck; ctx: ActionContext }) {
  // Poprawki AI ładują się same w sekcji „Propozycje AI” (D5, 14.10.2026) —
  // bez przycisku „Zaproponuj poprawki (AI)” przy sprawdzeniu.
  const kinds = checkLevelFixes(check).filter((kind) => kind !== "ai");
  if (kinds.length === 0 || check.status === "pass") return null;
  return (
    <div className="flex flex-wrap gap-2">
      {kinds.map((kind) => {
        if (kind === "bold_all") {
          const scope = check.key === "nice_bolded" ? "nice" : "must";
          return (
            <Button
              key={kind}
              size="sm"
              disabled={!ctx.editable || ctx.busy}
              onClick={() => ctx.apply({ action: "bold_all", scope }, "Pogrubiono wszystkie wystąpienia.")}
            >
              Pogrub wszystkie
            </Button>
          );
        }
        if (kind === "spelling") {
          return (
            <Button
              key={kind}
              size="sm"
              variant="outline"
              disabled={!ctx.editable || ctx.busy}
              onClick={() => ctx.apply({ action: "spelling" }, "Poprawiono pisownię technologii.")}
            >
              Popraw pisownię
            </Button>
          );
        }
        return null;
      })}
    </div>
  );
}

function RemoveTermButton({ term, ctx }: { term: string; ctx: ActionContext }) {
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={!ctx.editable || ctx.busy}
      onClick={() => ctx.apply({ action: "remove_term", term }, `Usunięto „${term}” z CV.`)}
    >
      Usuń „{term}” z CV
    </Button>
  );
}

function AskCandidateButtons({ item, ctx }: { item: QcItem; ctx: ActionContext }) {
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => ctx.copyQuestion(item)}>
        <Copy className="size-3.5" aria-hidden />
        Skopiuj pytanie do kandydata
      </Button>
      <Button asChild size="sm" variant="ghost">
        <Link href={`/candidates/${ctx.data.candidate_id}`} {...newTab(ctx)}>
          Profil kandydata
        </Link>
      </Button>
    </>
  );
}

/**
 * Przycisk naprawy jednej pozycji — wspólny z wierszami panelu „Do poprawy”
 * w edytorze CV (17.10.2026), który bierze z niego zgodę RODO i brak CV.
 */
export function ItemAction({ item, ctx }: { item: QcItem; ctx: ActionContext }) {
  const term = (item.term ?? item.requirement ?? "").trim();
  switch (item.fix) {
    case "role_order":
      return (
        <Button
          size="sm"
          disabled={!ctx.editable || ctx.busy}
          onClick={() => ctx.apply({ action: "role_order" }, "Ułożono stanowiska od najnowszego.")}
        >
          Ułóż od najnowszego
        </Button>
      );
    case "remove_term":
      return term ? <RemoveTermButton term={term} ctx={ctx} /> : null;
    case "ask_candidate":
      return (
        <span className="flex flex-wrap gap-2">
          <AskCandidateButtons item={item} ctx={ctx} />
        </span>
      );
    case "replace_consent":
      return (
        <span className="flex flex-wrap items-center gap-2">
          <ConsentScreenshotThumb stageId={ctx.data.stage_id} />
          <ConsentReplaceAction ctx={ctx} />
        </span>
      );
    case "upload_consent":
      return (
        <span className="text-xs text-muted-foreground">
          Zrzut zgody RODO wgrywa się w generatorze CV —{" "}
          <GeneratorOpener data={ctx.data}>
            {(open) => (
              <button type="button" className="font-medium text-primary hover:underline" onClick={open}>
                otwórz generator
              </button>
            )}
          </GeneratorOpener>
          , wgraj zrzut i wygeneruj CV ponownie.
        </span>
      );
    case "generate_cv":
      return (
        <GeneratorOpener data={ctx.data}>
          {(open) => (
            <Button size="sm" onClick={open}>
              Wygeneruj CV
            </Button>
          )}
        </GeneratorOpener>
      );
    default:
      return null;
  }
}

/** Rola z brakiem: na czym w oryginale stoi wymóg opisu i co jest w CV firmowym. */
function RoleEvidence({ item, ctx, onDismiss }: { item: QcItem; ctx: ActionContext; onDismiss?: () => void }) {
  const evidence = item.evidence?.trim();
  return (
    <li className="space-y-1 rounded-md border border-border bg-card px-2.5 py-2">
      <span className="flex flex-wrap items-center justify-between gap-1.5">
        <Badge variant="outline" size="sm">
          {item.role}
        </Badge>
        <span className="flex flex-wrap items-center gap-1">
          <LocateButton target={itemTarget(item)} ctx={ctx} />
          {onDismiss ? <DismissButton onClick={onDismiss} disabled={ctx.dismissing} /> : null}
        </span>
      </span>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-xs">
        {evidence ? (
          <>
            <dt className="text-muted-foreground">W oryginale</dt>
            <dd className="min-w-0 [overflow-wrap:anywhere]">
              {item.evidence_kind === "technologies" ? (
                `lista technologii tej roli: ${evidence}`
              ) : item.evidence_kind === "title" ? (
                `nazwa stanowiska: ${evidence}`
              ) : (
                <span className="italic">„{evidence}”</span>
              )}
            </dd>
          </>
        ) : null}
        <dt className="text-muted-foreground">W CV firmowym</dt>
        <dd>{companyCvRoleState(item)}</dd>
      </dl>
    </li>
  );
}

/**
 * „Szukałem w: …” — gdzie QC szukało pozycji i co znalazło. Bez tego rekruter
 * nie wie, czy „brak w oryginale” to prawda, czy zapis, którego QC nie zna.
 */
export function SearchedChips({ searched }: { searched?: QcSearch[] | null }) {
  if (!searched?.length) return null;
  const quotes = searched.filter((entry) => entry.found && entry.quote?.trim());
  return (
    <div className="space-y-1 text-xs">
      <p className="flex flex-wrap items-center gap-1" aria-label="Gdzie QC szukało">
        <span className="text-muted-foreground">Szukałem w:</span>
        {searched.map((entry) => (
          <Badge key={entry.source} variant={entry.found ? "success" : "outline"} size="sm">
            {QC_SEARCH_SOURCE_LABEL[entry.source]} {entry.found ? "✓" : "—"}
            <span className="sr-only">{entry.found ? "znaleziono" : "brak"}</span>
          </Badge>
        ))}
      </p>
      {quotes.map((entry) => (
        <p key={entry.source} className="border-l-2 border-border pl-2 text-muted-foreground [overflow-wrap:anywhere]">
          {QC_SEARCH_SOURCE_LABEL[entry.source]}: <q className="italic">{entry.quote}</q>
        </p>
      ))}
    </div>
  );
}

/** Informacje sprawdzenia — bez zadania, nie liczą się do uwag ani bramki. */
function InfoItems({ items }: { items: QcItem[] }) {
  if (items.length === 0) return null;
  return (
    <div role="group" aria-label="Informacje" className="space-y-1 text-xs">
      <p className="font-semibold text-muted-foreground">Informacje — bez poprawki</p>
      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={item.key ?? i} className="flex gap-1.5 text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0 text-info" aria-hidden />
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {item.role ? <span className="text-foreground">{item.role} · </span> : null}
              {item.requirement || item.term ? (
                <span className="font-medium text-foreground">{item.requirement ?? item.term}</span>
              ) : null}
              {item.detail ? ` — ${item.detail}` : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const CONFIRM_TEXT_MAX = 1000;

/** Formularz „Potwierdzone z kandydatem” w karcie treści spoza oryginału. */
function ConfirmForm({ term, ctx, onClose }: { term: string; ctx: ActionContext; onClose: () => void }) {
  const [text, setText] = useState("");
  const fieldId = useId();
  return (
    <form
      className="space-y-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        const said = text.trim();
        ctx.confirm(said ? { term, text: said } : { term }, onClose);
      }}
    >
      <label htmlFor={fieldId} className="block text-xs font-medium">
        Co powiedział kandydat? (opcjonalnie)
      </label>
      <textarea
        id={fieldId}
        className="min-h-16 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
        maxLength={CONFIRM_TEXT_MAX}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={ctx.confirming}>
          {ctx.confirming ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
          Zapisz potwierdzenie
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onClose} disabled={ctx.confirming}>
          Anuluj
        </Button>
      </div>
    </form>
  );
}

// ── „To nieprawda” ──────────────────────────────────────────────────────────

export function DismissButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return (
    <Button size="sm" variant="ghost" onClick={onClick} disabled={disabled}>
      <Ban className="size-3.5" aria-hidden />
      To nieprawda
    </Button>
  );
}

/** Powód z formularza „To nieprawda” — bez pustego opisu i fragmentu. */
export interface DismissFormValue {
  reason: QcDismissReason;
  note?: string;
  quote?: string;
}

export interface DismissFormProps {
  /** Czego dotyczy pominięcie — zdanie nad powodami. */
  subject: string;
  /** Czy przy tym powodzie trzeba wkleić fragment źródła. */
  needsQuote?: (reason: QcDismissReason | null) => boolean;
  /** Uwaga blokująca — pominięcie działa jak obejście. */
  blocking?: boolean;
  /** Dodatkowa wskazówka pod powodami. */
  hint?: React.ReactNode;
  pending: boolean;
  onSubmit: (value: DismissFormValue) => void;
  onClose: () => void;
}

/** Formularz „To nieprawda”: powód (5 gotowych), opis i — gdy trzeba — fragment źródła. */
export function DismissForm({ subject, needsQuote, blocking = false, hint, pending, onSubmit, onClose }: DismissFormProps) {
  const [reason, setReason] = useState<QcDismissReason | null>(null);
  const [note, setNote] = useState("");
  const [quote, setQuote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const baseId = useId();
  const noteId = `${baseId}-note`;
  const quoteId = `${baseId}-quote`;
  const quoteHintId = `${baseId}-quote-hint`;
  const quoteNeeded = needsQuote?.(reason) ?? false;
  return (
    <form
      aria-label={`To nieprawda: ${subject}`}
      className="space-y-2 rounded-md border border-border bg-card px-2.5 py-2 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        const problem = qcDismissError(reason, note, quoteNeeded ? quote : null);
        setError(problem);
        if (problem || !reason) return;
        const cleanNote = note.trim();
        onSubmit({
          reason,
          ...(cleanNote ? { note: cleanNote } : {}),
          ...(quoteNeeded ? { quote: quote.trim() } : {}),
        });
      }}
    >
      <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
        Oznaczasz jako nieprawdę: <span className="font-medium text-foreground">{subject}</span>
      </p>
      {blocking ? (
        <p className="rounded-md border border-warning/40 bg-warning-muted px-2 py-1.5 text-xs text-warning-muted-foreground">
          To uwaga blokująca — pominięcie działa jak przepuszczenie mimo QC, a Delivery Lead dostanie powiadomienie.
        </p>
      ) : null}
      <fieldset className="space-y-1">
        <legend className="text-xs font-medium">Dlaczego to nieprawda?</legend>
        {QC_DISMISS_REASONS.map((option) => (
          <label key={option.code} className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              type="radio"
              name={`${baseId}-reason`}
              value={option.code}
              checked={reason === option.code}
              onChange={() => {
                setReason(option.code);
                setError(null);
              }}
              className="mt-1 accent-primary"
            />
            <span>{option.label}</span>
          </label>
        ))}
      </fieldset>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {quoteNeeded ? (
        <div className="space-y-1">
          <label htmlFor={quoteId} className="block text-xs font-medium">
            Fragment źródła
          </label>
          <p id={quoteHintId} className="text-xs text-muted-foreground">
            Wklej fragment oryginału, notatki albo odpowiedzi, w którym to stoi — serwer go sprawdzi.
          </p>
          <textarea
            id={quoteId}
            aria-describedby={quoteHintId}
            className="min-h-14 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            maxLength={QC_DISMISS_QUOTE_MAX}
            value={quote}
            onChange={(event) => setQuote(event.target.value)}
          />
        </div>
      ) : null}
      <div className="space-y-1">
        <label htmlFor={noteId} className="block text-xs font-medium">
          {reason === "other" ? "Opis (wymagany)" : "Opis (opcjonalnie)"}
        </label>
        <textarea
          id={noteId}
          className="min-h-14 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          maxLength={QC_DISMISS_NOTE_MAX}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
          Oznacz jako nieprawdę
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onClose} disabled={pending}>
          Anuluj
        </Button>
      </div>
    </form>
  );
}

/** Nazwa pozycji w formularzu i na liście „Pominięte”: wymaganie albo termin, rola. */
function qcItemSubject(check: QcCheck, item: QcItem): string {
  const name = (item.requirement ?? item.term ?? "").trim() || item.detail?.trim() || check.label;
  return item.role ? `${name} · ${item.role}` : name;
}

/** „To nieprawda” przy pozycji QC — klucz pozycji z wyniku idzie do serwera bez zmian. */
function QcDismissForm({
  check,
  item,
  ctx,
  onClose,
}: {
  check: QcCheck;
  item: QcItem;
  ctx: ActionContext;
  onClose: () => void;
}) {
  return (
    <DismissForm
      subject={qcItemSubject(check, item)}
      needsQuote={(reason) => dismissNeedsQuote(check.key, reason)}
      blocking={check.severity === "blocking"}
      hint={
        check.key === "no_unsupported"
          ? "Kandydat powiedział o tym w rozmowie? Zapisz to przez „Potwierdzone z kandydatem”, nie tutaj."
          : undefined
      }
      pending={ctx.dismissing}
      onSubmit={(value) => ctx.dismiss({ check_key: check.key, key: item.key ?? "", ...value }, onClose)}
      onClose={onClose}
    />
  );
}

/**
 * Zrzut zgody, którego AI nie potwierdziło (F37): wymiana wprost z okna QC,
 * bez generatora. Delivery Lead przyjmuje zrzut przez „To OK” obok.
 */
function ConsentReplaceAction({ ctx }: { ctx: ActionContext }) {
  const queryClient = useQueryClient();
  const target = consentTarget(ctx.data);
  if (!target || !ctx.editable) return null;
  return (
    <ConsentAttachButton
      compact
      hasConsent
      {...target}
      onAttached={() => void queryClient.invalidateQueries({ queryKey: cvQcQueryKey(ctx.data.stage_id) })}
    />
  );
}

/** Czy `ItemAction` coś rysuje dla tej pozycji (poprawki całego sprawdzenia stoją niżej). */
function itemHasAction(item: QcItem): boolean {
  if (item.fix === "remove_term") return Boolean((item.term ?? item.requirement ?? "").trim());
  return (
    item.fix === "ask_candidate" ||
    item.fix === "upload_consent" ||
    item.fix === "replace_consent" ||
    item.fix === "generate_cv" ||
    item.fix === "role_order"
  );
}

/**
 * Mała etykieta źródła pozycji („QC”, „generator”, „kontrola AI”) — jedna lista
 * „Do poprawy” w edytorze CV łączy trzy źródła (13.10.2026). Okno QC jej nie
 * podaje.
 */
export function SourceTag({ label }: { label: string }) {
  return (
    <Badge variant="outline" size="sm" className="font-normal text-muted-foreground" data-issue-source={label}>
      {label}
    </Badge>
  );
}

/** Jedna rzecz do poprawy przed wysłaniem: co jest nie tak, gdzie i przycisk naprawy. */
export function TaskCard({ task, ctx, sourceLabel }: { task: QcTask; ctx: ActionContext; sourceLabel?: string }) {
  const { check, name, items } = task;
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Klucz pozycji, której formularz „To nieprawda” jest otwarty.
  const [dismissKey, setDismissKey] = useState<string | null>(null);
  const title = taskTitle(task);
  const roleItems = items.filter((i) => i.role);
  const first = items[0];
  const dismissable = items.filter((item) => canDismissItem(check, item, ctx.canDismissBlocking));
  const openDismiss = (key: string) => {
    setConfirmOpen(false);
    setDismissKey(key);
  };
  // Kilka ról z brakiem — przycisk przy każdej roli; inaczej karta pokazuje
  // jedną pozycję i przycisk stoi w wierszu akcji.
  const perRole = check.key === "critical_skills" && roleItems.length > 1;
  const single = !perRole && first && dismissable.includes(first) ? first : null;
  const dismissButton =
    single && dismissKey !== single.key ? (
      <DismissButton onClick={() => openDismiss(single.key ?? "")} disabled={ctx.dismissing} />
    ) : null;
  const dismissItem = dismissKey ? items.find((item) => item.key === dismissKey) ?? null : null;
  const editorButton = ctx.openEditor ? (
    <Button size="sm" variant="outline" onClick={ctx.openEditor}>
      Poprawię w edytorze
    </Button>
  ) : null;

  let body: React.ReactNode = null;
  let actions: React.ReactNode = null;
  let form: React.ReactNode = null;
  if (check.key === "critical_skills" && roleItems.length > 0) {
    const where = roleItems.length === 1 ? "tej roli" : "tych rolach";
    // Bez zdania w oryginale AI nie ma z czego pisać — zostaje pytanie do kandydata.
    const described = originalDescribesSkill(roleItems);
    body = (
      <>
        <p className="text-xs text-muted-foreground">
          {described
            ? `Oryginalne CV pokazuje tę umiejętność w ${where}. W CV firmowym brakuje tam zdania o tym, co kandydat z nią robił.`
            : `Oryginalne CV wymienia tę umiejętność w ${where}, ale nie opisuje, co kandydat z nią robił. Zapytaj kandydata — AI ułoży zdanie dopiero wtedy, gdy powiedzą o tym notatki.`}
        </p>
        <ul className="space-y-1.5" aria-label={`Role bez opisu: ${name}`}>
          {roleItems.map((item, i) => (
            <RoleEvidence
              key={item.key ?? i}
              item={item}
              ctx={ctx}
              onDismiss={
                perRole && item.key && dismissKey !== item.key && dismissable.includes(item)
                  ? () => openDismiss(item.key ?? "")
                  : undefined
              }
            />
          ))}
        </ul>
      </>
    );
    actions = (
      <>
        {described ? (
          <Button size="sm" disabled={!ctx.editable} onClick={ctx.requestAiFixes}>
            <Sparkles className="size-3.5" aria-hidden />
            Dopisz zdania z oryginału (AI)
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => ctx.copyQuestion(roleItems[0])}>
            <Copy className="size-3.5" aria-hidden />
            Skopiuj pytanie do kandydata
          </Button>
        )}
        {editorButton}
      </>
    );
  } else if (check.key === "no_unsupported" && first) {
    const term = (first.term ?? name ?? "").trim();
    // Tytuł mówi już, co jest nie tak — niżej tylko, co z tym zrobić.
    body = (
      <>
        <p className="text-xs text-muted-foreground">
          Oryginalne CV, odpowiedzi ze screeningu i notatki z rozmów o tym nie wspominają. Usuń to z CV albo potwierdź
          u kandydata i zapisz potwierdzenie.
        </p>
        <SearchedChips searched={first.searched} />
      </>
    );
    actions = (
      <>
        {term ? <RemoveTermButton term={term} ctx={ctx} /> : null}
        <AskCandidateButtons item={first} ctx={ctx} />
        {term && !confirmOpen ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setDismissKey(null);
              setConfirmOpen(true);
            }}
          >
            Potwierdzone z kandydatem
          </Button>
        ) : null}
        <LocateButton target={itemTarget(first)} ctx={ctx} />
      </>
    );
    form = term && confirmOpen ? <ConfirmForm term={term} ctx={ctx} onClose={() => setConfirmOpen(false)} /> : null;
  } else if (first) {
    // Bez nazwy tytułem jest samo zdanie pozycji — nie powtarzamy go niżej.
    const detail = name && first.detail ? <p className="text-xs text-muted-foreground">{first.detail}</p> : null;
    body =
      detail || first.searched?.length ? (
        <>
          {detail}
          <SearchedChips searched={first.searched} />
        </>
      ) : null;
    const where = ctx.locate ? itemTarget(first) : null;
    const action = first.fix ? <ItemAction item={first} ctx={ctx} /> : editorButton;
    actions =
      action || where ? (
        <>
          {action}
          <LocateButton target={where} ctx={ctx} />
        </>
      ) : null;
  }

  if (dismissItem) {
    form = <QcDismissForm check={check} item={dismissItem} ctx={ctx} onClose={() => setDismissKey(null)} />;
  }

  return (
    <li className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5">
      <p className="flex flex-wrap items-center gap-1.5">
        <XCircle className="size-4 shrink-0 text-destructive" aria-hidden />
        <span className="min-w-0 text-sm font-semibold">{title}</span>
        {QC_TASK_TAG[check.key] ? (
          <Badge variant="danger" size="sm">
            {QC_TASK_TAG[check.key]}
          </Badge>
        ) : null}
        {sourceLabel ? <SourceTag label={sourceLabel} /> : null}
      </p>
      {body}
      {actions || dismissButton ? (
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {dismissButton}
        </div>
      ) : null}
      {form}
    </li>
  );
}

export function CheckRow({ check, ctx, sourceLabel }: { check: QcCheck; ctx: ActionContext; sourceLabel?: string }) {
  const [open, setOpen] = useState(false);
  const [dismissKey, setDismissKey] = useState<string | null>(null);
  const roleGroups = groupRoleStates(check.roles ?? []);
  const info = check.info ?? [];
  const hasBody =
    check.items.length > 0 || checkLevelFixes(check).length > 0 || roleGroups.length > 0 || info.length > 0;
  // `useId`: okno QC i panel w edytorze CV bywają otwarte naraz.
  const bodyId = useId();
  const preview = check.status === "fail" || check.status === "manual" ? notePreview(check) ?? check.summary : null;
  return (
    <li className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        onClick={() => hasBody && setOpen((v) => !v)}
        aria-expanded={hasBody ? open : undefined}
        aria-controls={hasBody ? bodyId : undefined}
        className={cn(
          "grid w-full grid-cols-[20px_1fr_auto] items-center gap-3 px-3 py-2 text-left",
          open && hasBody && "border-b border-border bg-muted/40",
          !hasBody && "cursor-default",
        )}
      >
        <StatusIcon status={check.status} muted={isMutedNote(check)} />
        <span className="min-w-0">
          <span className="block text-sm font-medium">{check.label}</span>
          {preview && !open ? (
            <span className="block truncate text-xs text-muted-foreground">{preview}</span>
          ) : null}
        </span>
        <span className="flex items-center gap-1.5">
          {sourceLabel ? <SourceTag label={sourceLabel} /> : null}
          {statusBadge(check)}
          {hasBody ? (
            <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
          ) : null}
        </span>
      </button>
      {open && hasBody ? (
        <div id={bodyId} className="space-y-2 px-3 py-2.5">
          {check.items.map((item, i) => {
            const canDismiss = canDismissItem(check, item, ctx.canDismissBlocking);
            const formOpen = canDismiss && item.key != null && dismissKey === item.key;
            const where = ctx.locate ? itemTarget(item) : null;
            return (
              <div key={item.key ?? i} className="space-y-1.5 rounded-md border border-border/70 px-2.5 py-2 text-sm">
                <p className="flex flex-wrap items-center gap-1.5">
                  {item.role ? (
                    <Badge variant="outline" size="sm">
                      {item.role}
                    </Badge>
                  ) : null}
                  {item.requirement || item.term ? (
                    <span className="font-medium">{item.requirement ?? item.term}</span>
                  ) : null}
                </p>
                {item.detail ? <p className="text-xs text-muted-foreground">{item.detail}</p> : null}
                <SearchedChips searched={item.searched} />
                {where || (canDismiss && !formOpen) ? (
                  <div className="flex flex-wrap items-center gap-2">
                    {itemHasAction(item) ? <ItemAction item={item} ctx={ctx} /> : null}
                    <LocateButton target={where} ctx={ctx} />
                    {canDismiss && !formOpen ? (
                      item.fix === "role_order" ? (
                        // Kolejność stanowisk to wybór rekrutera, nie „nieprawda” —
                        // jedno kliknięcie, bez formularza powodu (D6, 16.10.2026).
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={ctx.dismissing}
                          onClick={() => ctx.dismiss({ check_key: check.key, key: item.key ?? "", reason: "kept_order" })}
                        >
                          Zostaw tę kolejność
                        </Button>
                      ) : (
                        <DismissButton onClick={() => setDismissKey(item.key ?? null)} disabled={ctx.dismissing} />
                      )
                    ) : null}
                  </div>
                ) : (
                  <ItemAction item={item} ctx={ctx} />
                )}
                {formOpen ? (
                  <QcDismissForm check={check} item={item} ctx={ctx} onClose={() => setDismissKey(null)} />
                ) : null}
              </div>
            );
          })}
          {roleGroups.length > 0 ? (
            <div role="group" aria-label="Rola po roli" className="space-y-1.5 text-xs">
              <p className="font-semibold text-muted-foreground">Rola po roli</p>
              {roleGroups.map((group) => (
                <div key={group.requirement} className="space-y-0.5">
                  <p className="font-medium">{group.requirement}</p>
                  <ul className="space-y-0.5 pl-3 text-muted-foreground">
                    {group.roles.map((role, i) => (
                      <li key={i}>
                        <span className="text-foreground">{role.role}</span> — {QC_ROLE_STATE_LABEL[role.state]}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : null}
          <InfoItems items={info} />
          <CheckActions check={check} ctx={ctx} />
        </div>
      ) : null}
    </li>
  );
}

/**
 * Znacznik „z pliku Word” w QC (29.10.2026) — ten sam, co w karcie „CV do
 * klienta”. CV kandydatki wgrane z dysku przeszło QC jako CV do klienta, bo
 * przy kontroli nic nie mówiło, że układ przyszedł z pliku, a nie z generatora.
 */
export function QcWordFileNote({ cv, className }: { cv: QcResult["cv"] | null | undefined; className?: string }) {
  if (!cv?.from_word_file) return null;
  return (
    <p
      className={cn("flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground", className)}
      data-testid="qc-cv-word-file"
    >
      <Badge size="sm" variant="neutral">
        z pliku Word
      </Badge>
      Treść przeniesiona bez AI — sprawdź układ przed wysyłką.
    </p>
  );
}

/** Zaliczone i niedotyczące — jedna linia, szczegóły po rozwinięciu. */
export function PassedChecks({ passed, skipped, ctx }: { passed: QcCheck[]; skipped: QcCheck[]; ctx: ActionContext }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (passed.length + skipped.length === 0) return null;
  // Bez CV nic nie jest „w porządku” — reszty po prostu nie sprawdzono.
  const title = passed.length > 0 ? "W porządku" : "Nie sprawdzono";
  return (
    <section aria-label={title} className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={listId}
        className="flex w-full items-start gap-2 rounded-lg border border-border px-3 py-2 text-left text-xs text-muted-foreground"
      >
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="font-semibold text-foreground">
            {title} ({passed.length > 0 ? passed.length : skipped.length})
          </span>
          {passed.length > 0 ? <span>: {passed.map((c) => c.label).join(" · ")}</span> : null}
        </span>
        <ChevronDown className={cn("mt-0.5 size-4 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <ul id={listId} className="space-y-2">
          {[...passed, ...skipped].map((check) => (
            <CheckRow key={check.key} check={check} ctx={ctx} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * Uwagi wyciszone w „Jakość QC” (D6): QC zbyt często się przy nich myliło,
 * więc widać je jako informację — nie liczą się do „Warto poprawić”.
 */
export function MutedChecks({ checks, ctx }: { checks: QcCheck[]; ctx: ActionContext }) {
  if (checks.length === 0) return null;
  return (
    <section aria-label="Informacje — wyciszone w „Jakość QC”" className="space-y-2">
      <h3 className={SECTION_TITLE}>Informacje — nie liczą się do uwag ({checks.length})</h3>
      <p className="text-xs text-muted-foreground">
        Wyciszone w „Jakość QC” — przy tych sprawdzeniach QC często się myliło. Zobacz, czy coś jest do poprawy.
      </p>
      <ul className="space-y-2">
        {checks.map((check) => (
          <CheckRow key={check.key} check={check} ctx={ctx} />
        ))}
      </ul>
    </section>
  );
}

/** Wiersz listy „Pominięte” — pozycja QC, uwaga generatora albo kontroli AI. */
export interface DismissedEntry {
  id: string;
  title: string;
  /** Skąd jest uwaga (sprawdzenie QC, rola, „Uwaga generatora”). */
  context?: string | null;
  dismissal: QcDismissal;
  onRestore: () => void;
}

/** Pozycje QC oznaczone „To nieprawda” jako wiersze listy „Pominięte”. */
export function qcDismissedEntries(checks: QcCheck[], ctx: ActionContext): DismissedEntry[] {
  return dismissedQcItems(checks).map(({ check, item }) => {
    const dismissal = item.dismissal as QcDismissal;
    return {
      id: `qc:${dismissal.id}`,
      title: (item.requirement ?? item.term ?? "").trim() || item.detail?.trim() || check.label,
      context: [check.label, item.role].filter(Boolean).join(" · "),
      dismissal,
      onRestore: () => ctx.restore(dismissal.id),
    };
  });
}

/** „Pominięte (n)” — zwinięte; kto, kiedy i dlaczego, z „Przywróć”. */
export function DismissedSection({ entries, restoring }: { entries: DismissedEntry[]; restoring: boolean }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (entries.length === 0) return null;
  return (
    <section aria-label="Pominięte" className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={listId}
        className="flex w-full items-start gap-2 rounded-lg border border-border px-3 py-2 text-left text-xs text-muted-foreground"
      >
        <Ban className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="font-semibold text-foreground">Pominięte ({entries.length})</span>
          {/* Bez „nieprawda”: „Zostaw tę kolejność” to wybór rekrutera; powód stoi przy wierszu. */}
          <span> — nie liczą się do uwag</span>
        </span>
        <ChevronDown className={cn("mt-0.5 size-4 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <ul id={listId} className="space-y-1.5">
          {entries.map((entry) => (
            <li key={entry.id} className="space-y-1 rounded-md border border-border px-2.5 py-2 text-xs">
              <p className="text-sm font-medium [overflow-wrap:anywhere]">{entry.title}</p>
              {entry.context ? <p className="text-muted-foreground [overflow-wrap:anywhere]">{entry.context}</p> : null}
              <p className="[overflow-wrap:anywhere]">
                {entry.dismissal.reason_label}
                {entry.dismissal.note ? <span className="text-muted-foreground"> — „{entry.dismissal.note}”</span> : null}
              </p>
              <p className="flex flex-wrap items-center justify-between gap-2 text-muted-foreground">
                <span>{[entry.dismissal.by_name, formatDate(entry.dismissal.at)].filter(Boolean).join(", ")}</span>
                <Button size="sm" variant="outline" onClick={entry.onRestore} disabled={restoring}>
                  <Undo2 className="size-3.5" aria-hidden />
                  Przywróć
                </Button>
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** Co rekruterzy potwierdzili u kandydata z tego okna — notatki pary, najnowsze pierwsze. */
export function Confirmations({ items }: { items: QcConfirmation[] }) {
  if (items.length === 0) return null;
  return (
    <section
      aria-label="Potwierdzone z kandydatem"
      className="space-y-1 rounded-lg border border-info/30 bg-info-muted px-3 py-2 text-xs leading-relaxed text-info-muted-foreground"
    >
      <h3 className="text-xs font-semibold">Potwierdzone z kandydatem</h3>
      <ul className="space-y-0.5">
        {items.map((item, i) => (
          <li key={i} className="[overflow-wrap:anywhere]">
            {item.text}
            {" — "}
            {[item.by_name, formatDate(item.at)].filter(Boolean).join(", ")}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Propozycje AI ────────────────────────────────────────────────────────────

/** Gdzie w CV stoi to, co poprawka zmienia: zastępowana linia albo stanowisko. */
function proposalTarget(fix: QcFix): IssueTarget | null {
  if (fix.current_text?.trim()) return { kind: "line", text: fix.current_text };
  const label = fix.cv_role_label || fix.role || null;
  const roleIndex = typeof fix.role_index === "number" ? fix.role_index : null;
  return roleIndex != null || label ? { kind: "role", roleIndex, label } : null;
}

function Proposal({
  fix,
  ctx,
  onApply,
  onDismiss,
}: {
  fix: QcFix;
  ctx: ActionContext;
  onApply: (fix: QcFix, text?: string) => void;
  onDismiss: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(fix.proposed_text);
  return (
    <li className="space-y-2 rounded-lg border border-border px-3 py-2.5" aria-label={`Propozycja: ${fix.requirement ?? fix.role ?? fix.id}`}>
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {fix.cv_role_label || fix.role ? (
          <Badge variant="outline" size="sm">
            {fix.cv_role_label || fix.role}
          </Badge>
        ) : null}
        {fix.requirement ? <span>{fix.requirement}</span> : null}
        {fix.check_key === "critical_skills" ? (
          <Badge variant="danger" size="sm">
            {QC_TASK_TAG.critical_skills}
          </Badge>
        ) : null}
      </p>
      {fix.current_text ? (
        <p className="text-xs text-muted-foreground">
          Teraz: <span className="line-through">{fix.current_text}</span>
        </p>
      ) : null}
      {editing ? (
        <textarea
          aria-label="Treść poprawki"
          className="min-h-20 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      ) : (
        <p className="rounded-md bg-success-muted px-2.5 py-1.5 text-sm text-foreground">
          {parseBoldMarkup(fix.proposed_text).map((run, i) =>
            run.b ? (
              <strong key={i} className="font-semibold">
                {run.t}
              </strong>
            ) : (
              <span key={i}>{run.t}</span>
            ),
          )}
        </p>
      )}
      <p className="border-l-2 border-border pl-2 text-xs text-muted-foreground">
        Źródło: {QC_FIX_SOURCE_LABEL[fix.source] ?? QC_FIX_SOURCE_LABEL.original}
        {fix.source_quote ? (
          <>
            {" — "}
            <q className="italic">{fix.source_quote}</q>
          </>
        ) : null}
      </p>
      <div className="flex flex-wrap gap-2">
        {editing ? (
          <>
            <Button
              size="sm"
              disabled={!ctx.editable || ctx.busy || !text.trim()}
              onClick={() => onApply(fix, text.trim())}
            >
              Zastosuj edycję
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false);
                setText(fix.proposed_text);
              }}
            >
              Anuluj
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" disabled={!ctx.editable || ctx.busy} onClick={() => onApply(fix)}>
              Zastosuj
            </Button>
            <Button size="sm" variant="outline" disabled={!ctx.editable} onClick={() => setEditing(true)}>
              Edytuj
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onDismiss(fix.id)}>
              Odrzuć
            </Button>
            <LocateButton target={proposalTarget(fix)} ctx={ctx} />
          </>
        )}
      </div>
    </li>
  );
}

export interface AiFixesViewProps {
  /** `id` sekcji — przycisk „Dopisz zdania (AI)” przewija do niej. */
  sectionId: string;
  ctx: ActionContext;
  /** Odpowiedź serwera; `undefined` = propozycje jeszcze się ładują. */
  data: QcFixesResponse | undefined;
  loading: boolean;
  failed: boolean;
  /** Propozycje bez odrzuconych i już zastosowanych. */
  visible: QcFix[];
  onRetry: () => void;
  onApply: (fix: QcFix, text?: string) => void;
  onDismiss: (id: string) => void;
}

/**
 * Sekcja „Propozycje AI” bez zapytań — okno QC i edytor CV podają jej stan.
 * Propozycje ładują się same (D5, 14.10.2026): bez odpowiedzi i bez awarii
 * sekcja mówi, że je przygotowuje — nie ma przycisku „Zaproponuj”.
 */
export function AiFixesView({
  sectionId,
  ctx,
  data,
  loading,
  failed,
  visible,
  onRetry,
  onApply,
  onDismiss,
}: AiFixesViewProps) {
  let body: React.ReactNode;
  if (!ctx.editable) {
    body = <p className="text-sm text-muted-foreground">{CV_NOT_EDITABLE_MESSAGE}</p>;
  } else if (failed || data?.status === "unavailable") {
    body = (
      <div role="status" className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <AlertTriangle className="size-4 text-warning" aria-hidden />
        Propozycje AI są chwilowo niedostępne — poprawki zrób w edytorze CV.
        <Button size="sm" variant="outline" onClick={onRetry} disabled={loading}>
          {loading ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <RefreshCw className="size-3.5" aria-hidden />}
          Ponów
        </Button>
      </div>
    );
  } else if (loading || !data) {
    body = (
      <p aria-live="polite" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Przygotowuję poprawki AI…
      </p>
    );
  } else if (data.status === "no_cv") {
    body = <p className="text-sm text-muted-foreground">Najpierw wygeneruj CV — AI poprawia istniejące CV.</p>;
  } else if (data.status === "not_editable") {
    body = <p className="text-sm text-muted-foreground">{CV_NOT_EDITABLE_MESSAGE}</p>;
  } else {
    body =
      visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          AI nie ma (więcej) propozycji z pokryciem w oryginale ani w notatkach — resztę popraw w edytorze CV.
        </p>
      ) : (
        <ul className="space-y-2">
          {visible.map((fix) => (
            <Proposal key={fix.id} fix={fix} ctx={ctx} onApply={onApply} onDismiss={onDismiss} />
          ))}
        </ul>
      );
  }

  return (
    <section id={sectionId} aria-label="Propozycje AI" className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-3">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Sparkles className="size-4 text-primary" aria-hidden />
        Propozycje AI
      </h3>
      {body}
    </section>
  );
}
