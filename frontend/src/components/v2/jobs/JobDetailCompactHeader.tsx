"use client";

import type { ReactNode } from "react";
import {
  ChevronDown,
  ChevronUp,
  Ellipsis,
  History,
  Link2,
  MessageCircle,
  PencilLine,
  Search,
  Sparkles,
  UserCheck,
  UserPlus,
  Wand2,
} from "lucide-react";

import { EntityHeader } from "@/components/ds/EntityHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export type JobDetailTab =
  | "pipeline"
  | "history"
  | "ai-matching"
  | "manual-search"
  | "portals"
  | "champion"
  | "questions"
  | "chat";

const SOURCING_TABS = new Set<JobDetailTab>([
  "ai-matching",
  "manual-search",
  "portals",
]);
const TOOL_TABS = new Set<JobDetailTab>(["champion", "questions", "chat"]);

interface JobDetailCompactHeaderProps {
  title: ReactNode;
  referenceNumber?: string | null;
  badges?: ReactNode;
  metadata?: ReactNode;
  presence?: ReactNode;
  activeTab: JobDetailTab;
  onTabChange: (tab: JobDetailTab) => void;
  onAddCandidate?: () => void;
  onEdit?: () => void;
  onWriteAnnouncement?: () => void;
  onGenerateInviteLink?: () => void;
  chatUnreadCount?: number;
  contextOpen: boolean;
  onContextOpenChange: (open: boolean) => void;
  contextContent: ReactNode;
}

function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

function WorkspaceButton({
  active,
  children,
  className,
  ...props
}: React.ComponentProps<typeof Button> & { active?: boolean }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={cn(
        "h-10 rounded-none border-b-2 px-3",
        active
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground",
        className,
      )}
      aria-current={active ? "page" : undefined}
      {...props}
    >
      {children}
    </Button>
  );
}

/**
 * Compact, two-row recruitment workspace header.
 *
 * The first row keeps identity and the primary action visible. The second row
 * groups the eight workspace sections into two direct destinations and two
 * menus, while the operational context stays available behind one disclosure.
 */
export function JobDetailCompactHeader({
  title,
  referenceNumber,
  badges,
  metadata,
  presence,
  activeTab,
  onTabChange,
  onAddCandidate,
  onEdit,
  onWriteAnnouncement,
  onGenerateInviteLink,
  chatUnreadCount = 0,
  contextOpen,
  onContextOpenChange,
  contextContent,
}: JobDetailCompactHeaderProps) {
  const sourcingActive = SOURCING_TABS.has(activeTab);
  const toolsActive = TOOL_TABS.has(activeTab);

  return (
    <Collapsible open={contextOpen} onOpenChange={onContextOpenChange}>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="px-4 py-3">
          <EntityHeader
            density="compact"
            title={title}
            badges={
              referenceNumber || badges ? (
                <>
                  {referenceNumber ? (
                    <Badge
                      variant="outline"
                      className="font-mono"
                      title="Numer referencyjny rekrutacji"
                    >
                      {referenceNumber}
                    </Badge>
                  ) : null}
                  {badges}
                </>
              ) : undefined
            }
            metadata={metadata}
            actions={
              <>
                {presence}
                {onAddCandidate ? (
                  <Button
                    type="button"
                    size="sm"
                    onClick={onAddCandidate}
                    data-testid="open-add-candidates"
                    title="Wyszukaj kandydatów i dodaj ich do pipeline"
                  >
                    <UserPlus className="h-4 w-4" />
                    Dodaj kandydata
                  </Button>
                ) : null}

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className={cn(sourcingActive && "border-primary text-primary")}
                      aria-label="Pozyskaj kandydatów"
                      aria-current={sourcingActive ? "page" : undefined}
                    >
                      <Search className="h-4 w-4" />
                      Pozyskaj
                      <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56">
                    <DropdownMenuLabel>Pozyskiwanie</DropdownMenuLabel>
                    <DropdownMenuItem
                      aria-current={activeTab === "ai-matching" ? "page" : undefined}
                      onSelect={() => onTabChange("ai-matching")}
                    >
                      <Sparkles className="h-4 w-4" />
                      AI Matching
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      data-testid="tab-manual-search"
                      aria-current={activeTab === "manual-search" ? "page" : undefined}
                      onSelect={() => onTabChange("manual-search")}
                    >
                      <Search className="h-4 w-4" />
                      Wyszukaj manualnie
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      aria-current={activeTab === "portals" ? "page" : undefined}
                      onSelect={() => onTabChange("portals")}
                    >
                      <Link2 className="h-4 w-4" />
                      Portale ogłoszeniowe
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>

                {onEdit || onWriteAnnouncement || onGenerateInviteLink ? (
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="outline"
                        aria-label="Więcej akcji rekrutacji"
                        title="Więcej akcji"
                      >
                        <Ellipsis className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                      <DropdownMenuLabel>Rekrutacja</DropdownMenuLabel>
                      {onEdit ? (
                        <DropdownMenuItem
                          onSelect={() => deferMenuAction(onEdit)}
                        >
                          <PencilLine className="h-4 w-4" />
                          Edytuj
                        </DropdownMenuItem>
                      ) : null}
                      {onWriteAnnouncement ? (
                        <DropdownMenuItem
                          onSelect={() => deferMenuAction(onWriteAnnouncement)}
                        >
                          <Wand2 className="h-4 w-4" />
                          AI Ogłoszenie
                        </DropdownMenuItem>
                      ) : null}
                      {onGenerateInviteLink ? (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() =>
                              deferMenuAction(onGenerateInviteLink)
                            }
                          >
                            <Link2 className="h-4 w-4" />
                            Wygeneruj link
                          </DropdownMenuItem>
                        </>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </>
            }
          />
        </div>

        <div className="flex min-w-0 items-center justify-between gap-2 border-t border-border px-1">
          <nav
            className="flex min-w-0 items-center overflow-x-auto overscroll-x-contain"
            aria-label="Sekcje rekrutacji"
          >
            <WorkspaceButton
              active={activeTab === "pipeline"}
              onClick={() => onTabChange("pipeline")}
            >
              Pipeline
            </WorkspaceButton>
            <WorkspaceButton
              active={activeTab === "history"}
              onClick={() => onTabChange("history")}
              data-testid="tab-history"
            >
              <History className="h-4 w-4" />
              Historia
            </WorkspaceButton>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <WorkspaceButton
                  active={toolsActive}
                  aria-label={
                    chatUnreadCount > 0
                      ? `Narzędzia, ${chatUnreadCount > 99 ? "ponad 99" : chatUnreadCount} nieprzeczytane`
                      : "Narzędzia"
                  }
                >
                  Narzędzia
                  {chatUnreadCount > 0 ? (
                    <Badge
                      variant="danger"
                      size="sm"
                      className="tabular-nums"
                      aria-hidden="true"
                    >
                      {chatUnreadCount > 99 ? "99+" : chatUnreadCount}
                    </Badge>
                  ) : null}
                  <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                </WorkspaceButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuLabel>Narzędzia rekrutacji</DropdownMenuLabel>
                <DropdownMenuItem
                  data-testid="tab-champion"
                  aria-current={activeTab === "champion" ? "page" : undefined}
                  onSelect={() => onTabChange("champion")}
                >
                  <Sparkles className="h-4 w-4" />
                  Profil Championa
                </DropdownMenuItem>
                <DropdownMenuItem
                  data-testid="tab-questions"
                  aria-current={activeTab === "questions" ? "page" : undefined}
                  onSelect={() => onTabChange("questions")}
                >
                  <UserCheck className="h-4 w-4" />
                  Baza pytań
                </DropdownMenuItem>
                <DropdownMenuItem
                  data-testid="tab-chat"
                  aria-current={activeTab === "chat" ? "page" : undefined}
                  aria-label={
                    chatUnreadCount > 0
                      ? `Chat, ${chatUnreadCount > 99 ? "ponad 99" : chatUnreadCount} nieprzeczytane`
                      : "Chat"
                  }
                  onSelect={() => onTabChange("chat")}
                >
                  <MessageCircle className="h-4 w-4" />
                  Chat
                  {chatUnreadCount > 0 ? (
                    <Badge
                      variant="danger"
                      size="sm"
                      className="ml-auto tabular-nums"
                      aria-hidden="true"
                    >
                      {chatUnreadCount > 99 ? "99+" : chatUnreadCount}
                    </Badge>
                  ) : null}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </nav>

          <CollapsibleTrigger asChild>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="shrink-0 text-muted-foreground"
              aria-expanded={contextOpen}
              aria-controls="job-operational-context"
              data-testid="toggle-job-header"
              title={contextOpen ? "Ukryj zespół i priorytet" : "Pokaż zespół i priorytet"}
            >
              <UserCheck className="h-4 w-4" />
              <span className="hidden sm:inline">Zespół i priorytet</span>
              {contextOpen ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </CollapsibleTrigger>
        </div>

        <CollapsibleContent id="job-operational-context">
          <div className="space-y-3 border-t border-border bg-muted/30 p-4">
            {contextContent}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
