"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Laptop, ShieldAlert } from "lucide-react";

import { ContactActions } from "@/components/phone-preview/contact";
import { PREVIEW_PATH } from "@/components/phone-preview/access";
import { Block, Loaded, Row, Rows, count, plDate } from "@/components/phone-preview/ui";
import { api, type CandidateBlacklistInfo } from "@/lib/api";

// Karta kontaktu kandydata na telefonie (decyzja Artura 14.11.2026). Dane z
// `GET /api/candidates/{id}/quick-view` (ten sam co szybki podgląd na laptopie);
// `via=phone` zapisuje otwarcie w historii kandydata.

interface QuickView {
  candidate: {
    id: number;
    name: string;
    lastname: string;
    email: string | null;
    phone: string | null;
    city: string | null;
    blacklist: CandidateBlacklistInfo | null;
    rate_from_hourly: string | null;
    rate_from_at: string | null;
  };
  current_position: { title: string | null } | null;
  availability: { available_from: string | null; notice_period: number | null; notice_period_unit: string | null } | null;
  current_recruitments: Array<{ job_id: number; job_title: string | null; job_working_title: string | null; client_name: string | null; stage_name: string; moved_at: string; moved_by_name: string | null }>;
  current_recruitments_total: number;
  recent_notes: Array<{ id: number; content: string; created_at: string; author_name: string | null }>;
  contact_attempts: number;
}

const UNITS: Record<string, string> = { days: "dni", weeks: "tyg.", months: "mies." };

export default function PhonePreviewCandidatePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const view = useQuery({
    queryKey: ["phone-preview", "candidate", id],
    queryFn: () => api.get<QuickView>(`/api/candidates/${id}/quick-view`, { params: { via: "phone" } }).then((r) => r.data),
    // Każde otwarcie idzie do serwera (i do historii kandydata), a numer nie
    // zostaje w pamięci podręcznej po wyjściu z karty.
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: "always",
  });
  const c = view.data?.candidate;
  return (
    <div className="pb-6">
      <header className="sticky top-0 z-10 flex items-center gap-1 border-b bg-card px-2 py-2">
        <button type="button" onClick={() => router.back()} aria-label="Wróć" className="flex h-11 w-11 shrink-0 items-center justify-center">
          <ChevronLeft className="h-5 w-5" />
        </button>
        <div className="min-w-0">
          <h1 className="truncate font-semibold">{c ? `${c.name} ${c.lastname}` : "Kandydat"}</h1>
          <p className="truncate text-xs text-muted-foreground">{[view.data?.current_position?.title, c?.city].filter(Boolean).join(" · ")}</p>
        </div>
      </header>
      <div className="px-4 pt-4">
        <Loaded query={view} height="h-40">
          {(v) => (
            <div className="space-y-3">
              {v.candidate.blacklist ? (
                <p className="flex gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm" role="alert">
                  <ShieldAlert className="h-5 w-5 shrink-0 text-destructive-muted-foreground" />
                  <span>Czarna lista{v.candidate.blacklist.reason ? `: ${v.candidate.blacklist.reason}` : ""}. Nie kontaktuj się bez rozmowy z {v.candidate.blacklist.by_name ?? "osobą, która wpisała"}.</span>
                </p>
              ) : null}
              <ContactActions phone={v.candidate.phone} email={v.candidate.email} />
            </div>
          )}
        </Loaded>
      </div>
      {view.data ? (
        <>
          <Block title="Przed telefonem">
            <Rows>
              <Row label="Dostępny od" value={view.data.availability?.available_from ? plDate(view.data.availability.available_from) : "—"} />
              <Row
                label="Okres wypowiedzenia"
                value={view.data.availability?.notice_period ? `${view.data.availability.notice_period} ${UNITS[view.data.availability.notice_period_unit ?? ""] ?? ""}` : "—"}
              />
              <Row label="Stawka od" value={c?.rate_from_hourly ? `${count(Number(c.rate_from_hourly))} zł/h` : "—"} />
              <Row label="Próby kontaktu" value={count(view.data.contact_attempts)} />
            </Rows>
          </Block>
          <Block title="W rekrutacjach" note={`${count(view.data.current_recruitments_total)} w toku`}>
            {view.data.current_recruitments.length === 0 ? (
              <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Nie jest teraz w żadnym procesie.</p>
            ) : (
              <Rows>
                {view.data.current_recruitments.map((r) => (
                  <Link key={`${r.job_id}-${r.stage_name}`} href={`${PREVIEW_PATH}/rekrutacje/${r.job_id}`} className="flex items-center gap-3 px-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{r.job_working_title || r.job_title}</div>
                      <div className="truncate text-xs text-muted-foreground">{r.client_name} · <b className="font-medium text-foreground">{r.stage_name}</b> od {plDate(r.moved_at)}</div>
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </Link>
                ))}
              </Rows>
            )}
          </Block>
          {view.data.recent_notes.length ? (
            <Block title="Ostatnie notatki">
              <Rows>
                {view.data.recent_notes.slice(0, 2).map((n) => (
                  <div key={n.id} className="px-3 py-2.5 text-sm">
                    <p className="line-clamp-3">{n.content}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{n.author_name} · {plDate(n.created_at)}</p>
                  </div>
                ))}
              </Rows>
            </Block>
          ) : null}
          <p className="mx-4 mt-5 flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
            <Laptop className="h-4 w-4 shrink-0" />CV, historia i zapis wyniku rozmowy są na laptopie. Otwarcie tej karty zapisuje się w historii kandydata.
          </p>
        </>
      ) : null}
    </div>
  );
}
