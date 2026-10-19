"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CalendarCheck } from "lucide-react";

import { ConversationDialog } from "@/components/care/ConversationDialog";
import { EmptyState } from "@/components/ds/EmptyState";
import { InlineStats } from "@/components/ds/InlineStats";
import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { useCareWeek, type WeekContact } from "@/lib/api/care";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";

import { ConsultantPanel } from "./ConsultantPanel";
import { ContactsTable } from "./ContactsTable";
import { FeedbackRequestsSection } from "./FeedbackRequestsSection";
import { shiftIso, weekRangeLabel } from "./week-format";

/** `?contract=` — panel osi otwarty z linku (powiadomienie „Konsultant dla front office”). */
export function contractParam(value: string | null | undefined): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

interface TalkTarget {
  contractId: number;
  clientId: number;
  planItem: { id: number; label: string } | null;
}

/**
 * „Opieka · Ten tydzień” (D15): jedna kolejka na tydzień pracy — prośby
 * o opinię od menedżerów u klienta i rozmowy z konsultantami z powodem
 * (punkt planu, umówiony kontakt). Kliknięcie konsultanta otwiera oś
 * z „Przekaż do front office”. Awaria zapytania ≠ pusta kolejka.
 */
export function WeekPanel() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [from, setFrom] = useState<string | null>(null);
  const [talk, setTalk] = useState<TalkTarget | null>(null);
  const query = useCareWeek(scope, from);
  const data = query.data;
  // Panel z adresu (link z powiadomienia) i z kliknięcia; adres pisze
  // `useUrlWriter` (natywna historia), więc stan trzymamy też lokalnie.
  const urlContract = contractParam(searchParams?.get("contract"));
  const [selected, setSelected] = useState<number | null>(urlContract);
  useEffect(() => setSelected(urlContract), [urlContract]);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (data?.contacts.length ?? 0) + (data?.feedback.length ?? 0) === 0,
  });

  const setContract = (id: number | null) => {
    setSelected(id);
    const params = new URLSearchParams(window.location.search);
    if (id == null) params.delete("contract");
    else params.set("contract", String(id));
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };
  const talkTo = (row: WeekContact) => {
    const plan = row.reasons.find((reason) => reason.plan_item_id != null);
    setTalk({
      contractId: row.contract_id,
      clientId: row.client_id,
      planItem: plan?.plan_item_id ? { id: plan.plan_item_id, label: plan.label } : null,
    });
  };
  const selectedRow = data?.contacts.find((row) => row.contract_id === selected) ?? null;

  const list = (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Tydzień">
          <Button
            size="sm"
            variant="ghost"
            aria-label="Poprzedni tydzień"
            disabled={!data}
            onClick={() => data && setFrom(shiftIso(data.week.from, -7))}
          >
            ‹
          </Button>
          <span className="min-w-36 text-center text-sm font-medium tabular-nums">
            {data
              ? `${data.week.is_current ? "Ten tydzień" : "Tydzień"} · ${weekRangeLabel(data.week.from, data.week.to)}`
              : "Ten tydzień"}
          </span>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Następny tydzień"
            disabled={!data}
            onClick={() => data && setFrom(shiftIso(data.week.from, 7))}
          >
            ›
          </Button>
          {data && !data.week.is_current ? (
            <Button size="sm" variant="ghost" onClick={() => setFrom(null)}>
              Wróć do tego tygodnia
            </Button>
          ) : null}
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="Zakres listy">
          {(
            [
              ["mine", "Moi"],
              ["all", "Wszyscy w moim zakresie"],
            ] as const
          ).map(([value, label]) => (
            <Button
              key={value}
              size="sm"
              variant={scope === value ? "secondary" : "ghost"}
              aria-pressed={scope === value}
              onClick={() => setScope(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie tygodnia…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" || !data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={
            state === "error" ? "Nie udało się wczytać kolejki na ten tydzień." : undefined
          }
          onRetry={() => query.refetch()}
        />
      ) : (
        <>
          <InlineStats
            id="care-week-stats"
            stats={[
              { id: "contacts", label: "kontaktów", value: data.counts.contacts },
              { id: "overdue", label: "zaległe", value: data.counts.overdue },
              ...(data.feedback_visible
                ? [{ id: "feedback", label: "opinie od menedżerów", value: data.counts.feedback }]
                : []),
              {
                id: "front-office",
                label: "do przekazania",
                value: data.counts.front_office,
                title: "Kończą projekt w ciągu 60 dni albo chcą zmiany projektu",
              },
            ]}
          />
          {state === "empty" ? (
            <EmptyState
              icon={CalendarCheck}
              title="W tym tygodniu nie ma zaplanowanych kontaktów"
              description={
                scope === "mine"
                  ? "Kontakty z planu opieki i umówione rozmowy Twoich konsultantów pojawią się tutaj."
                  : undefined
              }
              action={
                // Admin i osoby bez podopiecznych widziały tu pustkę, a w
                // „Wszyscy” czekało kilkaset kontaktów (testy produkcji 19.10).
                scope === "mine" ? (
                  <Button size="sm" variant="outline" onClick={() => setScope("all")}>
                    Pokaż wszystkich w moim zakresie
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <>
              <FeedbackRequestsSection items={data.feedback} canWrite={data.can_write_feedback} />
              {data.contacts.length ? (
                <section className="space-y-1.5" aria-labelledby="care-week-contacts">
                  <h3
                    id="care-week-contacts"
                    className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    Rozmowa z konsultantem
                  </h3>
                  <ContactsTable
                    rows={data.contacts}
                    today={data.week.today}
                    canEdit={data.can_edit}
                    showOwner={scope === "all"}
                    selectedId={selected}
                    onOpen={(row) => setContract(row.contract_id)}
                    onTalk={talkTo}
                  />
                </section>
              ) : null}
            </>
          )}
        </>
      )}
    </div>
  );

  return (
    <>
      <ListDetailLayout
        list={list}
        panel={
          selected != null ? (
            <ConsultantPanel
              key={selected}
              contractId={selected}
              onClose={() => setContract(null)}
              onTalk={(clientId) =>
                selectedRow
                  ? talkTo(selectedRow)
                  : setTalk({ contractId: selected, clientId, planItem: null })
              }
            />
          ) : null
        }
        onClose={() => setContract(null)}
        panelLabel="Oś konsultanta"
      />
      {talk ? (
        <ConversationDialog
          contractId={talk.contractId}
          clientId={talk.clientId}
          planItem={talk.planItem}
          open
          onOpenChange={(open) => {
            if (!open) setTalk(null);
          }}
        />
      ) : null}
    </>
  );
}
