"use client";

/**
 * Oddanie osoby z blokadą „Biorę” w wierszu „Prowadzi” panelu osoby
 * (prośba rekruterki i decyzja Artura z 25.11.2026, makiety:
 * https://claude.ai/artifact/RYsL53ApEcA3CMEcsCLrrd). Trzy drogi:
 *
 * - „Oddaj…” — osoba z blokadą wybiera kogoś z zespołu, ta dostaje 12 h;
 * - „Zwolnij” — blokada kończy się teraz, „Biorę” może kliknąć każdy;
 * - „Poproś o oddanie” — prośba w panelu i dzwonku, odpowiedź „Oddaj”/„Zostaw”.
 *
 * Reguły: docs/claude/rekrutacja-tablica/oddanie-osoby-z-blokada.md.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cardShortName } from "@/lib/board-card-badges";
import { useAuthStore } from "@/store/auth";

export type HandoverItem = Pick<
  KanbanItem,
  | "candidate_id"
  | "claim_user_id"
  | "claim_user_name"
  | "claim_until"
  | "claim_request_user_id"
  | "claim_request_user_name"
  | "claim_request_reason"
  | "can_hand_over"
  | "can_ask"
>;

export interface HandoverView {
  /** Patrzący ma aktywną blokadę i serwer przyjmie „Oddaj…”, „Zwolnij”, odpowiedź. */
  holder: boolean;
  /** Blokadę ma ktoś inny: stan prośby albo „Poproś o oddanie”. */
  other: boolean;
  /** Serwer przyjmie prośbę patrzącego (rola rekrutera, otwarta rekrutacja, kolumna). */
  canAsk: boolean;
  /** Prośba czeka (serwer podaje ją tylko przy aktywnej blokadzie). */
  request: { userId: number; name: string; reason: string | null } | null;
  /** Prośba patrzącego czeka na odpowiedź. */
  askedByMe: boolean;
}

export function handoverView(item: HandoverItem, viewerId: number | null, now: Date = new Date()): HandoverView {
  const active =
    item.claim_user_id != null && Boolean(item.claim_until) && new Date(item.claim_until ?? 0).getTime() > now.getTime();
  // Przyciski idą za polami serwera (`can_hand_over`, `can_ask`), jak „Biorę” za
  // `can_take`: zamknięta rekrutacja albo karta poza „Nowymi” ich nie ma.
  const mine = active && viewerId != null && item.claim_user_id === viewerId;
  const holder = mine && item.can_hand_over === true;
  const request =
    active && item.claim_request_user_id != null
      ? {
          userId: item.claim_request_user_id,
          name: item.claim_request_user_name?.trim() || "Ktoś z zespołu",
          reason: item.claim_request_reason?.trim() || null,
        }
      : null;
  return {
    holder,
    other: active && !mine,
    canAsk: active && !mine && item.can_ask === true,
    request,
    askedByMe: request != null && viewerId != null && request.userId === viewerId,
  };
}

interface Person {
  id: number;
  name: string | null;
  role: string;
  roles?: string[] | null;
  is_active?: boolean;
}

/** Oddać można aktywnej osobie z rolą rekrutera (jak „Prowadzi”). */
function canReceive(person: Person, viewerId: number | null): boolean {
  if (person.is_active === false || person.id === viewerId) return false;
  const roles = person.roles?.length ? person.roles : [person.role];
  return roles.some((r) => r === "recruiter" || r === "sourcer" || r === "tac");
}

function useClaimCall(jobId: number) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  return useMutation({
    mutationFn: async ({ path, body }: { path: string; body: Record<string, unknown>; done: string }) =>
      (await api.post(`/api/pipeline/claim${path}`, body)).data,
    onSuccess: (_data, vars) => {
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      showSuccess(vars.done);
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać zmiany.")),
  });
}

interface HandoverProps {
  item: HandoverItem;
  jobId: number;
  /** Panel tylko do odczytu („Podgląd jako”): bez przycisków. */
  readOnly?: boolean;
}

const linkClass =
  "shrink-0 rounded-md px-1 font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 pointer-coarse:p-2";

/** Przyciski na końcu wiersza z blokadą. */
export function ClaimHandoverActions({ item, jobId, readOnly = false }: HandoverProps) {
  const viewerId = useAuthStore((s) => s.user?.id ?? null);
  const view = handoverView(item, viewerId);
  const call = useClaimCall(jobId);
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const [giving, setGiving] = useState(false);
  const holderFirst = cardShortName(item.claim_user_name) ?? "osoba z blokadą";
  const ids = { candidate_id: item.candidate_id, job_id: jobId };

  if (readOnly || (!view.holder && !view.other)) return null;

  const release = async () => {
    const ok = await askConfirm({
      title: "Zwolnić blokadę?",
      description:
        "Karta będzie wolna: pierwsza osoba, która kliknie „Biorę”, dostanie ją na 12 h. Twoje imię zostaje na karcie do tego czasu.",
      confirmLabel: "Zwolnij",
    });
    if (ok) call.mutate({ path: "/release", body: ids, done: "Zwolniono — osobę może wziąć każdy." });
  };

  const ask = async () => {
    const reason = await askReason({
      title: `Poproś: ${holderFirst} odda Ci tę osobę`,
      description: `${holderFirst} dostanie prośbę w dzwonku i odda jednym kliknięciem. Bez zgody blokada zostaje do końca.`,
      confirmLabel: "Wyślij prośbę",
      field: {
        label: `Dlaczego (zobaczy ${holderFirst})`,
        placeholder: "Np. rozmawiam z nią od dawna, mam z nią relację",
        minLength: 3,
        maxLength: 300,
      },
    });
    if (reason) call.mutate({ path: "/request", body: { ...ids, reason }, done: `Prośba wysłana do: ${holderFirst}.` });
  };

  return (
    <>
      {view.holder ? (
        <>
          <button type="button" className={linkClass} onClick={() => setGiving(true)} disabled={call.isPending} data-testid="claim-handover-give">
            Oddaj…
          </button>
          <button type="button" className={linkClass} onClick={release} disabled={call.isPending} data-testid="claim-handover-release">
            Zwolnij
          </button>
        </>
      ) : view.askedByMe ? (
        <span className="shrink-0 rounded bg-warning/15 px-1.5 font-semibold text-warning" data-testid="claim-handover-asked">
          Prośba wysłana
        </span>
      ) : view.request ? (
        <span className="shrink-0 truncate" title={`O tę osobę prosi już ${view.request.name}`}>
          · prosi {cardShortName(view.request.name)}
        </span>
      ) : view.canAsk ? (
        <button type="button" className={linkClass} onClick={ask} disabled={call.isPending} data-testid="claim-handover-ask">
          Poproś o oddanie
        </button>
      ) : null}
      {giving ? <GiveDialog item={item} jobId={jobId} viewerId={viewerId} onClose={() => setGiving(false)} /> : null}
      {confirmDialog}
    </>
  );
}

/** Pasek prośby pod „Prowadzi” — widzi go osoba z blokadą. */
export function ClaimRequestBanner({ item, jobId, readOnly = false }: HandoverProps) {
  const viewerId = useAuthStore((s) => s.user?.id ?? null);
  const view = handoverView(item, viewerId);
  const call = useClaimCall(jobId);
  if (readOnly || !view.holder || !view.request) return null;
  const first = cardShortName(view.request.name) ?? view.request.name;
  const answer = (accept: boolean) =>
    call.mutate({
      path: "/request/answer",
      body: { candidate_id: item.candidate_id, job_id: jobId, accept },
      done: accept ? `Oddane — ${first} ma osobę na 12 h.` : `Zostaje u Ciebie. ${first} dostanie znać.`,
    });
  return (
    <div
      className="mt-1 flex min-w-0 items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] text-foreground"
      data-testid="claim-request-banner"
    >
      <span className="min-w-0 flex-1 truncate" title={view.request.reason ?? undefined}>
        <span className="font-semibold">{view.request.name}</span> prosi o tę osobę
        {view.request.reason ? `: „${view.request.reason}”` : ""}
      </span>
      <button
        type="button"
        disabled={call.isPending}
        onClick={() => answer(true)}
        className="shrink-0 rounded bg-primary px-1.5 font-semibold leading-[18px] text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      >
        Oddaj — {first}
      </button>
      <button type="button" disabled={call.isPending} onClick={() => answer(false)} className={linkClass}>
        Zostaw
      </button>
    </div>
  );
}

function GiveDialog({
  item,
  jobId,
  viewerId,
  onClose,
}: {
  item: HandoverItem;
  jobId: number;
  viewerId: number | null;
  onClose: () => void;
}) {
  const people = useQuery<Person[]>({
    queryKey: ["pair-owner-people"],
    queryFn: async () => {
      const { data } = await api.get<unknown>("/api/users/mentionable", { params: { include_inactive: "true" } });
      return Array.isArray(data) ? (data as Person[]) : [];
    },
    staleTime: 60_000,
  });
  const call = useClaimCall(jobId);
  const candidates = (people.data ?? []).filter((p) => canReceive(p, viewerId));
  const [picked, setPicked] = useState<number | null>(null);
  const pickedPerson = candidates.find((p) => p.id === picked) ?? null;
  const first = cardShortName(pickedPerson?.name ?? null);
  return (
    <AppModal
      open
      onOpenChange={(next) => (next ? null : onClose())}
      title="Oddaj osobę w tej rekrutacji"
      description="Masz ją na wyłączność przez „Biorę”. Oddajesz od razu, bez czekania na koniec blokady."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={!pickedPerson || call.isPending}
            onClick={() =>
              call.mutate(
                {
                  path: "/handover",
                  body: { candidate_id: item.candidate_id, job_id: jobId, to_user_id: picked },
                  done: `Oddane — ${pickedPerson?.name ?? "wybrana osoba"} ma osobę na 12 h.`,
                },
                { onSuccess: onClose },
              )
            }
          >
            {call.isPending ? "Oddaję…" : first ? `Oddaj — ${first}` : "Oddaj"}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="space-y-1">
          <label className="block text-xs font-medium text-foreground" htmlFor="claim-handover-person">
            Komu
          </label>
          <select
            id="claim-handover-person"
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            value={picked ?? ""}
            onChange={(e) => setPicked(e.target.value ? Number(e.target.value) : null)}
            disabled={people.isLoading}
          >
            <option value="">{people.isLoading ? "Wczytywanie osób…" : "Wybierz osobę…"}</option>
            {candidates.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name ?? `Konto nr ${p.id}`}
              </option>
            ))}
          </select>
          {people.isError ? (
            <p className="text-[11px] text-destructive">
              {apiErrorMessage(people.error, "Nie udało się wczytać listy osób.")}
            </p>
          ) : null}
        </div>
        <div className="rounded-md border border-border bg-muted/30 p-2.5 text-xs">
          <div className="mb-1 font-semibold text-foreground">Po oddaniu</div>
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            <li>{first ?? "Wybrana osoba"} ma blokadę 12 h od teraz, imię na karcie i w filtrze „Kto dodał”</li>
            <li>dostaje dzwonek z linkiem do karty, a umówiony telefon idzie razem z osobą</li>
            <li>Liga, cele i premia liczą się jak przy „Biorę”: według tego, kto zweryfikuje</li>
          </ul>
        </div>
      </div>
    </AppModal>
  );
}
