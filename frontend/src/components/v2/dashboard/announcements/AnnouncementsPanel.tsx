"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, MoreHorizontal, Pin, Plus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  invalidateAnnouncements,
  markAnnouncementRead,
  useAnnouncements,
  withdrawAnnouncement,
  type Announcement,
} from "@/lib/api/announcements";
import { ANNOUNCEMENTS_VISIBLE, audienceLabel, publishedLabel, shortDay } from "@/lib/announcements";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import { cn } from "@/lib/utils";

import { AnnouncementDialog } from "./AnnouncementDialog";

interface RowProps {
  item: Announcement;
  canPublish: boolean;
  busy: boolean;
  onRead: (item: Announcement) => void;
  onEdit: (item: Announcement) => void;
  onWithdraw: (item: Announcement) => void;
}

function AnnouncementRow({ item, canPublish, busy, onRead, onEdit, onWithdraw }: RowProps) {
  const [expanded, setExpanded] = useState(false);
  const long = item.body.length > 220 || item.body.split("\n").length > 3;
  const author = item.author_name ? (shortenPersonName(item.author_name) ?? item.author_name) : null;
  const meta = [author, publishedLabel(item.created_at), `do ${shortDay(item.visible_until)}`];
  if (canPublish) meta.push(`do: ${audienceLabel(item.audience_roles)}`);
  if (item.read) meta.push("przeczytane");
  return (
    <li
      className={cn(
        "grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3 border-t border-border pt-2.5 first:border-t-0 first:pt-0",
        item.read && "text-muted-foreground",
      )}
      data-testid="announcement-row"
      data-read={item.read ? "true" : "false"}
    >
      <span
        aria-hidden="true"
        className={cn("mt-1.5 h-2 w-2 rounded-full", item.read ? "bg-border" : "bg-primary")}
      />
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-1.5 text-sm">
          {item.pinned ? <Pin className="h-3.5 w-3.5 shrink-0" aria-label="Przypięte" /> : null}
          <span className={cn("break-words", item.read ? "font-medium" : "font-semibold text-foreground")}>
            {item.title}
          </span>
          {item.important ? (
            <Badge variant={item.read ? "neutral" : "soft"} size="sm">
              Ważne
            </Badge>
          ) : null}
        </p>
        <p
          className={cn(
            "mt-0.5 whitespace-pre-line break-words text-sm",
            item.read ? "text-muted-foreground" : "text-foreground",
            long && !expanded && "line-clamp-3",
          )}
        >
          {item.body}
        </p>
        {long ? (
          <button
            type="button"
            className="text-xs font-medium text-primary underline-offset-2 hover:underline"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Zwiń" : "Pokaż całość"}
          </button>
        ) : null}
        <p className="mt-0.5 text-xs text-muted-foreground">{meta.filter(Boolean).join(" · ")}</p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {canPublish && item.recipient_count !== null ? (
          <span className="hidden text-xs text-muted-foreground sm:inline" data-testid="announcement-read-count">
            przeczytało {item.read_count ?? 0} z {item.recipient_count}
          </span>
        ) : null}
        {item.for_me && !item.read ? (
          <Button size="sm" variant="outline" className="bg-card" disabled={busy} onClick={() => onRead(item)}>
            Przeczytane
          </Button>
        ) : item.read ? (
          <Check className="h-4 w-4" aria-label="Przeczytane" />
        ) : null}
        {canPublish ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="ghost" aria-label={`Więcej: ${item.title}`}>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onEdit(item)}>Popraw</DropdownMenuItem>
              <DropdownMenuItem className="text-destructive" onSelect={() => onWithdraw(item)}>
                Zdejmij przed terminem
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
    </li>
  );
}

/** „Nowe ogłoszenie” w nagłówku pulpitu — tylko Head of Recruitment i administrator. */
export function AnnouncementPublishButton() {
  const query = useAnnouncements();
  const [open, setOpen] = useState(false);
  if (!query.isSuccess || !query.data.can_publish) return null;
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} data-testid="announcement-new">
        <Plus className="h-4 w-4" aria-hidden />
        Ogłoszenie
      </Button>
      <AnnouncementDialog open={open} onOpenChange={setOpen} roles={query.data.audience_roles} />
    </>
  );
}

/**
 * Panel „Ogłoszenia” (decyzja Artura 28.10.2026) — na górze pulpitu każdej
 * osoby, nad kafelkami i niezależnie od własnego układu, wzorem panelu P0.
 * Znika, gdy nie ma aktywnych ogłoszeń; błąd zapytania też go chowa (panel
 * nie zastępuje dzwonka, a „ważne” przychodzą i tak mailem).
 *
 * Kolejność daje serwer: nieprzeczytane nad przeczytanymi, w grupie przypięte
 * i najnowsze. Przeczytane szarzeje i zostaje do końca dnia „widoczne do”.
 */
export function AnnouncementsPanel({ className }: { className?: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useAnnouncements();
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [edited, setEdited] = useState<Announcement | null>(null);
  const items = query.data?.items ?? [];
  if (!query.isSuccess || items.length === 0) return confirmDialog;
  const canPublish = query.data.can_publish;
  const unread = items.filter((item) => item.for_me && !item.read).length;
  const shown = expanded ? items : items.slice(0, ANNOUNCEMENTS_VISIBLE);
  const hidden = items.length - shown.length;

  const read = async (item: Announcement) => {
    setBusy(item.id);
    try {
      await markAnnouncementRead(item.id);
      invalidateAnnouncements(queryClient);
    } catch (err) {
      toast.showError(apiErrorMessage(err, "Nie udało się oznaczyć ogłoszenia jako przeczytane."));
    } finally {
      setBusy(null);
    }
  };
  const withdraw = async (item: Announcement) => {
    const ok = await askConfirm({
      title: "Zdjąć ogłoszenie?",
      description: `„${item.title}” zniknie z pulpitu wszystkich odbiorców przed terminem.`,
      confirmLabel: "Zdejmij",
      variant: "destructive",
    });
    if (!ok) return;
    setBusy(item.id);
    try {
      await withdrawAnnouncement(item.id);
      invalidateAnnouncements(queryClient);
      toast.showSuccess("Ogłoszenie zdjęte.");
    } catch (err) {
      toast.showError(apiErrorMessage(err, "Nie udało się zdjąć ogłoszenia."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      aria-label="Ogłoszenia"
      className={cn("grid gap-2.5 rounded-xl border border-primary/30 bg-card p-3", className)}
      data-testid="announcements-panel"
      data-tour="dashboard.announcements"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-base font-bold">
          Ogłoszenia · {items.length}
          {unread > 0 && unread < items.length ? (
            <span className="font-normal text-muted-foreground"> · nieprzeczytane {unread}</span>
          ) : null}
        </h2>
        <p className="text-xs text-muted-foreground sm:ml-auto">
          {canPublish ? "Widzisz wszystkie aktywne · odbiorcy widzą swoje" : "Publikuje Head of Recruitment i administrator"}
        </p>
      </div>
      <ul className="grid gap-2.5">
        {shown.map((item) => (
          <AnnouncementRow
            key={item.id}
            item={item}
            canPublish={canPublish}
            busy={busy === item.id}
            onRead={(next) => void read(next)}
            onEdit={setEdited}
            onWithdraw={(next) => void withdraw(next)}
          />
        ))}
      </ul>
      {items.length > ANNOUNCEMENTS_VISIBLE ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="w-fit text-xs font-medium text-primary underline-offset-2 hover:underline"
          data-testid="announcements-toggle"
        >
          {expanded ? "Pokaż mniej" : `Pokaż wszystkie · jeszcze ${hidden}`}
        </button>
      ) : null}
      {canPublish ? (
        <AnnouncementDialog
          key={edited?.id ?? "none"}
          open={edited !== null}
          onOpenChange={(open) => {
            if (!open) setEdited(null);
          }}
          edited={edited}
          roles={query.data.audience_roles}
        />
      ) : null}
      {confirmDialog}
    </section>
  );
}
