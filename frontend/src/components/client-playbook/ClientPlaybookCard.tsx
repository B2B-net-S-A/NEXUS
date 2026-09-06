"use client";

/**
 * Karta klienta — renderer TYLKO DO ODCZYTU standardów współpracy per klient
 * (SLA, limity, polityka stawek, off-limit z umowy, „co powiedzieć
 * kandydatowi", reguły priorytetu, zasady procesu, onboarding, dokumenty).
 *
 * Dwa warianty:
 *  * `full` — profil klienta (zakładka „Zasady współpracy") i Pomoc → Klienci;
 *  * `compact` — sekcja 6 Profilu Championa na stronie rekrutacji: chipy
 *    z liczbami, reguły priorytetu i „co powiedzieć kandydatowi", bez
 *    markdownu i dokumentów, z linkiem do pełnej karty w POMOCY. Nie do
 *    profilu klienta: `/clients/*` jest w middleware bramkowane sekcją
 *    Delivery, a compact czyta głównie rekruter (delivery = none); Pomoc
 *    czyta każdy zalogowany (D13).
 *
 * Cztery gałęzie w tej kolejności: błąd → ładowanie → pusto → dane. Pusty
 * stan WYŁĄCZNIE po `isSuccess` (`resolveViewState`) — przerwa między
 * ponowieniami nie może udawać „klient nie ma karty". 403 to „Brak
 * uprawnień", nigdy pustka: pustka czyta się jak utrata danych.
 *
 * Fakty z reguły CV (nazwa pliku, język) idą z OSOBNEJ kwerendy; jej awaria
 * nie blokuje karty — dostaje podpowiedź przy fakcie.
 *
 * Akcja edycji ma dwa tryby i nigdy oba naraz: `editHref` (link, np. do
 * profilu klienta `/clients/<id>?tab=zasady`) albo `onEdit` (przycisk —
 * edycja w miejscu w profilu klienta). Pokazywana tylko z capability
 * `client_playbook.manage`; sam odczyt karty jest org-wide.
 */

import Link from "next/link";
import { BookOpen, ExternalLink, Pencil } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { EmptyState } from "@/components/ds/EmptyState";
import { KeyFacts, type KeyFact } from "@/components/ds/KeyFacts";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { buttonVariants } from "@/components/ui/button";
import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { useCapability } from "@/hooks/useCapability";
import {
  formatOffLimits,
  isPlaybookEmpty,
  useClientPlaybook,
  PLAYBOOK_FIELD_LABELS,
  type ClientPlaybook,
  type PlaybookDocument,
} from "@/lib/client-playbooks";
import type { ClientCvRule } from "@/lib/cv-rules";
import { safeExternalHref } from "@/lib/safe-href";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

export interface ClientPlaybookCardProps {
  clientId: number;
  variant: "full" | "compact";
  /** Link „Edytuj kartę" / „Załóż kartę" (np. do profilu klienta `/clients/<id>?tab=zasady`); pokazywany TYLKO z capability. */
  editHref?: string | null;
  /** Alternatywa dla `editHref`: przycisk zamiast linku (edycja w miejscu w profilu klienta). Nie podawaj obu. */
  onEdit?: () => void;
  className?: string;
}

export function ClientPlaybookCard({
  clientId,
  variant,
  editHref,
  onEdit,
  className,
}: ClientPlaybookCardProps) {
  const query = useClientPlaybook(clientId);
  // Fakty z reguły CV — awaria TEJ kwerendy nie blokuje karty (własna gałąź:
  // podpowiedź w fakcie).
  const cvRule = useClientCvRule(clientId);
  const canManage = useCapability("client_playbook.manage");

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    // OBOWIĄZKOWE — pustka dopiero po sukcesie.
    isSuccess: query.isSuccess,
    isEmpty: isPlaybookEmpty(query.data),
  });

  if (state === "loading") {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Ładowanie karty klienta…
      </p>
    );
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return (
      <QueryStateNotice
        state={state}
        description={
          state === "error"
            ? "Nie udało się wczytać karty klienta. Karta może istnieć — to tylko nieudane pobranie."
            : undefined
        }
        onRetry={state === "error" ? () => void query.refetch() : undefined}
      />
    );
  }
  if (state === "empty") {
    return (
      <EmptyState
        icon={BookOpen}
        className={variant === "compact" ? "py-6" : undefined}
        title="Ten klient nie ma jeszcze karty"
        description="Kartę zakłada Delivery Lead w profilu klienta (Zasady współpracy → Edytuj kartę) albo w Ustawieniach → Reguły CV → Karta klienta."
        action={
          !canManage ? null : onEdit ? (
            <button
              type="button"
              onClick={onEdit}
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              Załóż kartę
            </button>
          ) : editHref ? (
            <Link
              href={editHref}
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              Załóż kartę
            </Link>
          ) : null
        }
      />
    );
  }

  const playbook = query.data;
  // „ready" ⇒ dane zdefiniowane; strażnik wyłącznie dla typu.
  if (!playbook) return null;
  const rule = cvRule.data?.is_active ? cvRule.data : null;

  return variant === "compact" ? (
    <CompactCard
      playbook={playbook}
      rule={rule}
      editHref={canManage ? (editHref ?? null) : null}
      className={className}
    />
  ) : (
    <FullCard
      playbook={playbook}
      rule={rule}
      cvRuleFailed={cvRule.isError}
      editHref={canManage ? (editHref ?? null) : null}
      onEdit={canManage ? onEdit : undefined}
      className={className}
    />
  );
}

// ── Wariant pełny ───────────────────────────────────────────────────────────

function metaLine(playbook: ClientPlaybook): string {
  let line = `wersja ${playbook.version}`;
  if (playbook.updated_by_name) line += ` · zaktualizował ${playbook.updated_by_name}`;
  if (playbook.updated_at) {
    const d = new Date(playbook.updated_at);
    if (!Number.isNaN(d.getTime())) line += ` · ${d.toLocaleDateString("pl-PL")}`;
  }
  return line;
}

function FullCard({
  playbook,
  rule,
  cvRuleFailed,
  editHref,
  onEdit,
  className,
}: {
  playbook: ClientPlaybook;
  rule: ClientCvRule | null;
  cvRuleFailed: boolean;
  editHref: string | null;
  onEdit?: () => void;
  className?: string;
}) {
  const cvRuleHint = cvRuleFailed ? "nie udało się sprawdzić reguły CV" : undefined;
  const facts: KeyFact[] = [
    {
      id: "sla_business_days",
      label: PLAYBOOK_FIELD_LABELS.sla_business_days,
      value: playbook.sla_business_days,
    },
    {
      id: "sla_min_candidates",
      label: PLAYBOOK_FIELD_LABELS.sla_min_candidates,
      value: playbook.sla_min_candidates,
    },
    {
      id: "cv_limit_per_process",
      label: PLAYBOOK_FIELD_LABELS.cv_limit_per_process,
      value: playbook.cv_limit_per_process,
    },
    {
      id: "hold_hours",
      label: PLAYBOOK_FIELD_LABELS.hold_hours,
      value: playbook.hold_hours,
    },
    {
      id: "multi_project_cooldown_days",
      label: PLAYBOOK_FIELD_LABELS.multi_project_cooldown_days,
      value: playbook.multi_project_cooldown_days,
    },
    {
      id: "rate_policy",
      label: PLAYBOOK_FIELD_LABELS.rate_policy,
      value: playbook.rate_policy,
    },
    {
      id: "off_limits",
      label: PLAYBOOK_FIELD_LABELS.off_limits,
      value: formatOffLimits(playbook.off_limits),
      hint: playbook.off_limits?.notes ?? undefined,
    },
    {
      id: "cv_filename",
      label: "Nazwa pliku CV (z reguły CV)",
      value: rule ? (rule.filename_preview ?? rule.filename_pattern) : null,
      hint: cvRuleHint,
    },
    {
      id: "cv_language",
      label: "Język CV (z reguły CV)",
      value: rule?.cv_language ? rule.cv_language.toUpperCase() : null,
      hint: cvRuleHint,
    },
  ];

  return (
    <article className={cn("space-y-5", className)} data-testid="client-playbook-card">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-foreground">
            {`Karta klienta${playbook.client_name ? ` — ${playbook.client_name}` : ""}`}
          </h3>
          <p className="text-xs text-muted-foreground">{metaLine(playbook)}</p>
        </div>
        {onEdit ? (
          <button
            type="button"
            onClick={onEdit}
            className={buttonVariants({ variant: "outline", size: "sm" })}
            data-testid="client-playbook-edit"
          >
            <Pencil className="h-4 w-4" aria-hidden /> Edytuj kartę
          </button>
        ) : editHref ? (
          <Link
            href={editHref}
            className={buttonVariants({ variant: "outline", size: "sm" })}
            data-testid="client-playbook-edit"
          >
            <Pencil className="h-4 w-4" aria-hidden /> Edytuj kartę
          </Link>
        ) : null}
      </header>

      <KeyFacts columns={3} density="compact" facts={facts} />

      <TextBlock
        title={PLAYBOOK_FIELD_LABELS.about_for_candidate}
        text={playbook.about_for_candidate}
      />
      <TextBlock title={PLAYBOOK_FIELD_LABELS.priority_rules} text={playbook.priority_rules} />
      <MarkdownBlock title="Zasady procesu rekrutacji" md={playbook.process_rules_md} />
      <MarkdownBlock title="Onboarding po akceptacji" md={playbook.onboarding_md} />
      <DocumentsBlock documents={playbook.documents} />
    </article>
  );
}

function BlockTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </h4>
  );
}

function TextBlock({ title, text }: { title: string; text: string | null }) {
  if (!text?.trim()) return null;
  return (
    <section>
      <BlockTitle>{title}</BlockTitle>
      <p className="whitespace-pre-wrap text-sm text-foreground">{text}</p>
    </section>
  );
}

function MarkdownBlock({ title, md }: { title: string; md: string | null }) {
  if (!md?.trim()) return null;
  return (
    <section>
      <BlockTitle>{title}</BlockTitle>
      {/* react-markdown domyślnie neutralizuje `javascript:` w linkach markdownu. */}
      <div className="prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-foreground prose-a:text-primary">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      </div>
    </section>
  );
}

function DocumentsBlock({ documents }: { documents: PlaybookDocument[] }) {
  if (!documents || documents.length === 0) return null;
  return (
    <section>
      <BlockTitle>Dokumenty</BlockTitle>
      <ul className="space-y-1">
        {documents.map((doc, i) => {
          // Allowlista http/https — link z bazy bywa czymkolwiek, a `href`
          // z `javascript:` wykonałby się w sesji czytelnika.
          const href = safeExternalHref(doc.url);
          return (
            <li key={`${doc.url}-${i}`} className="text-sm">
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  {doc.name || href}
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                </a>
              ) : (
                <span className="text-muted-foreground">{`${doc.name} — nieprawidłowy link`}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ── Wariant compact (strona rekrutacji) ─────────────────────────────────────

const RATE_POLICY_CHIP_MAX = 60;

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

function compactChips(playbook: ClientPlaybook, rule: ClientCvRule | null): string[] {
  const chips: string[] = [];
  if (playbook.sla_business_days != null) chips.push(`SLA ${playbook.sla_business_days} dni`);
  if (playbook.sla_min_candidates != null) chips.push(`min. ${playbook.sla_min_candidates} kand.`);
  if (playbook.cv_limit_per_process != null) chips.push(`limit CV ${playbook.cv_limit_per_process}`);
  if (playbook.hold_hours != null) chips.push(`blokada ${playbook.hold_hours} h`);
  if (playbook.multi_project_cooldown_days != null) {
    chips.push(`karencja ${playbook.multi_project_cooldown_days} dni`);
  }
  const off = playbook.off_limits;
  if (off?.months != null) chips.push(`off-limit ${off.months} mies.`);
  else if (off?.scope?.trim()) chips.push(`off-limit: ${off.scope.trim()}`);
  if (rule?.cv_language) chips.push(`CV: ${rule.cv_language.toUpperCase()}`);
  if (rule?.filename_preview) chips.push(`plik: ${rule.filename_preview}`);
  if (playbook.rate_policy?.trim()) {
    chips.push(`stawki: ${truncate(playbook.rate_policy.trim(), RATE_POLICY_CHIP_MAX)}`);
  }
  return chips;
}

function FactChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-foreground">
      {children}
    </span>
  );
}

function CompactCard({
  playbook,
  rule,
  editHref,
  className,
}: {
  playbook: ClientPlaybook;
  rule: ClientCvRule | null;
  editHref?: string | null;
  className?: string;
}) {
  const chips = compactChips(playbook, rule);
  return (
    <section
      className={cn("space-y-2 rounded-lg border border-border bg-muted/30 p-3", className)}
      data-testid="client-playbook-card-compact"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {`Karta klienta${playbook.client_name ? ` · ${playbook.client_name}` : ""}`}
        </span>
        <span className="flex items-center gap-3">
          {/* „Pełna karta klienta →" celowo do Pomocy, nie do profilu klienta:
              /clients/* jest w middleware bramkowane sekcją Delivery, a compact
              czyta głównie rekruter (delivery = none). Pomoc czyta każdy
              zalogowany (D13). „Edytuj →" dochodzi tylko z uprawnieniem
              `client_playbook.manage` (zbramkowane w call-site), spójnie ze
              stanem pustym „Załóż kartę" i wariantem full. */}
          <Link
            href={`/help?tab=clients&client=${playbook.client_id}`}
            className="text-xs text-primary hover:underline"
          >
            Pełna karta klienta →
          </Link>
          {editHref ? (
            <Link
              href={editHref}
              data-testid="client-playbook-edit"
              className="text-xs text-primary hover:underline"
            >
              Edytuj →
            </Link>
          ) : null}
        </span>
      </div>
      {chips.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <FactChip key={chip}>{chip}</FactChip>
          ))}
        </div>
      ) : null}
      {playbook.priority_rules ? (
        <p className="text-xs text-foreground">
          <span className="font-medium">Reguły priorytetu:</span> {playbook.priority_rules}
        </p>
      ) : null}
      {playbook.about_for_candidate ? (
        <p className="whitespace-pre-wrap text-xs text-muted-foreground">
          {playbook.about_for_candidate}
        </p>
      ) : null}
    </section>
  );
}
