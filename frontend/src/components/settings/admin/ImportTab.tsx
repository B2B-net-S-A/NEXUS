"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Database } from "lucide-react";
import { adminApi, type ImportTaskStatus } from "@/lib/api";

export function ImportTab() {
  const [dryRun, setDryRun] = useState(true);
  const [copyEmb, setCopyEmb] = useState(true);
  const [batchSize, setBatchSize] = useState(500);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const startMutation = useMutation({
    mutationFn: (data: { dry_run: boolean; batch_size: number; copy_embeddings: boolean }) =>
      adminApi.startTalentRadarImport(data).then((r) => r.data),
    onSuccess: (task) => {
      setActiveTaskId(task.task_id);
      queryClient.invalidateQueries({ queryKey: ["import-tasks"] });
    },
  });

  const { data: task } = useQuery({
    queryKey: ["import-task", activeTaskId],
    queryFn: (): Promise<ImportTaskStatus | null> =>
      activeTaskId
        ? adminApi.getTalentRadarImportStatus(activeTaskId).then((r) => r.data)
        : Promise.resolve(null),
    enabled: !!activeTaskId,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && (data.status === "running" || data.status === "queued") ? 2000 : false;
    },
  });

  const { data: tasks } = useQuery({
    queryKey: ["import-tasks"],
    queryFn: (): Promise<ImportTaskStatus[]> =>
      adminApi.listImportTasks().then((r) => r.data),
    refetchInterval: 5000,
  });

  const candidates = task?.progress?.candidates;
  const embeddings = task?.progress?.embeddings;

  const Bar = ({ done, total, label }: { done: number; total: number; label: string }) => {
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    return (
      <div>
        <div className="flex justify-between text-xs text-muted-foreground mb-1">
          <span>{label}</span>
          <span>
            {done.toLocaleString()} / {total.toLocaleString()} ({pct}%)
          </span>
        </div>
        <div className="w-full h-2 bg-muted dark:bg-muted rounded-full overflow-hidden">
          <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-5">
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-3">
          <Database className="w-5 h-5 text-violet-500" />
          Import z talent-radar (Supabase)
        </h2>
        <p className="text-sm text-muted-foreground mb-4">
          Ściąga kandydatów z projektu <code>talentradar-prod</code>. Pole <code>TALENT_RADAR_DSN</code>{" "}
          musi być ustawione w Coolify env. Embedding copy oszczędza koszt Voyage (~70k requestów).
        </p>

        <div className="grid grid-cols-3 gap-4 mb-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="w-4 h-4 accent-blue-600"
            />
            <span className="text-sm">Dry-run (read only, nic nie zapisuje)</span>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={copyEmb}
              onChange={(e) => setCopyEmb(e.target.checked)}
              className="w-4 h-4 accent-blue-600"
            />
            <span className="text-sm">Kopiuj embeddings pgvector → Qdrant</span>
          </label>
          <label className="flex items-center gap-2 text-sm">
            Batch:
            <input
              type="number"
              value={batchSize}
              onChange={(e) => setBatchSize(Number(e.target.value) || 500)}
              className="w-24 px-2 py-1 rounded border border-border dark:border-border bg-card dark:bg-card"
              min={50}
              max={2000}
            />
          </label>
        </div>

        <button
          onClick={() =>
            startMutation.mutate({
              dry_run: dryRun,
              batch_size: batchSize,
              copy_embeddings: copyEmb,
            })
          }
          disabled={startMutation.isPending}
          className="px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium disabled:opacity-50"
        >
          {startMutation.isPending ? "Uruchamianie..." : "Rozpocznij import"}
        </button>

        {startMutation.isError && (
          <div className="mt-3 text-xs text-destructive bg-destructive/10 rounded p-2">
            {(startMutation.error as { response?: { data?: { detail?: string } } })?.response?.data
              ?.detail ?? "Błąd"}
          </div>
        )}

        {task && (
          <div className="mt-5 space-y-4 pt-4 border-t border-border dark:border-border">
            <div className="flex justify-between items-center">
              <span className="text-sm">
                Zadanie <code className="text-xs">{task.task_id}</code> — status:{" "}
                <strong
                  className={
                    task.status === "done"
                      ? "text-emerald-600"
                      : task.status === "error"
                      ? "text-destructive"
                      : "text-primary"
                  }
                >
                  {task.status}
                </strong>
              </span>
              {task.finished_at && (
                <span className="text-xs text-muted-foreground">
                  {new Date(task.finished_at).toLocaleString("pl-PL")}
                </span>
              )}
            </div>

            {candidates && (
              <div className="space-y-2">
                <Bar
                  done={candidates.processed}
                  total={candidates.total}
                  label="Kandydaci"
                />
                <div className="grid grid-cols-4 gap-2 text-xs text-muted-foreground">
                  <span>Inserted: {candidates.inserted.toLocaleString()}</span>
                  <span>Updated: {candidates.updated.toLocaleString()}</span>
                  <span>Skipped: {candidates.skipped.toLocaleString()}</span>
                  <span className={candidates.errors ? "text-destructive" : ""}>
                    Errors: {candidates.errors.toLocaleString()}
                  </span>
                </div>
              </div>
            )}

            {embeddings && (
              <div className="space-y-2">
                <Bar
                  done={embeddings.processed}
                  total={embeddings.total}
                  label="Embeddings (pgvector → Qdrant)"
                />
                <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                  <span>Copied: {embeddings.copied.toLocaleString()}</span>
                  <span>Missing in source: {embeddings.missing_source.toLocaleString()}</span>
                  <span className={embeddings.errors ? "text-destructive" : ""}>
                    Errors: {embeddings.errors.toLocaleString()}
                  </span>
                </div>
              </div>
            )}

            {task.error && (
              <pre className="text-xs text-destructive bg-destructive/10 dark:bg-destructive/15 rounded p-2 whitespace-pre-wrap">
                {task.error}
              </pre>
            )}

            {candidates?.error_samples && candidates.error_samples.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">
                  Przykładowe błędy ({candidates.error_samples.length})
                </summary>
                <pre className="mt-2 p-2 bg-muted dark:bg-card rounded whitespace-pre-wrap">
                  {candidates.error_samples.join("\n")}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>

      {tasks && tasks.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-4">
          <h3 className="font-medium mb-2">Historia importów (sesja pamięci)</h3>
          <ul className="space-y-1 text-sm">
            {tasks.map((t) => (
              <li
                key={t.task_id}
                className="flex items-center gap-3 py-1 cursor-pointer hover:bg-muted dark:hover:bg-card px-2 rounded"
                onClick={() => setActiveTaskId(t.task_id)}
              >
                <code className="text-xs text-muted-foreground">{t.task_id}</code>
                <span
                  className={
                    t.status === "done"
                      ? "text-emerald-600"
                      : t.status === "error"
                      ? "text-destructive"
                      : "text-primary"
                  }
                >
                  {t.status}
                </span>
                <span className="text-xs text-muted-foreground ml-auto">
                  {new Date(t.started_at).toLocaleString("pl-PL")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default ImportTab;
