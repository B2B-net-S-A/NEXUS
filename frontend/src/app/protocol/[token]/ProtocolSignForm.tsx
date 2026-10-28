"use client";

/**
 * Formularz `/protocol/{token}`: treść protokołu, imię i nazwisko, zgoda.
 * Publiczne API przez zwykły `fetch` (nigdy instancja axios z sesją).
 */
import { useState } from "react";
import { CheckCircle2, FileDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";

export interface PublicProtocolBlock {
  type: "paragraph" | "table";
  text?: string;
  rows?: string[][];
}

export interface PublicProtocol {
  number: string;
  kind: "wydanie" | "zwrot";
  protocol_date: string;
  holder_name: string;
  issuer_name: string;
  expires_at: string;
  total: string;
  lines: { position: number; name: string; identifier: string | null; value: string | null }[];
  document: PublicProtocolBlock[];
}

/** Linie podpisów z pliku do druku — na stronie zastępuje je formularz. */
const SIGNATURE_LINE = /^(Strona przekazująca Strona przyjmująca|\(podpis\) \(podpis\))$/;

export function visibleBlocks(blocks: PublicProtocolBlock[]): PublicProtocolBlock[] {
  return blocks.filter((block) => {
    // Wzór standardowy (28.10.2026) ma podpisy w tabelce bez ramek.
    if (block.type === "table") return !SIGNATURE_LINE.test((block.rows?.[0] ?? []).join(" "));
    const text = (block.text ?? "").replace(/\s+/g, " ").trim();
    return text !== "" && !SIGNATURE_LINE.test(text);
  });
}

function browserApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

async function failure(res: Response, fallback: string): Promise<Error> {
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    data = undefined;
  }
  return new Error(apiErrorMessage({ response: { status: res.status, data } }, fallback));
}

export function ProtocolSignForm({ token, protocol }: { token: string; protocol: PublicProtocol }) {
  const [name, setName] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const base = `${browserApiBase()}/api/public/equipment-protocols/${encodeURIComponent(token)}`;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSending(true);
    setError(null);
    try {
      const res = await fetch(`${base}/sign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signer_name: name.trim(), accepted: true }),
      });
      if (!res.ok) throw await failure(res, "Nie udało się zapisać potwierdzenia.");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nie udało się zapisać potwierdzenia.");
    } finally {
      setSending(false);
    }
  };

  const openPdf = async () => {
    setPdfError(null);
    try {
      const res = await fetch(`${base}/document.pdf`);
      if (!res.ok) throw await failure(res, "PDF jest chwilowo niedostępny.");
      const url = URL.createObjectURL(await res.blob());
      window.open(url, "_blank", "noopener");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setPdfError(err instanceof Error ? err.message : "PDF jest chwilowo niedostępny.");
    }
  };

  if (done) {
    return (
      <div role="status" className="flex items-start gap-3 rounded-lg border border-border bg-card p-5">
        <CheckCircle2 className="mt-0.5 h-5 w-5 text-success" aria-hidden />
        <div>
          <p className="font-medium">Dziękujemy — odbiór potwierdzony.</p>
          <p className="text-sm text-muted-foreground">
            Recepcja zatwierdzi podpis protokołu {protocol.number}. Link przestał działać.
          </p>
        </div>
      </div>
    );
  }

  const expires = new Date(protocol.expires_at).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Warsaw",
  });

  return (
    <div className="space-y-6">
      <article
        aria-label="Treść protokołu"
        className="space-y-1.5 rounded-lg border border-border bg-card p-5 text-sm leading-relaxed"
      >
        {visibleBlocks(protocol.document).map((block, index) =>
          block.type === "table" ? (
            <div key={index} className="overflow-x-auto py-2">
              <table className="w-full min-w-[520px] border-collapse text-xs">
                <tbody>
                  {(block.rows ?? []).map((row, rowIndex) => (
                    <tr key={rowIndex} className={rowIndex === 0 ? "font-semibold" : undefined}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="border border-border px-2 py-1 align-top">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p key={index}>{block.text}</p>
          ),
        )}
      </article>
      <div className="space-y-1">
        <Button type="button" variant="outline" size="sm" onClick={openPdf}>
          <FileDown className="h-4 w-4" aria-hidden />
          Otwórz PDF
        </Button>
        {pdfError ? <p className="text-xs text-muted-foreground">{pdfError}</p> : null}
      </div>
      <form onSubmit={submit} className="space-y-4 rounded-lg border border-border bg-card p-5">
        <label className="block space-y-1.5 text-sm">
          <span className="font-medium">Imię i nazwisko</span>
          <Input
            value={name}
            autoComplete="name"
            onChange={(event) => setName(event.target.value)}
            required
            minLength={3}
            maxLength={200}
          />
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={accepted}
            onChange={(event) => setAccepted(event.target.checked)}
          />
          <span>
            Potwierdzam odbiór sprzętu wymienionego w protokole i znam jego treść.
          </span>
        </label>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!accepted || name.trim().length < 3 || sending}>
            {sending ? "Zapisywanie…" : "Potwierdzam odbiór"}
          </Button>
          <span className="text-xs text-muted-foreground">Link ważny do {expires}, działa jeden raz.</span>
        </div>
      </form>
    </div>
  );
}
