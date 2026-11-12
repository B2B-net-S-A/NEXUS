"use client";

import Link from "next/link";
import { Bot } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useBotPeoplePending, useStartBotPeople } from "@/lib/api/sales-bot-people";
import { cn } from "@/lib/utils";

import { peopleCount } from "../research-import/research-import";

export const BOT_PEOPLE_RUNNING = "Bot już szuka decydentów tej firmy. Kolejny bieg po 24 godzinach.";

/** Adres przeglądu wyniku: Leady → „Lista z researchu” z otwartym wynikiem. */
export function botPeopleHref(resultId: number): string {
  return `/sales/leads?osoby=${resultId}`;
}

interface BotPeopleActionProps {
  companyId: number;
  canEdit: boolean;
  className?: string;
}

/**
 * „Znajdź decydentów (bot)” przy mapie konta i na karcie firmy. Wynik czeka na
 * przegląd: wtedy zamiast przycisku jest odnośnik do niego. Z wyłączonymi
 * zadaniami bota, przy wczytywaniu i błędzie nic nie pokazuje: to dodatek.
 */
export function BotPeopleAction({ companyId, canEdit, className }: BotPeopleActionProps) {
  const query = useBotPeoplePending();
  const start = useStartBotPeople();
  const { showError, showSuccess } = useToast();
  if (!query.isSuccess || !query.data.enabled) return null;
  const pending = query.data.items.find((item) => item.company.id === companyId);
  if (pending) {
    return (
      <span className={cn("inline-flex items-center gap-1.5 text-xs", className)}>
        <Badge variant="info" size="sm">
          Osoby od bota
        </Badge>
        {canEdit ? (
          <Link href={botPeopleHref(pending.id)} className="text-primary hover:underline">
            Przejrzyj: {peopleCount(pending.open)}
          </Link>
        ) : (
          <span className="text-muted-foreground">{peopleCount(pending.open)} czeka na przegląd</span>
        )}
      </span>
    );
  }
  if (!canEdit) return null;
  const running = query.data.running_company_ids.includes(companyId);
  return (
    <Button
      size="sm"
      variant="outline"
      className={cn("shrink-0", className)}
      data-tour="sales.bot-people.find"
      disabled={running}
      title={running ? BOT_PEOPLE_RUNNING : "Bot poszuka osób decyzyjnych na publicznych stronach firmy"}
      loading={start.isPending}
      onClick={() =>
        start.mutate(companyId, {
          onSuccess: () =>
            showSuccess("Bot szuka decydentów. Wynik pojawi się w Leady → „Lista z researchu”."),
          onError: (error) => showError(apiErrorMessage(error, "Nie udało się zlecić biegu bota.")),
        })
      }
    >
      <Bot className="mr-1 h-3.5 w-3.5" aria-hidden /> Znajdź decydentów (bot)
    </Button>
  );
}
