"use client";

/**
 * „Uporządkowanie wymagań” (13.10.2026, D4, makieta P5) — propozycja serwera
 * dla jednej rekrutacji jako porównanie „Teraz” → „Po zmianie”.
 *
 * Decyduje Delivery Lead rekrutacji, Head of Recruitment albo admin
 * (`can_decide`); reszta widzi okno tylko do odczytu. „Zatwierdź” to zwykły
 * zapis Profilu Championa po stronie serwera, „Odrzuć” chowa propozycję do
 * następnej zmiany profilu. Okno otwiera pulpit („Wymagania do poprawy”)
 * i baner Profilu Championa.
 */

import Link from "next/link";
import { Fragment, useId, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

import { useOptionalToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  staleProposalFrom,
  useApplyRequirementProposal,
  useDismissRequirementProposal,
  useRequirementProposal,
  type RequirementProposal,
} from "@/lib/requirement-proposal-api";
import { countPl } from "@/lib/plural-pl";
import { LEVEL_LABEL, type RequirementLevel } from "@/lib/requirement-rows";
import { cn } from "@/lib/utils";

const LEVELS: readonly RequirementLevel[] = ["critical", "must", "nice"];

/** Uzupełnienie słów do szukania — pełny formularz Profilu Championa. */
export function championEditHref(jobId: number): string {
  return `/jobs/${jobId}?tab=champion&mode=edit`;
}

export interface RequirementProposalDialogProps {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tytuł rekrutacji w opisie okna (pulpit go zna; Profil Championa nie musi go podawać). */
  jobTitle?: string;
}

interface Notice {
  text: string;
  tone: "warning" | "error";
}

function sentence(text: string): string {
  const trimmed = text.trim();
  return trimmed ? trimmed[0].toLocaleUpperCase("pl") + trimmed.slice(1) : trimmed;
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-block max-w-full break-words rounded-md border border-border bg-muted/40 px-2 py-0.5 text-xs text-foreground">
      {children}
    </span>
  );
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      {children}
    </div>
  );
}

function Chips({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-xs text-muted-foreground">— brak</p>;
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item, index) => (
        <Chip key={`${item}-${index}`}>{item}</Chip>
      ))}
    </div>
  );
}

function BeforeColumn({ proposal, languageChanged }: { proposal: RequirementProposal; languageChanged: boolean }) {
  const { before } = proposal;
  return (
    <section aria-label="Teraz" className="min-w-0 space-y-3 rounded-lg border border-border p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Teraz</h3>
      <Group label={LEVEL_LABEL.must}>
        <Chips items={before.must} />
      </Group>
      {before.critical.length > 0 ? (
        <Group label="Krytyczne">
          <div className="flex flex-wrap gap-1">
            {before.critical.map((name, index) => (
              <Chip key={`${name}-${index}`}>
                {name}
                <span className="text-muted-foreground"> · krytyczne</span>
              </Chip>
            ))}
          </div>
        </Group>
      ) : null}
      {before.language || languageChanged ? (
        <p className="text-xs text-foreground">Język: {before.language ?? "brak"}</p>
      ) : null}
    </section>
  );
}

function AfterColumn({ proposal, languageChanged }: { proposal: RequirementProposal; languageChanged: boolean }) {
  const { after } = proposal;
  return (
    <section aria-label="Po zmianie" className="min-w-0 space-y-3 rounded-lg border border-primary/30 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-primary">Po zmianie</h3>
      {after.rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">Brak słów do szukania.</p>
      ) : null}
      {LEVELS.map((level) => {
        const rows = after.rows.filter((row) => row.level === level);
        if (rows.length === 0) return null;
        return (
          <Group key={level} label={LEVEL_LABEL[level]}>
            <ul className="space-y-1" data-testid={`proposal-rows-${level}`}>
              {rows.map((row, index) => (
                <li key={`${row.words.join("|")}-${index}`} className="flex flex-wrap items-center gap-1">
                  {row.words.map((word, wordIndex) => (
                    <Fragment key={`${word}-${wordIndex}`}>
                      {wordIndex > 0 ? <span className="text-xs text-muted-foreground"> lub </span> : null}
                      <Chip>{word}</Chip>
                    </Fragment>
                  ))}
                </li>
              ))}
            </ul>
          </Group>
        );
      })}
      {after.talk.length > 0 ? (
        <Group label="Rekruter sprawdza w rozmowie">
          <div className="flex flex-wrap gap-1" data-testid="proposal-talk">
            {after.talk.map((item, index) => (
              <Chip key={`${item.kind}-${item.name}-${index}`}>
                {item.name}
                {item.level === "nice" ? (
                  <span className="text-muted-foreground"> · mile widziane</span>
                ) : null}
              </Chip>
            ))}
          </div>
        </Group>
      ) : null}
      {languageChanged ? (
        <p className="text-xs text-foreground">Język: {after.language ?? "brak"}</p>
      ) : null}
      {after.critical?.length === 0 && proposal.before.critical.length > 0 ? (
        <p className="text-xs text-foreground" data-testid="proposal-no-critical">
          Krytyczne: brak — dotychczasowe są zdaniami, a zdanie nie może być krytyczne.
        </p>
      ) : null}
      {after.rare && after.rare.length > 0 ? (
        <Group label="Mało osób w bazie">
          <ul className="space-y-0.5 text-xs text-foreground" data-testid="proposal-rare">
            {after.rare.map((item, index) => (
              <li key={`${item.words.join("|")}-${index}`}>
                „{item.words.join(" lub ")}” —{" "}
                {item.people === 0
                  ? "nikt w bazie"
                  : `tylko ${countPl(item.people, "osoba", "osoby", "osób")}`}
                {item.action === "split" && item.parts
                  ? `, rozdzielone: ${item.parts.join(" lub ")}`
                  : ", rekruter sprawdzi w rozmowie"}
              </li>
            ))}
          </ul>
        </Group>
      ) : null}
      {after.overflow && after.overflow.length > 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="proposal-overflow">
          Nie mieści się w wierszach, trafi do opisu wymagań: {after.overflow.join(", ")}
        </p>
      ) : null}
    </section>
  );
}

export function RequirementProposalDialog({
  jobId,
  open,
  onOpenChange,
  jobTitle,
}: RequirementProposalDialogProps) {
  const query = useRequirementProposal(jobId, open);
  const apply = useApplyRequirementProposal(jobId);
  const dismiss = useDismissRequirementProposal(jobId);
  const toast = useOptionalToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [notice, setNotice] = useState<Notice | null>(null);
  const descriptionId = useId();
  const hintId = useId();

  const proposal = query.data?.proposal ?? null;
  const canDecide = query.data?.can_decide === true;
  const busy = apply.isPending || dismiss.isPending;

  const changeOpen = (next: boolean) => {
    if (!next) setNotice(null);
    onOpenChange(next);
  };

  // 409 „profil się zmienił” podmienia propozycję w pamięci zapytania (hook);
  // tu zostaje zdanie, dlaczego okno pokazuje coś innego niż przed chwilą.
  const showDecisionError = (error: unknown, fallback: string) => {
    setNotice({
      text: apiErrorMessage(error, fallback),
      tone: staleProposalFrom(error) ? "warning" : "error",
    });
  };

  const approve = () => {
    if (!proposal) return;
    setNotice(null);
    apply.mutate(proposal, {
      onSuccess: (data) => {
        toast?.showSuccess("Wymagania uporządkowane.");
        for (const text of data.notices ?? []) toast?.showInfo(text);
        changeOpen(false);
      },
      onError: (error) => showDecisionError(error, "Nie udało się zatwierdzić propozycji."),
    });
  };

  const reject = async () => {
    if (!proposal) return;
    const decided = proposal;
    const confirmed = await askConfirm({
      title: "Odrzucić propozycję?",
      description: "Wróci dopiero po zmianie Profilu Championa.",
      confirmLabel: "Odrzuć",
    });
    if (!confirmed) return;
    setNotice(null);
    dismiss.mutate(decided, {
      onSuccess: () => {
        toast?.showSuccess("Propozycja odrzucona.");
        changeOpen(false);
      },
      onError: (error) => showDecisionError(error, "Nie udało się odrzucić propozycji."),
    });
  };

  const languageChanged =
    proposal !== null && (proposal.before.language ?? null) !== (proposal.after.language ?? null);

  let hint: ReactNode = null;
  if (proposal && !canDecide) {
    hint = "Zatwierdza Delivery Lead tej rekrutacji albo Head of Recruitment.";
  } else if (proposal && !proposal.can_apply) {
    hint = (
      <>
        Najpierw dodaj słowo do szukania w Profilu Championa.{" "}
        <Link
          href={championEditHref(jobId)}
          onClick={() => changeOpen(false)}
          className="font-medium text-primary hover:underline"
        >
          Uzupełnij
        </Link>
      </>
    );
  }

  let body: ReactNode;
  if (query.isPending) {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Wczytuję propozycję…
      </p>
    );
  } else if (query.isError && !query.data) {
    body = (
      <div role="alert" className="space-y-2 text-sm">
        <p className="text-destructive">
          {apiErrorMessage(query.error, "Nie udało się wczytać propozycji.")}
        </p>
        <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
          Ponów
        </Button>
      </div>
    );
  } else if (!proposal) {
    body = (
      <p className="text-sm text-muted-foreground">
        Wymagania tej rekrutacji nie wymagają już poprawek.
      </p>
    );
  } else {
    body = (
      <div className="space-y-4">
        {notice ? (
          <p
            role={notice.tone === "error" ? "alert" : "status"}
            className={cn(
              "rounded-md px-3 py-2 text-sm",
              notice.tone === "error"
                ? "bg-destructive/10 text-destructive"
                : "bg-warning-muted text-warning-muted-foreground",
            )}
          >
            {notice.text}
          </p>
        ) : null}
        <div>
          <p className="mb-1 text-sm font-medium">Co się zmieni</p>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground" data-testid="proposal-reasons">
            {proposal.reasons.map((reason) => (
              <li key={reason.code}>{sentence(reason.text)}</li>
            ))}
          </ul>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <BeforeColumn proposal={proposal} languageChanged={languageChanged} />
          <AfterColumn proposal={proposal} languageChanged={languageChanged} />
        </div>
        {proposal.contract_reviewed ? (
          <p className="text-xs font-medium text-warning" data-testid="proposal-reviewed-note">
            Zatwierdzenie zastąpi wymagania sprawdzone wcześniej przez człowieka.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <>
      <Dialog open={open} onOpenChange={changeOpen}>
        <DialogContent size="xl" aria-describedby={descriptionId}>
          <DialogHeader>
            <DialogTitle className="text-lg">Uporządkowanie wymagań</DialogTitle>
            <DialogDescription id={descriptionId}>
              {jobTitle ? `${jobTitle} · ` : ""}Słowa do szukania zostają w wymaganiach, zdania
              przechodzą do rozmowy z kandydatem.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>{body}</DialogBody>
          <DialogFooter className="sm:items-center">
            {hint ? (
              <p id={hintId} className="text-xs text-muted-foreground sm:mr-auto" data-testid="proposal-hint">
                {hint}
              </p>
            ) : null}
            <Button variant="ghost" onClick={() => changeOpen(false)}>
              Zamknij
            </Button>
            {proposal && canDecide ? (
              <>
                <Button
                  variant="outline"
                  onClick={() => void reject()}
                  loading={dismiss.isPending}
                  disabled={busy}
                >
                  Odrzuć
                </Button>
                <Button
                  onClick={approve}
                  loading={apply.isPending}
                  disabled={busy || !proposal.can_apply}
                  aria-describedby={!proposal.can_apply && hint ? hintId : undefined}
                >
                  Zatwierdź
                </Button>
              </>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </>
  );
}
