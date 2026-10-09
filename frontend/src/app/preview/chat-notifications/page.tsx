"use client";

/**
 * Harness wizualny okienka „Czaty” z górnego paska — publiczny, ZERO zapytań.
 *
 * Renderuje prezentacyjne części (`ChatTopbarButton`, `ChatThreadsPanel`) na
 * danych fikcyjnych. Stany obok siebie, żeby awaria nie dała się pomylić
 * z brakiem rozmów.
 */

import {
  ChatThreadsPanel,
  ChatTopbarButton,
  type ChatThreadsPanelProps,
} from "@/components/v2/shell/ChatNotificationsDropdown";
import type { ChatThread } from "@/lib/api/chatNotifications";

const NOW = Date.now();

function ago(minutes: number): string {
  return new Date(NOW - minutes * 60_000).toISOString();
}

const THREADS: ChatThread[] = [
  {
    kind: "job",
    entity_id: 11,
    title: "Tester automatyzujący · Selenium, Java",
    subtitle: "Bank Przykładowy",
    unread_count: 4,
    has_mention: true,
    last_author_name: "Anna Przykładowa",
    last_message: "Klient prosi o drugą osobę na czwartek — zerkniesz, kogo mamy?",
    last_at: ago(3),
    link: "/jobs/11?tab=chat&msg=101",
  },
  {
    kind: "candidate",
    entity_id: 21,
    title: "Bartek Testowy",
    subtitle: null,
    unread_count: 1,
    has_mention: false,
    last_author_name: "Celina Fikcyjna",
    last_message: "Oddzwonił. Pasuje mu środa po 15:00.",
    last_at: ago(42),
    link: "/candidates/21?tab=chat&msg=202",
  },
  {
    kind: "job",
    entity_id: 12,
    title: "Analityk danych z bardzo długą nazwą stanowiska, która nie mieści się w jednej linii",
    subtitle: "Klient Alfa Spółka z ograniczoną odpowiedzialnością",
    unread_count: 120,
    has_mention: false,
    last_author_name: "Dawid Wzorcowy",
    last_message:
      "Podsumowanie po rozmowie: kandydat zna SQL i Pythona, pyta o tryb pracy i o to, czy projekt ma szansę na przedłużenie po pół roku.",
    last_at: ago(60 * 5),
    link: "/jobs/12?tab=chat&msg=303",
  },
  {
    kind: "job",
    entity_id: 13,
    title: "DevOps Engineer",
    subtitle: "Klient Beta",
    unread_count: 0,
    has_mention: false,
    last_author_name: "Ewa Bezkategorii",
    last_message: "Dzięki, zamykam temat.",
    last_at: ago(60 * 24 * 3),
    link: "/jobs/13?tab=chat&msg=404",
  },
];

const noop = () => undefined;

const BASE: ChatThreadsPanelProps = {
  state: "ready",
  threads: THREADS,
  unreadThreads: 3,
  onOpenThread: noop,
  onMarkAllRead: noop,
  onRetry: noop,
  onOpenSettings: noop,
};

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="w-full max-w-96 shrink-0">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className="overflow-hidden rounded-lg border border-border bg-card shadow-md">
        {children}
      </div>
    </section>
  );
}

export default function ChatNotificationsPreviewPage() {
  return (
    <main className="min-h-dvh bg-muted/30 p-4 sm:p-6">
      <h1 className="mb-1 text-lg font-semibold text-foreground">
        Okienko „Czaty” — harness
      </h1>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
        Powiadomienia czatów rekrutacji i kandydatów, jedna pozycja na rozmowę.
        Dane fikcyjne, bez zapytań do serwera.
      </p>

      <div className="mb-6 flex flex-wrap items-center gap-6 rounded-lg border border-border bg-background px-4 py-2">
        <span className="text-xs text-muted-foreground">Ikona w pasku:</span>
        <ChatTopbarButton unreadThreads={0} hasMention={false} open={false} />
        <ChatTopbarButton unreadThreads={3} hasMention={false} open={false} />
        <ChatTopbarButton unreadThreads={3} hasMention open={false} />
        <ChatTopbarButton unreadThreads={120} hasMention open />
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <Frame title="Rozmowy">
          <ChatThreadsPanel {...BASE} />
        </Frame>
        <Frame title="Wszystko przeczytane">
          <ChatThreadsPanel
            {...BASE}
            unreadThreads={0}
            threads={THREADS.map((t) => ({ ...t, unread_count: 0, has_mention: false }))}
          />
        </Frame>
        <Frame title="Brak rozmów">
          <ChatThreadsPanel {...BASE} threads={[]} unreadThreads={0} />
        </Frame>
        <Frame title="Ładowanie">
          <ChatThreadsPanel {...BASE} state="loading" threads={[]} unreadThreads={0} />
        </Frame>
        <Frame title="Błąd">
          <ChatThreadsPanel {...BASE} state="error" threads={[]} unreadThreads={0} />
        </Frame>
      </div>
    </main>
  );
}
