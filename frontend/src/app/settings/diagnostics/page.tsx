"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, PlayCircle, RefreshCw } from "lucide-react";
import { phase5Api } from "@/lib/api";

interface DiagReport {
  voyage: {
    key_present: boolean;
    ping_ok?: boolean;
    dim?: number;
    reason?: string;
  };
  qdrant: {
    host: string | null;
    port: number | null;
    ok?: boolean;
    reason?: string;
    all_collections?: string[];
    counts?: Record<string, number | string | null>;
  };
  collections: {
    candidates: string;
    jobs: string;
  };
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${
        ok
          ? "bg-green-100 text-green-700 border-green-300"
          : "bg-destructive/15 text-destructive border-red-300"
      }`}
    >
      {ok ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
      {label}
    </span>
  );
}

export default function DiagnosticsPage() {
  const [report, setReport] = useState<DiagReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [initBusy, setInitBusy] = useState(false);
  const [initMsg, setInitMsg] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await phase5Api.diagnostics();
      setReport(r.data as DiagReport);
    } catch (e) {
      console.error("diagnostics failed:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleInit = async () => {
    setInitBusy(true);
    setInitMsg(null);
    try {
      await phase5Api.initCollections();
      setInitMsg("Kolekcje utworzone / zweryfikowane.");
      await load();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      setInitMsg(`Błąd: ${msg}`);
    } finally {
      setInitBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-muted dark:bg-card">
      <div className="max-w-4xl mx-auto px-4 py-8 space-y-5">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Diagnostyka embeddingu</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Voyage AI + Qdrant — stan połączeń i kolekcji.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="flex items-center gap-1 text-sm px-3 py-1.5 rounded-md border border-border dark:border-border hover:bg-muted dark:hover:bg-muted"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Odśwież
            </button>
            <button
              onClick={handleInit}
              disabled={initBusy}
              className="flex items-center gap-1 text-sm px-3 py-1.5 rounded-md bg-slate-700 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              <PlayCircle className="w-3.5 h-3.5" />
              {initBusy ? "Inicjalizuję…" : "Utwórz kolekcje"}
            </button>
          </div>
        </header>

        {initMsg && (
          <div className="rounded bg-primary/10 dark:bg-primary/10 border border-primary/20 dark:border-primary/90 px-3 py-2 text-sm">
            {initMsg}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
        ) : !report ? (
          <p className="text-sm text-muted-foreground">Brak danych.</p>
        ) : (
          <>
            <section className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4 space-y-2">
              <h2 className="font-medium mb-2">Voyage AI</h2>
              <div className="flex gap-2 flex-wrap items-center">
                <StatusPill
                  ok={report.voyage.key_present}
                  label={`API key: ${report.voyage.key_present ? "ustawiony" : "BRAK"}`}
                />
                <StatusPill
                  ok={!!report.voyage.ping_ok}
                  label={`Ping: ${report.voyage.ping_ok ? "OK" : "FAIL"}`}
                />
                {report.voyage.dim !== undefined && (
                  <span className="text-xs text-muted-foreground">
                    dim = {report.voyage.dim}
                  </span>
                )}
              </div>
              {report.voyage.reason && (
                <pre className="text-xs text-destructive bg-destructive/10 dark:bg-destructive/15 rounded p-2 whitespace-pre-wrap">
                  {report.voyage.reason}
                </pre>
              )}
            </section>

            <section className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4 space-y-2">
              <h2 className="font-medium mb-2">Qdrant</h2>
              <div className="flex gap-2 flex-wrap items-center">
                <StatusPill
                  ok={!!report.qdrant.ok}
                  label={`Połączenie: ${report.qdrant.ok ? "OK" : "FAIL"}`}
                />
                <span className="text-xs text-muted-foreground">
                  {report.qdrant.host}:{report.qdrant.port}
                </span>
              </div>
              {report.qdrant.reason && (
                <pre className="text-xs text-destructive bg-destructive/10 dark:bg-destructive/15 rounded p-2 whitespace-pre-wrap">
                  {report.qdrant.reason}
                </pre>
              )}

              {report.qdrant.counts && (
                <table className="w-full text-sm mt-3">
                  <thead className="text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="text-left py-1">Kolekcja</th>
                      <th className="text-right">Liczba punktów</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.qdrant.counts).map(([name, count]) => (
                      <tr key={name} className="border-t border-border dark:border-border">
                        <td className="py-1">
                          <code className="text-xs bg-muted dark:bg-card px-1.5 py-0.5 rounded">
                            {name}
                          </code>
                        </td>
                        <td className="text-right">
                          {count === "MISSING" ? (
                            <span className="text-destructive font-medium">BRAK</span>
                          ) : (
                            <span>{count}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {report.qdrant.all_collections && (
                <p className="text-xs text-muted-foreground mt-2">
                  Wszystkie kolekcje: {report.qdrant.all_collections.join(", ") || "—"}
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
