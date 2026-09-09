"use client";

import { useState } from "react";
import { Wand2, X, Copy, Check } from "lucide-react";
import { aiWriterApi } from "@/lib/api";

export function AIJobWriterModal({
  job,
  onClose,
  onUse,
}: {
  job: { title?: string; client?: { name?: string }; requirements?: string; seniority?: string | null };
  onClose: () => void;
  onUse: (desc: string) => Promise<void>;
}) {
  const [title, setTitle] = useState(job?.title || "");
  const [clientName, setClientName] = useState(job?.client?.name || "");
  const [seniority, setSeniority] = useState(() => ["junior", "mid", "senior", "lead"].includes(job?.seniority ?? "") ? job.seniority! : "");
  const [requirements, setRequirements] = useState(job?.requirements || "");
  const [generated, setGenerated] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);

  const handleGenerate = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await aiWriterApi.generateJobDescription({
        title,
        client_name: clientName || undefined,
        requirements: requirements || undefined,
        seniority: seniority || undefined,
      });
      setGenerated(data.description);
    } catch {
      setError("Nie udało się przygotować szkicu. Spróbuj ponownie.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleApply = async () => {
    if (!generated || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onUse(generated);
      onClose();
    } catch {
      setError("Nie udało się zapisać opisu. Szkic pozostaje dostępny — spróbuj ponownie.");
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async () => {
    if (!generated) return;
    await navigator.clipboard.writeText(generated);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div role="dialog" aria-modal="true" aria-label="Szkic ogłoszenia" className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-card rounded-2xl shadow-xl w-full max-w-2xl my-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border">
          <div className="flex items-center gap-2">
            <Wand2 className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground">Szkic ogłoszenia</h2>
          </div>
          <button onClick={onClose} disabled={saving} aria-label="Zamknij szkic" className="text-muted-foreground hover:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-sm text-muted-foreground">Szablon na podstawie podanych danych. Sprawdź i popraw szkic przed zapisaniem go jako opisu rekrutacji.</p>
          {/* Form */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground mb-1">Tytuł stanowiska</label>
              <input
                aria-label="Tytuł stanowiska"
                disabled={isLoading || saving}
                value={title}
                onChange={(e) => { setTitle(e.target.value); setGenerated(null); }}
                placeholder="np. Angular Developer"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-muted-foreground mb-1">Klient</label>
              <input
                aria-label="Klient"
                disabled={isLoading || saving}
                value={clientName}
                onChange={(e) => { setClientName(e.target.value); setGenerated(null); }}
                placeholder="np. Nordea"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">Poziom seniority</label>
            <div className="flex gap-2">
              {["", "junior", "mid", "senior", "lead"].map((s) => (
                <button
                  key={s}
                  aria-pressed={seniority === s}
                  disabled={isLoading || saving}
                  onClick={() => { setSeniority(s); setGenerated(null); }}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors capitalize ${
                    seniority === s
                      ? "bg-primary text-white"
                      : "border border-border text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {s ? s.charAt(0).toUpperCase() + s.slice(1) : "Nie podano"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">
              Wymagania / kluczowe umiejętności
            </label>
            <textarea
              aria-label="Wymagania / kluczowe umiejętności"
              disabled={isLoading || saving}
              value={requirements}
              onChange={(e) => { setRequirements(e.target.value); setGenerated(null); }}
              rows={4}
              placeholder="Angular 14+&#10;RxJS&#10;TypeScript&#10;Agile/Scrum&#10;Komunikatywny angielski"
              className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-none focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            />
            <p className="text-xs text-muted-foreground mt-0.5">Wpisz wymagania po jednym w linii</p>
          </div>

          {error && (
            <div role="alert" className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            onClick={handleGenerate}
            disabled={!title.trim() || isLoading || saving}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-primary text-white font-medium rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {isLoading ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Generuję...
              </>
            ) : (
              <>
                <Wand2 className="w-4 h-4" />
                Przygotuj szkic
              </>
            )}
          </button>

          {/* Generated output */}
          {generated !== null && (
            <div className="border border-border rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-muted border-b border-border dark:border-border">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Szkic do sprawdzenia
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs border border-border rounded-lg hover:bg-card text-muted-foreground transition-colors"
                  >
                    {copied ? (
                      <><Check className="w-3.5 h-3.5 text-emerald-500" /> Skopiowano</>
                    ) : (
                      <><Copy className="w-3.5 h-3.5" /> Kopiuj</>
                    )}
                  </button>
                  <button
                    onClick={handleApply}
                    disabled={saving || !generated.trim()}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                  >
                    {saving ? "Zapisuję…" : "Zapisz sprawdzony opis"}
                  </button>
                </div>
              </div>
              <div className="p-4 max-h-72 overflow-y-auto">
                <textarea aria-label="Szkic do sprawdzenia" value={generated} disabled={saving}
                  onChange={e => setGenerated(e.target.value)} rows={8}
                  className="w-full text-sm text-foreground leading-relaxed" />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

