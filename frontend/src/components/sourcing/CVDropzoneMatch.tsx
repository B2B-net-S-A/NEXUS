"use client";

import { useRef, useState, type DragEvent } from "react";
import { FileUp, Loader2, Sparkles, X } from "lucide-react";
import {
  recommendationsApi,
  type CvUploadPreviewResponse,
  type JobMatch,
} from "@/lib/api";
import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";

const ACCEPTED_EXT = [".pdf", ".docx", ".doc", ".txt"];

export function CVDropzoneMatch() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CvUploadPreviewResponse | null>(null);
  const [filename, setFilename] = useState<string | null>(null);

  const handleFile = async (file: File) => {
    setError(null);
    setResult(null);

    const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
    if (!ACCEPTED_EXT.includes(ext)) {
      setError(
        `Nieobsługiwany format: ${ext}. Akceptowane: ${ACCEPTED_EXT.join(", ")}`,
      );
      return;
    }

    setFilename(file.name);
    setLoading(true);
    try {
      const res = await recommendationsApi.cvUploadPreview(file, {
        top_k: 10,
        threshold: 30,
      });
      setResult(res.data);
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail ?? "Błąd serwera")
          : "Nie udało się przetworzyć CV";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      void handleFile(file);
    }
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(true);
  };

  const onDragLeave = () => setDragActive(false);

  const reset = () => {
    setResult(null);
    setError(null);
    setFilename(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  // Map preview matches → JobMatch shape expected by SuggestedJobsWidget.
  const widgetMatches: JobMatch[] | undefined = result
    ? result.matches.map((m) => ({
        job: m.job,
        total_score: m.total_score,
        breakdown: m.breakdown,
      }))
    : undefined;

  return (
    <section
      className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 mb-4"
      data-testid="cv-dropzone-match"
    >
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="w-4 h-4 text-purple-500" />
        <h3 className="font-semibold text-sm text-gray-900 dark:text-gray-100">
          Wrzuć CV — AI dopasuje otwarte projekty
        </h3>
        {result && (
          <button
            onClick={reset}
            className="ml-auto text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
          >
            <X className="w-3 h-3" /> Wyczyść
          </button>
        )}
      </div>

      {!result && (
        <div
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            dragActive
              ? "border-purple-500 bg-purple-50 dark:bg-purple-900/20"
              : "border-gray-300 dark:border-gray-600 hover:border-purple-400 hover:bg-purple-50/50 dark:hover:bg-purple-900/10"
          }`}
          data-testid="cv-dropzone-area"
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXT.join(",")}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
          {loading ? (
            <div className="flex items-center justify-center gap-2 text-gray-600">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span>Parsuję CV{filename ? ` „${filename}"` : ""}…</span>
            </div>
          ) : (
            <>
              <FileUp className="w-10 h-10 mx-auto text-gray-400 mb-2" />
              <p className="text-sm text-gray-700 dark:text-gray-300 font-medium">
                Przeciągnij CV tutaj lub kliknij, aby wybrać plik
              </p>
              <p className="text-xs text-gray-500 mt-1">
                PDF / DOCX / TXT, max 10 MB. Kandydat NIE jest tworzony w bazie.
              </p>
            </>
          )}
        </div>
      )}

      {error && (
        <div className="mt-3 rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-4">
          <CvSummaryCard summary={result.parsed_summary} filename={filename} />
          {widgetMatches && widgetMatches.length > 0 ? (
            <SuggestedJobsWidget candidateId={0} matches={widgetMatches} maxItems={10} />
          ) : (
            <div className="rounded bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
              Nie znalazłem ofert powyżej progu jakości dla tego CV. Spróbuj
              edytować profil ręcznie lub poluzuj próg.
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function CvSummaryCard({
  summary,
  filename,
}: {
  summary: CvUploadPreviewResponse["parsed_summary"];
  filename: string | null;
}) {
  const fullName = [summary.first_name, summary.last_name]
    .filter(Boolean)
    .join(" ");
  const skillNames = summary.skills
    .map((s) => s.name)
    .filter(Boolean)
    .slice(0, 8);

  return (
    <div className="rounded-lg border border-purple-200 dark:border-purple-800/50 bg-purple-50/50 dark:bg-purple-900/10 p-3">
      <div className="text-xs uppercase tracking-wide text-purple-700 dark:text-purple-300 font-bold mb-2">
        Sparsowane CV{filename ? ` · ${filename}` : ""}
      </div>
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {fullName && (
          <Field label="Imię i nazwisko" value={fullName} />
        )}
        {summary.current_position && (
          <Field label="Stanowisko" value={summary.current_position} />
        )}
        {summary.email && <Field label="Email" value={summary.email} />}
        {summary.city && <Field label="Miasto" value={summary.city} />}
        {summary.years_it_experience !== null && (
          <Field
            label="Doświadczenie"
            value={`${summary.years_it_experience} lat`}
          />
        )}
        {skillNames.length > 0 && (
          <div className="md:col-span-2">
            <dt className="text-xs text-gray-500">Technologie</dt>
            <dd className="flex flex-wrap gap-1 mt-1">
              {skillNames.map((s) => (
                <span
                  key={s}
                  className="text-xs bg-white dark:bg-gray-800 border border-gray-300 px-1.5 py-0.5 rounded"
                >
                  {s}
                </span>
              ))}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | undefined }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className="text-sm text-gray-900 dark:text-gray-100">{value}</dd>
    </div>
  );
}
