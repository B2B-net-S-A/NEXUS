"use client";

// Ustawienia → Integracje → „Wtyczka LinkedIn” (makieta 6, 28.10.2026).
// Prezentacyjny: dane i odłączanie przychodzą z propsów
// (`app/settings/linkedin-extension/page.tsx`).

import { Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type { ExtensionConnectionDto } from "@/lib/api";

export type LinkedinExtensionLoad =
  | { status: "loading" }
  | { status: "error"; forbidden: boolean; message: string; onRetry: () => void }
  | { status: "success"; items: ExtensionConnectionDto[]; readsLimit: number };

export interface LinkedinExtensionSettingsViewProps {
  load: LinkedinExtensionLoad;
  onRevoke: (keyId: string) => Promise<void>;
  revokingKeyId: string | null;
  revokeError: string | null;
  now?: Date;
}

const MINUTE = 60_000;

/** „2 min temu”, „1 godz. temu”, „wczoraj”, dalej data — jak w makiecie. */
export function lastUsedLabel(iso: string | null, now: Date): string {
  if (!iso) return "jeszcze nie używana";
  const at = new Date(iso);
  const diff = now.getTime() - at.getTime();
  if (diff < MINUTE) return "przed chwilą";
  if (diff < 60 * MINUTE) return `${Math.floor(diff / MINUTE)} min temu`;
  const sameDay = at.toDateString() === now.toDateString();
  if (sameDay) return `${Math.floor(diff / (60 * MINUTE))} godz. temu`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (at.toDateString() === yesterday.toDateString()) return "wczoraj";
  return at.toLocaleDateString("pl-PL");
}

/** Odmiana „profil / profile / profili” i „dodany / dodane / dodanych”. */
export function usageLabel(reads: number, adds: number): string {
  if (reads === 0 && adds === 0) return "—";
  const pl = (n: number, one: string, few: string, many: string) => {
    if (n === 1) return one;
    const tens = n % 100;
    const units = n % 10;
    return units >= 2 && units <= 4 && (tens < 12 || tens > 14) ? few : many;
  };
  return `${reads} ${pl(reads, "odczyt", "odczyty", "odczytów")} · ${adds} ${pl(adds, "dodany", "dodane", "dodanych")}`;
}

export function LinkedinExtensionSettingsView({
  load,
  onRevoke,
  revokingKeyId,
  revokeError,
  now = new Date(),
}: LinkedinExtensionSettingsViewProps) {
  const { askConfirm, confirmDialog } = useConfirmV2();

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Wtyczka LinkedIn</h1>
        <p className="text-sm text-muted-foreground">
          Panel NEXUSA na LinkedInie i w LinkedIn Recruiterze. Każda osoba łączy
          wtyczkę swoim kontem i widzi w niej to samo co w NEXUSIE.
        </p>
      </header>

      {load.status === "loading" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Wczytuję połączenia…
        </p>
      ) : null}

      {load.status === "error" ? (
        <QueryStateNotice
          state={load.forbidden ? "forbidden" : "error"}
          description={load.message}
          onRetry={load.forbidden ? undefined : load.onRetry}
        />
      ) : null}

      {load.status === "success" ? (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          {revokeError ? (
            <p className="border-b border-border bg-destructive-muted px-4 py-2 text-sm text-destructive-muted-foreground" role="alert">
              {revokeError}
            </p>
          ) : null}
          {load.items.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground">
              Nikt jeszcze nie połączył wtyczki. Osoba instaluje ją z linku do
              Chrome Web Store i klika w panelu „Zaloguj przez NEXUS”.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-semibold">Osoba</th>
                    <th className="px-4 py-2 font-semibold">Ostatnio</th>
                    <th className="px-4 py-2 font-semibold">Dziś</th>
                    <th className="px-4 py-2 font-semibold">Wersja</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {load.items.map((item) => (
                    <tr key={item.key_id} className="border-t border-border">
                      <td className="px-4 py-2 font-medium text-foreground">{item.user_name}</td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {lastUsedLabel(item.last_used_at, now)}
                      </td>
                      <td className="px-4 py-2 tabular-nums text-muted-foreground">
                        {usageLabel(item.reads_today, item.adds_today)}
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">{item.extension_version ?? "—"}</td>
                      <td className="px-4 py-2 text-right">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          loading={revokingKeyId === item.key_id}
                          onClick={async () => {
                            const ok = await askConfirm({
                              title: `Odłączyć wtyczkę: ${item.user_name}?`,
                              description:
                                "Panel na LinkedInie przestanie działać od razu. Osoba może połączyć wtyczkę ponownie swoim kontem.",
                              confirmLabel: "Odłącz",
                              variant: "destructive",
                            });
                            if (ok) await onRevoke(item.key_id);
                          }}
                        >
                          Odłącz
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
            Dzienny limit odczytów stron LinkedIna na osobę: {load.readsLimit}. Powyżej
            panel prosi o przerwę do jutra.
          </p>
        </div>
      ) : null}
      {confirmDialog}
    </section>
  );
}
