"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CARD_STATUS_LABELS,
  CHANNEL_LABELS,
  HIRING_SOURCE_LABELS,
  INITIATIVE_KIND_LABELS,
  OWNER_SOURCE_LABELS,
  REDEPLOY_REASON_LABELS,
  REDEPLOY_STATUS_LABELS,
  useCareOwners,
  useContractCare,
  useSetContractOwner,
  useUpdatePlanItem,
  type CarePlanItem,
  type ContractCare,
  type TechCard,
} from "@/lib/api/care";
import { formatDate } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { careTimeline, conversationSignals } from "./care-format";
import { ConversationDialog } from "./ConversationDialog";
import { TechCardDialog } from "./TechCardDialog";

const DEFAULT_OWNER = "default";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

function OwnerPicker({ care }: { care: ContractCare }) {
  const { showToast } = useToast();
  const owners = useCareOwners(care.can_edit);
  const save = useSetContractOwner(care.contract.id);
  const value = care.owner.explicit && care.owner.user ? String(care.owner.user.id) : DEFAULT_OWNER;
  return (
    <Select
      value={value}
      onValueChange={(next) =>
        save.mutate(next === DEFAULT_OWNER ? null : Number(next), {
          onSuccess: () => showToast("Opiekun zmieniony", "success"),
          onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić opiekuna."), "error"),
        })
      }
      disabled={save.isPending}
    >
      <SelectTrigger aria-label="Opiekun kontraktu" className="h-8 w-56">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={DEFAULT_OWNER}>Domyślny (klient albo DL)</SelectItem>
        {(owners.data ?? []).map((owner) => (
          <SelectItem key={owner.id} value={String(owner.id)}>
            {owner.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function PlanList({ care, onRecord }: { care: ContractCare; onRecord: (item: CarePlanItem) => void }) {
  const { showToast } = useToast();
  const update = useUpdatePlanItem(care.contract.id);
  if (!care.plan.length) {
    return (
      <p className="text-sm text-muted-foreground">
        {care.contract.start_date
          ? "Plan pojawi się, gdy kontrakt będzie aktywny."
          : "Kontrakt nie ma daty startu — plan liczy się od niej."}
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border/60">
      {care.plan.map((item) => (
        <li key={item.id} className="flex items-center justify-between gap-2 py-1.5 text-sm">
          <StatusDot
            tone={
              item.status === "done"
                ? "success"
                : item.status === "skipped"
                  ? "neutral"
                  : item.overdue
                    ? "danger"
                    : "info"
            }
            note={
              item.status === "done"
                ? "zrobiony"
                : item.status === "skipped"
                  ? "pominięty"
                  : item.overdue
                    ? "po terminie"
                    : undefined
            }
          >
            {item.label} · {formatDate(item.due_on)}
          </StatusDot>
          {care.can_edit && item.status === "open" ? (
            <span className="flex shrink-0 gap-1">
              <Button variant="ghost" size="sm" onClick={() => onRecord(item)}>
                Zapisz
              </Button>
              <Button
                variant="quiet"
                size="sm"
                disabled={update.isPending}
                onClick={() =>
                  update.mutate(
                    { itemId: item.id, status: "skipped" },
                    {
                      onError: (err) =>
                        showToast(apiErrorMessage(err, "Nie udało się pominąć kontaktu."), "error"),
                    },
                  )
                }
              >
                Pomiń
              </Button>
            </span>
          ) : null}
          {care.can_edit && item.status === "skipped" ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={update.isPending}
              onClick={() => update.mutate({ itemId: item.id, status: "open" })}
            >
              Przywróć
            </Button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function CardBody({ card }: { card: TechCard }) {
  return (
    <div className="grid gap-1.5 text-sm">
      <span className="text-muted-foreground">
        {[
          card.area ? `Obszar ${card.area.name}` : null,
          card.team_size ? `zespół ${card.team_size}` : null,
          card.team_externals != null ? `z zewnątrz ${card.team_externals}` : null,
          card.satisfaction ? `zadowolenie ${card.satisfaction}/5` : null,
        ]
          .filter(Boolean)
          .join(" · ") || "Bez szczegółów zespołu"}
      </span>
      {card.skills.length || card.unrecognized_skills.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Technologie">
          {card.skills.map((skill) => (
            <li key={skill.id} className="rounded-md border border-border bg-muted/40 px-2 py-0.5 text-xs">
              {skill.name}
            </li>
          ))}
          {card.unrecognized_skills.map((name) => (
            <li
              key={name}
              className="rounded-md border border-dashed border-border px-2 py-0.5 text-xs text-muted-foreground"
              title="Spoza słownika — czeka na przejrzenie"
            >
              {name}
            </li>
          ))}
        </ul>
      ) : null}
      {card.initiatives.length ? (
        <span className="text-muted-foreground">
          Inicjatywy:{" "}
          {card.initiatives
            .map((item) => `${item.name} (${INITIATIVE_KIND_LABELS[item.kind] ?? item.kind})`)
            .join(", ")}
        </span>
      ) : null}
      {card.vendors.length ? (
        <span className="text-muted-foreground">
          Dostawcy: {card.vendors.map((vendor) => vendor.name).join(", ")}
        </span>
      ) : null}
      {card.hiring ? (
        <span>
          Klient zatrudnia
          {card.hiring_roles.length ? `: ${card.hiring_roles.join(", ")}` : ""}
          {card.hiring_source ? ` · ${HIRING_SOURCE_LABELS[card.hiring_source]}` : ""}
          {card.sales_status === "converted" ? " · sprzedaż: szansa" : ""}
          {card.sales_status === "archived" ? " · sprzedaż: zarchiwizowany" : ""}
        </span>
      ) : null}
      {card.memorable_quote ? <q className="text-muted-foreground">{card.memorable_quote}</q> : null}
      {card.note ? <p className="whitespace-pre-line">{card.note}</p> : null}
    </div>
  );
}

function Timeline({ care, onEditCard }: { care: ContractCare; onEditCard: (card: TechCard) => void }) {
  const entries = careTimeline(care.conversations, care.tech_cards);
  if (!entries.length) {
    return (
      <p className="text-sm text-muted-foreground">
        Nie ma jeszcze rozmów. Pierwszy kontakt wypada w planie po lewej.
      </p>
    );
  }
  return (
    <ol className="space-y-3">
      {entries.map((entry) => (
        <li key={`${entry.kind}-${entry.id}`} className="grid grid-cols-[72px_minmax(0,1fr)] gap-3">
          <span className="pt-0.5 text-xs tabular-nums text-muted-foreground">
            {formatDate(entry.date)}
          </span>
          {entry.kind === "conversation" ? (
            <div className="grid gap-1 text-sm">
              <span className="font-medium">
                {CHANNEL_LABELS[entry.item.channel]}
                {entry.item.author ? ` · ${entry.item.author.name}` : ""}
                {entry.item.satisfaction ? ` · zadowolenie ${entry.item.satisfaction}/5` : ""}
              </span>
              {conversationSignals(entry.item).length ? (
                <span className="text-xs text-muted-foreground">
                  Sygnały: {conversationSignals(entry.item).join(" · ")}
                  {entry.item.project_end_on ? ` (${formatDate(entry.item.project_end_on)})` : ""}
                </span>
              ) : null}
              {entry.item.note ? <p className="whitespace-pre-line">{entry.item.note}</p> : null}
              {entry.item.client_hiring_note ? (
                <span className="text-muted-foreground">Klient szuka: {entry.item.client_hiring_note}</span>
              ) : null}
              {entry.item.follow_up_on ? (
                <span className="text-xs text-muted-foreground">
                  Następny kontakt: {formatDate(entry.item.follow_up_on)}
                </span>
              ) : null}
            </div>
          ) : (
            <div className="grid gap-1">
              <span className="flex items-center justify-between gap-2 text-sm font-medium">
                <span>
                  Karta technologiczna
                  {entry.item.author ? ` · ${entry.item.author.name}` : ""}
                  {entry.item.is_draft
                    ? " · szkic"
                    : entry.item.status
                      ? ` · ${CARD_STATUS_LABELS[entry.item.status]}`
                      : ""}
                </span>
                {care.can_edit ? (
                  <Button variant="ghost" size="sm" onClick={() => onEditCard(entry.item)}>
                    Edytuj
                  </Button>
                ) : null}
              </span>
              <CardBody card={entry.item} />
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

/** Zakładka „Opieka” kontraktu: opiekun, plan kontaktów, oś rozmów i kart. */
export function ContractCareTab({ contractId }: { contractId: number }) {
  const query = useContractCare(contractId);
  const [conversationFor, setConversationFor] = useState<CarePlanItem | null | undefined>(undefined);
  const [cardDialog, setCardDialog] = useState<{ card: TechCard | null } | null>(null);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <p className="p-4 text-sm text-muted-foreground">Wczytywanie opieki…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "forbidden" || state === "not_found"
            ? apiErrorMessage(query.error, "Nie możesz zobaczyć opieki tego kontraktu.")
            : undefined
        }
        onRetry={() => query.refetch()}
      />
    );
  }
  const care = query.data;
  const activeRedeploy = care.redeploy.filter((item) => item.status === "open" || item.status === "in_progress");
  const latestHiring = care.tech_cards.find((card) => card.hiring && !card.is_draft);

  return (
    <div className="space-y-3">
      {care.can_edit ? (
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setConversationFor(null)}>
            Zapisz rozmowę
          </Button>
          <Button size="sm" onClick={() => setCardDialog({ card: null })}>
            Karta technologiczna
          </Button>
        </div>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="grid content-start gap-3">
          <Section title="Opieka">
            <Fact label="Opiekun">
              {care.owner.user ? care.owner.user.name : "Brak — ustaw opiekuna"}
            </Fact>
            {care.owner.source ? (
              <p className="text-right text-xs text-muted-foreground">
                {OWNER_SOURCE_LABELS[care.owner.source]}
              </p>
            ) : null}
            {care.can_edit ? (
              <div className="flex justify-end">
                <OwnerPicker care={care} />
              </div>
            ) : null}
            <Fact label="Dzień współpracy">{care.contract.day_of_cooperation ?? "—"}</Fact>
            <Fact label="Zadowolenie">
              {care.last_satisfaction
                ? `${care.last_satisfaction.value} / 5 · ${formatDate(care.last_satisfaction.on)}`
                : "—"}
            </Fact>
            <Fact label="Następny kontakt">
              {care.next_contact ? (
                <span className={care.next_contact.overdue ? "text-destructive" : undefined}>
                  {care.next_contact.label} · {formatDate(care.next_contact.due_on)}
                </span>
              ) : (
                "—"
              )}
            </Fact>
          </Section>
          <Section title="Plan kontaktów">
            <PlanList care={care} onRecord={(item) => setConversationFor(item)} />
          </Section>
          <Section title="Sygnały">
            {care.project_end?.end_on ? (
              <Fact label="Koniec projektu">{formatDate(care.project_end.end_on)}</Fact>
            ) : null}
            {latestHiring ? (
              <Fact label="Klient zatrudnia">
                {latestHiring.hiring_roles.join(", ") || "tak"}
              </Fact>
            ) : null}
            {activeRedeploy.length ? (
              <ul className="space-y-1 text-sm">
                {activeRedeploy.map((item) => (
                  <li key={item.id}>
                    <StatusDot tone="warning" note={REDEPLOY_STATUS_LABELS[item.status]}>
                      Do przepięcia: {REDEPLOY_REASON_LABELS[item.reason]}
                      {item.due_on ? ` · ${formatDate(item.due_on)}` : ""}
                    </StatusDot>
                  </li>
                ))}
              </ul>
            ) : null}
            {!care.project_end?.end_on && !latestHiring && !activeRedeploy.length ? (
              <p className="text-sm text-muted-foreground">Brak sygnałów z rozmów.</p>
            ) : null}
          </Section>
        </div>
        <Section title="Oś opieki">
          <Timeline care={care} onEditCard={(card) => setCardDialog({ card })} />
        </Section>
      </div>
      {conversationFor !== undefined ? (
        <ConversationDialog
          contractId={contractId}
          planItem={conversationFor}
          open
          onOpenChange={(open) => {
            if (!open) setConversationFor(undefined);
          }}
        />
      ) : null}
      {cardDialog ? (
        <TechCardDialog
          contractId={contractId}
          clientId={care.contract.client_id}
          card={cardDialog.card}
          open
          onOpenChange={(open) => {
            if (!open) setCardDialog(null);
          }}
        />
      ) : null}
    </div>
  );
}
