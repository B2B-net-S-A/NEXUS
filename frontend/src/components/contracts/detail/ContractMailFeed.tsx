"use client";

// Poczta kontraktu w zakładce Historia (decyzje Artura 23.11.2026): maile ze
// spraw przy kontrakcie i archiwum administracja@ z home.pl. Treść widzi tylko
// osoba, która widzi kwoty klienta (maile niosą stawki) — reszta temat i nadawcę.

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Mail, Paperclip } from "lucide-react";

import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

interface ContractMail {
  key: string;
  source: "case" | "archive";
  received_at: string | null;
  sender: string | null;
  subject: string | null;
  direction: "in" | "out";
  case_id: number | null;
  case_title: string | null;
  attachments: number;
  excerpt: string | null;
}

interface ContractNotice {
  id: number;
  case_id: number;
  kind: string;
  label: string;
  status: "pending" | "confirmed";
  received_at: string | null;
  proposed_last_day: string | null;
  client_end_date: string | null;
  stale: boolean;
}

export interface ContractMailsResponse {
  notices: ContractNotice[];
  mails: ContractMail[];
  with_body: boolean;
}

function day(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function useContractMails(contractId: number) {
  return useQuery({
    queryKey: ["contracts", contractId, "mails"],
    queryFn: async () => (await api.get<ContractMailsResponse>(`/api/contracts/${contractId}/mails`)).data,
  });
}

export function ContractMailFeed({ contractId }: { contractId: number }) {
  const query = useContractMails(contractId);
  if (query.isError) {
    return (
      <p className="mb-4 text-sm text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać poczty kontraktu.")}
      </p>
    );
  }
  if (!query.isSuccess) {
    return (
      <p role="status" className="mb-4 text-sm text-muted-foreground">
        Wczytuję pocztę…
      </p>
    );
  }
  const { notices, mails, with_body: withBody } = query.data;
  if (notices.length === 0 && mails.length === 0) return null;
  return (
    <section aria-label="Poczta kontraktu" className="mb-6 space-y-3">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Mail aria-hidden className="size-4" /> Poczta ({mails.length})
      </h3>
      {notices.length > 0 ? (
        <ul className="space-y-1 rounded-lg border border-border bg-card p-3 text-[13px]">
          {notices.map((notice) => (
            <li key={notice.id}>
              <span className="font-medium">{notice.label}</span> z maila {day(notice.received_at)}
              {notice.proposed_last_day ? ` · ${day(notice.proposed_last_day)}` : ""}
              {notice.client_end_date && notice.kind !== "client_termination"
                ? ` · klient: ${day(notice.client_end_date)}`
                : ""}
              <span className="text-muted-foreground">
                {" "}
                ({notice.status === "pending" ? "czeka na potwierdzenie w back office" : "potwierdzone"})
              </span>
              {notice.stale ? <span className="text-destructive"> · data już minęła</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {mails.length > 0 ? (
        <ol className="divide-y divide-border rounded-lg border border-border bg-card">
          {mails.map((mail) => (
            <li key={mail.key} className="space-y-0.5 px-3 py-2 text-[13px]">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="min-w-0 truncate font-medium">{mail.subject || "(bez tematu)"}</span>
                <span className="shrink-0 tabular-nums text-[12px] text-muted-foreground">{day(mail.received_at)}</span>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 text-[12px] text-muted-foreground">
                <span>od: {mail.sender ?? "—"}</span>
                <span>{mail.source === "archive" ? "archiwum administracja@" : "sprawa"}</span>
                {mail.case_id ? (
                  <Link href={`/people/cases/${mail.case_id}`} className="hover:underline">
                    {mail.case_title ?? `sprawa #${mail.case_id}`}
                  </Link>
                ) : null}
                {mail.attachments > 0 ? (
                  <span className="inline-flex items-center gap-0.5">
                    <Paperclip aria-hidden className="size-3" /> {mail.attachments}
                  </span>
                ) : null}
              </div>
              {withBody && mail.excerpt ? (
                <p className="line-clamp-3 whitespace-pre-line text-[12.5px] text-muted-foreground">{mail.excerpt}</p>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
