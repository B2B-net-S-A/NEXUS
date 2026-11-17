"use client";

/**
 * Bot Cpro w oknie „Do wrzucenia do Cpro” (decyzje Artura 17.11.2026).
 *
 * Grok Bot sam wrzuca osoby z kolejki do Cpro Nordei i wysyła ofertę; osoba od
 * Cpro widzi przy każdej osobie, co bot zrobił albo czego mu brakuje, a ręczne
 * „✓ Wrzucone” zostaje na wypadek, gdy bot nie dał rady.
 * → docs/claude/integracje/cpro-bot-grok.md
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, ExternalLink, Loader2, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CPRO_QUEUE_QUERY_KEY,
  retryCproBot,
  type CproBotItem,
  type CproBotSummary,
} from "@/lib/api/boardTasks";
import { cn } from "@/lib/utils";

const TIME = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" });

type Tone = "muted" | "info" | "success" | "warning" | "danger";

const TONE_CLASS: Record<Tone, string> = {
  muted: "text-muted-foreground",
  info: "text-info-muted-foreground",
  success: "text-success-muted-foreground",
  warning: "text-warning-muted-foreground",
  danger: "text-destructive",
};

/** Link do oferty w Cpro tylko https (serwer i tak przepuszcza tylko *.onevms.se). */
export function cproOfferHref(url: string | null | undefined): string | undefined {
  return url && /^https:\/\//i.test(url) ? url : undefined;
}

/** Jedno zdanie o bocie przy osobie — to samo, co widać w wierszu. */
export function cproBotText(bot: CproBotItem): { tone: Tone; text: string } {
  switch (bot.state) {
    case "blocked":
      return { tone: "warning", text: `Bot czeka: ${bot.blockers.join(" · ")}` };
    case "ready":
      return { tone: "muted", text: "Bot wrzuci tę osobę w najbliższym biegu (do 5 min)." };
    case "working":
      return { tone: "info", text: "Bot wypełnia ofertę w Cpro…" };
    case "submitted":
      return bot.moved === false
        ? {
            tone: "warning",
            text: `Bot wysłał ofertę do Cpro${bot.cpro_status ? ` (${bot.cpro_status})` : ""}, ale nie przesunął karty — kliknij „Wrzucone”.${bot.message ? ` ${bot.message}` : ""}`,
          }
        : { tone: "success", text: `Bot wysłał ofertę do Cpro${bot.cpro_status ? ` (${bot.cpro_status})` : ""}.` };
    case "draft":
      return { tone: "info", text: "Szkic oferty w Cpro z próby — bot wyśle go w następnym biegu." };
    case "skipped":
      return { tone: "warning", text: `Bot pominął: ${bot.message ?? "osoba ma już ofertę w Cpro"}` };
    case "failed":
      return { tone: "danger", text: `Bot nie wrzucił: ${bot.message ?? "nieznany błąd"} Wrzuć ręcznie albo ponów.` };
    case "retry":
      return { tone: "warning", text: "Bieg bota się nie udał — bot spróbuje jeszcze raz." };
  }
}

export function CproBotItemStatus({
  stageId,
  bot,
  canRetry,
}: {
  stageId: number;
  bot: CproBotItem | null | undefined;
  canRetry: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [busy, setBusy] = useState(false);
  if (!bot) return null;
  const { tone, text } = cproBotText(bot);
  const href = cproOfferHref(bot.offer_url);
  const retryable = canRetry && (bot.state === "failed" || bot.state === "skipped");

  const retry = async () => {
    setBusy(true);
    try {
      await retryCproBot(stageId);
      showSuccess("Bot dostał tę osobę — wynik pojawi się tutaj.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zlecić bota. Spróbuj ponownie."));
    } finally {
      setBusy(false);
      void queryClient.invalidateQueries({ queryKey: CPRO_QUEUE_QUERY_KEY });
    }
  };

  return (
    <div className="mt-1 space-y-0.5 text-xs" data-testid="cpro-bot-status" data-state={bot.state}>
      <p className={cn("flex items-start gap-1 [overflow-wrap:anywhere]", TONE_CLASS[tone])}>
        {bot.state === "working" ? (
          <Loader2 className="mt-0.5 size-3 shrink-0 animate-spin" aria-hidden />
        ) : (
          <Bot className="mt-0.5 size-3 shrink-0" aria-hidden />
        )}
        <span>{text}</span>
      </p>
      {bot.data_from.length > 0 ? (
        <p className="text-muted-foreground">Dane z rekrutacji {bot.data_from.join(", ")}</p>
      ) : null}
      {href || retryable ? (
        <p className="flex flex-wrap items-center gap-2">
          {href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
            >
              Oferta w Cpro <ExternalLink className="size-3" aria-hidden />
            </a>
          ) : null}
          {retryable ? (
            <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" disabled={busy} onClick={() => void retry()}>
              {busy ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <RotateCcw className="size-3" aria-hidden />}
              Ponów botem
            </Button>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

/** Linia nad kolejką: czy bot działa i co dziś wysłał. */
export function CproBotLine({ bot }: { bot: CproBotSummary | null | undefined }) {
  if (!bot) return null;
  if (!bot.configured) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-warning-muted-foreground" data-testid="cpro-bot-line">
        <Bot className="size-3.5" aria-hidden /> Bot Cpro nie ma jeszcze rutyny w Grok Bocie — wrzucaj ręcznie.
      </p>
    );
  }
  const parts = [
    bot.working ? "wypełnia Cpro teraz" : "sprawdza kolejkę co 5 min",
    `wysłane dziś: ${bot.sent_today}`,
    ...(bot.last_run_at ? [`ostatni bieg ${TIME.format(new Date(bot.last_run_at))}`] : []),
  ];
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="cpro-bot-line">
      {bot.working ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Bot className="size-3.5" aria-hidden />}
      Bot Cpro · {parts.join(" · ")}
    </p>
  );
}
