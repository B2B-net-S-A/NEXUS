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
 * Treść CV, dowodów i propozycji to TEKST — nic nie trafia na stronę jako HTML.
 */

import Link from "next/link";
import { useId, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  HelpCircle,
  Loader2,
  LocateFixed,
  MinusCircle,
  RefreshCw,
  Sparkles,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  QcCheck,
  QcConfirmBody,
  QcConfirmation,
  QcFix,
  QcFixAction,
  QcFixesResponse,
  QcItem,
  QcResult,
} from "@/lib/api/cvQc";
import {
  CV_NOT_EDITABLE_MESSAGE,
  QC_ROLE_STATE_LABEL,
  QC_TASK_TAG,
  checkLevelFixes,
  companyCvRoleState,
  groupRoleStates,
  itemTarget,
  notePreview,
  originalDescribesSkill,
  parseBoldMarkup,
  taskTitle,
  type IssueTarget,
  type QcTask,
} from "@/lib/cv-qc";
import { cn, formatDate } from "@/lib/utils";

export const SECTION_TITLE = "text-xs font-semibold uppercase tracking-wider text-muted-foreground";

function StatusIcon({ status }: { status: QcCheck["status"] }) {
  if (status === "pass") return <CheckCircle2 className="size-4 text-success" aria-label="Przechodzi" />;
  if (status === "fail") return <AlertTriangle className="size-4 text-warning" aria-label="Warto poprawić" />;
  if (status === "manual")
    return <HelpCircle className="size-4 text-info" aria-label="Do sprawdzenia ręcznie" />;
  return <MinusCircle className="size-4 text-muted-foreground" aria-label="Nie dotyczy" />;
}

function statusBadge(check: QcCheck) {
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
  requestAiFixes: () => void;
  copyQuestion: (item: QcItem) => void;
  /** Edytor sprawdzanego CV — `null`, gdy tego CV nie da się edytować w NEXUSIE. */
  openEditor: (() => void) | null;
  /** „Pokaż w CV” — tylko w edytorze CV, gdzie tekst stoi obok listy. */
  locate?: (target: IssueTarget) => void;
  /** Odnośniki poza listę otwierają nową kartę (edytor CV zostaje otwarty). */
  linksInNewTab?: boolean;
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

const generatorHref = (data: QcResult) =>
  `/cv-generator?candidate_id=${data.candidate_id}&job_id=${data.job_id}`;

function CheckActions({ check, ctx }: { check: QcCheck; ctx: ActionContext }) {
  const kinds = checkLevelFixes(check);
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
        return (
          <Button key={kind} size="sm" variant="outline" disabled={!ctx.editable} onClick={ctx.requestAiFixes}>
            <Sparkles className="size-3.5" aria-hidden />
            Zaproponuj poprawki (AI)
          </Button>
        );
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

function ItemAction({ item, ctx }: { item: QcItem; ctx: ActionContext }) {
  const term = (item.term ?? item.requirement ?? "").trim();
  switch (item.fix) {
    case "remove_term":
      return term ? <RemoveTermButton term={term} ctx={ctx} /> : null;
    case "ask_candidate":
      return (
        <span className="flex flex-wrap gap-2">
          <AskCandidateButtons item={item} ctx={ctx} />
        </span>
      );
    case "upload_consent":
      return (
        <span className="text-xs text-muted-foreground">
          Zrzut zgody RODO wgrywa się w generatorze CV —{" "}
          <Link href={generatorHref(ctx.data)} className="font-medium text-primary hover:underline" {...newTab(ctx)}>
            otwórz generator
          </Link>
          , wgraj zrzut i wygeneruj CV ponownie.
        </span>
      );
    case "generate_cv":
      return (
        <Button asChild size="sm">
          <Link href={generatorHref(ctx.data)} {...newTab(ctx)}>
            Wygeneruj CV
          </Link>
        </Button>
      );
    default:
      return null;
  }
}

/** Rola z brakiem: na czym w oryginale stoi wymóg opisu i co jest w CV firmowym. */
function RoleEvidence({ item, ctx }: { item: QcItem; ctx: ActionContext }) {
  const evidence = item.evidence?.trim();
  return (
    <li className="space-y-1 rounded-md border border-border bg-card px-2.5 py-2">
      <span className="flex flex-wrap items-center justify-between gap-1.5">
        <Badge variant="outline" size="sm">
          {item.role}
        </Badge>
        <LocateButton target={itemTarget(item)} ctx={ctx} />
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

/** Jedna rzecz do poprawy przed wysłaniem: co jest nie tak, gdzie i przycisk naprawy. */
export function TaskCard({ task, ctx }: { task: QcTask; ctx: ActionContext }) {
  const { check, name, items } = task;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const title = taskTitle(task);
  const roleItems = items.filter((i) => i.role);
  const first = items[0];
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
            <RoleEvidence key={i} item={item} ctx={ctx} />
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
      <p className="text-xs text-muted-foreground">
        Oryginalne CV i notatki z rozmów o tym nie wspominają. Usuń to z CV albo potwierdź u kandydata i zapisz
        potwierdzenie.
      </p>
    );
    actions = (
      <>
        {term ? <RemoveTermButton term={term} ctx={ctx} /> : null}
        <AskCandidateButtons item={first} ctx={ctx} />
        {term && !confirmOpen ? (
          <Button size="sm" variant="outline" onClick={() => setConfirmOpen(true)}>
            Potwierdzone z kandydatem
          </Button>
        ) : null}
        <LocateButton target={itemTarget(first)} ctx={ctx} />
      </>
    );
    form = term && confirmOpen ? <ConfirmForm term={term} ctx={ctx} onClose={() => setConfirmOpen(false)} /> : null;
  } else if (first) {
    // Bez nazwy tytułem jest samo zdanie pozycji — nie powtarzamy go niżej.
    body = name && first.detail ? <p className="text-xs text-muted-foreground">{first.detail}</p> : null;
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
      </p>
      {body}
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      {form}
    </li>
  );
}

export function CheckRow({ check, ctx }: { check: QcCheck; ctx: ActionContext }) {
  const [open, setOpen] = useState(false);
  const roleGroups = groupRoleStates(check.roles ?? []);
  const hasBody = check.items.length > 0 || checkLevelFixes(check).length > 0 || roleGroups.length > 0;
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
        <StatusIcon status={check.status} />
        <span className="min-w-0">
          <span className="block text-sm font-medium">{check.label}</span>
          {preview && !open ? (
            <span className="block truncate text-xs text-muted-foreground">{preview}</span>
          ) : null}
        </span>
        <span className="flex items-center gap-1.5">
          {statusBadge(check)}
          {hasBody ? (
            <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
          ) : null}
        </span>
      </button>
      {open && hasBody ? (
        <div id={bodyId} className="space-y-2 px-3 py-2.5">
          {check.items.map((item, i) => (
            <div key={i} className="space-y-1.5 rounded-md border border-border/70 px-2.5 py-2 text-sm">
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
              {ctx.locate && itemTarget(item) ? (
                <div className="flex flex-wrap items-center gap-2">
                  <ItemAction item={item} ctx={ctx} />
                  <LocateButton target={itemTarget(item)} ctx={ctx} />
                </div>
              ) : (
                <ItemAction item={item} ctx={ctx} />
              )}
            </div>
          ))}
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
          <CheckActions check={check} ctx={ctx} />
        </div>
      ) : null}
    </li>
  );
}

/** Zaliczone i niedotyczące — jedna linia, szczegóły po rozwinięciu. */
export function PassedChecks({ passed, skipped, ctx }: { passed: QcCheck[]; skipped: QcCheck[]; ctx: ActionContext }) {
  const [open, setOpen] = useState(false);
  if (passed.length + skipped.length === 0) return null;
  const listId = useId();
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
        Źródło: {fix.source === "notes" ? "notatka rekrutera" : "oryginalne CV"}
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
  /** Odpowiedź serwera; `undefined` = jeszcze nie proszono o propozycje. */
  data: QcFixesResponse | undefined;
  loading: boolean;
  failed: boolean;
  /** Propozycje bez odrzuconych i już zastosowanych. */
  visible: QcFix[];
  onRequest: () => void;
  onRetry: () => void;
  onApply: (fix: QcFix, text?: string) => void;
  onDismiss: (id: string) => void;
}

/** Sekcja „Propozycje AI” bez zapytań — okno QC i edytor CV podają jej stan. */
export function AiFixesView({
  sectionId,
  ctx,
  data,
  loading,
  failed,
  visible,
  onRequest,
  onRetry,
  onApply,
  onDismiss,
}: AiFixesViewProps) {
  let body: React.ReactNode;
  if (!ctx.editable) {
    body = <p className="text-sm text-muted-foreground">{CV_NOT_EDITABLE_MESSAGE}</p>;
  } else if (loading) {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Luna porównuje CV z oryginałem i notatkami…
      </p>
    );
  } else if (failed || data?.status === "unavailable") {
    body = (
      <div role="status" className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <AlertTriangle className="size-4 text-warning" aria-hidden />
        Propozycje AI są chwilowo niedostępne — poprawki zrób w edytorze CV.
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw className="size-3.5" aria-hidden />
          Ponów
        </Button>
      </div>
    );
  } else if (data?.status === "no_cv") {
    body = <p className="text-sm text-muted-foreground">Najpierw wygeneruj CV — AI poprawia istniejące CV.</p>;
  } else if (data?.status === "not_editable") {
    body = <p className="text-sm text-muted-foreground">{CV_NOT_EDITABLE_MESSAGE}</p>;
  } else if (data) {
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
  } else {
    body = (
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          AI zaproponuje zdania z pokryciem w oryginalnym CV albo notatkach — bez źródła nie ma poprawki.
        </p>
        <Button size="sm" variant="outline" onClick={onRequest}>
          <Sparkles className="size-3.5" aria-hidden />
          Zaproponuj poprawki (AI)
        </Button>
      </div>
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
