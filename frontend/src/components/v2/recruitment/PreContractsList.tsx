"use client";

/**
 * Rekrutacje › Umowy przedwstępne (0506, 21.10.2026).
 *
 * Head of Recruitment, Finanse, Rada nadzorcza i Automatyzacje widzą
 * wszystkie prośby, Delivery Lead swoich klientów i swoje prośby, rekruter to,
 * co wystawia, i to, o co prosił (zakres liczy serwer). Zakładka w adresie
 * (`?tab=`) — link z kafelka i dzwonka. Rada nadzorcza nie otwiera panelu
 * osoby (decyzja Artura 23.10.2026), więc osoba jest dla niej tekstem.
 */

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import {
  PRE_CONTRACT_TABS,
  PRE_CONTRACT_TONE_CLASS,
  usePreContractList,
  type PreContractRequest,
  type PreContractTab,
} from "@/lib/api/preContracts";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { isBoardOnly, useAuthStore } from "@/store/auth";

const TAB_KEYS = new Set<string>(PRE_CONTRACT_TABS.map((t) => t.value));

export function preContractTabFromParam(value: string | null): PreContractTab {
  return value && TAB_KEYS.has(value) ? (value as PreContractTab) : "todo";
}

function dayPl(iso?: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function sinceWho(r: PreContractRequest): { when: string; who: string } {
  const last = r.events[r.events.length - 1];
  if (last) return { when: dayPl(last.at), who: last.actor?.name ?? "" };
  return { when: dayPl(r.requested_at), who: r.requested_by?.name ?? "" };
}

export function PreContractsList() {
  const searchParams = useSearchParams();
  const pathname = usePathname() ?? "";
  const { replaceUrl } = useUrlWriter();
  const tab = preContractTabFromParam(searchParams?.get("tab") ?? null);
  const list = usePreContractList(tab);
  const opensPersonPanel = !isBoardOnly(useAuthStore((s) => s.user));

  const setTab = (next: PreContractTab) => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    if (next === "todo") params.delete("tab");
    else params.set("tab", next);
    const qs = params.toString();
    replaceUrl(qs ? `${pathname}?${qs}` : pathname);
  };

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Zakładki umów przedwstępnych" className="flex flex-wrap gap-2">
        {PRE_CONTRACT_TABS.map((t) => {
          const count = list.data?.counts?.[t.value];
          const active = t.value === tab;
          return (
            <button
              key={t.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.value)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-sm font-medium",
                active ? "border-foreground bg-foreground text-background" : "border-border bg-background hover:bg-muted",
              )}
            >
              {t.label}
              {count != null && t.value !== "all" ? <span className="ml-1 tabular-nums">· {count}</span> : null}
            </button>
          );
        })}
      </div>

      {list.isLoading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Wczytuję umowy…
        </p>
      ) : list.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się wczytać umów przedwstępnych.{" "}
          <button type="button" className="font-medium underline" onClick={() => void list.refetch()}>
            Ponów
          </button>
        </p>
      ) : list.isSuccess && list.data.items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {tab === "todo" ? "Nic do zrobienia — wszystkie prośby mają podpisane umowy." : "Brak umów w tej zakładce."}
        </p>
      ) : list.isSuccess ? (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[880px] text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Osoba</th>
                <th scope="col" className="px-3 py-2 font-medium">Rekrutacja · klient</th>
                <th scope="col" className="px-3 py-2 font-medium">Etap</th>
                <th scope="col" className="px-3 py-2 font-medium">Poprosił · na kiedy</th>
                <th scope="col" className="px-3 py-2 font-medium">Stan umowy</th>
                <th scope="col" className="px-3 py-2 font-medium">Wystawia</th>
                <th scope="col" className="px-3 py-2 font-medium">Ostatni krok</th>
                <th scope="col" className="px-3 py-2 font-medium">Ważna do</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((r) => {
                const last = sinceWho(r);
                return (
                  <tr key={r.id} className="border-t border-border align-top" data-testid="pre-contract-row">
                    <td className="px-3 py-2 font-medium">
                      {opensPersonPanel ? (
                        <Link
                          href={`/jobs/${r.job_id}?candidate=${r.candidate_id}`}
                          className="hover:underline"
                        >
                          {r.candidate_name}
                        </Link>
                      ) : (
                        r.candidate_name
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {r.job_title}
                      {r.client_name ? <span className="block text-xs text-muted-foreground">{r.client_name}</span> : null}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{r.stage_name ?? "—"}</td>
                    <td className="px-3 py-2">
                      {r.requested_by?.name ?? "—"}
                      <span className="block text-xs text-muted-foreground">{r.needed_before_label}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn("inline-block rounded px-2 py-0.5 text-xs font-semibold", PRE_CONTRACT_TONE_CLASS[r.badge.tone])}
                        title={r.badge.detail}
                      >
                        {r.badge.label}
                      </span>
                      {r.candidate_signature_form_label ? (
                        <span className="block text-xs text-muted-foreground">kandydat: {r.candidate_signature_form_label}</span>
                      ) : null}
                      {r.withdrawal ? (
                        <span className="block text-xs text-muted-foreground">
                          {r.withdrawal.kind_label}
                          {r.withdrawal.decision
                            ? ` · ${r.withdrawal.decision === "demand" ? "wezwanie do zapłaty" : "bez kary"}`
                            : " · czeka na decyzję"}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">{r.assignee?.name ?? "—"}</td>
                    <td className="px-3 py-2">
                      {last.when}
                      {last.who ? <span className="block text-xs text-muted-foreground">{last.who}</span> : null}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {dayPl(r.valid_until)}
                      {r.b2b_deadline ? (
                        <span className="block text-xs font-medium text-destructive">B2B do {dayPl(r.b2b_deadline)}</span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Head of Recruitment, Finanse, Rada nadzorcza i Automatyzacje widzą wszystkie prośby,
        Delivery Lead swoich klientów i swoje prośby, pozostali to, o co prosili, co wystawiają
        albo obserwują.
      </p>
    </div>
  );
}
