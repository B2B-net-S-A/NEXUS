"use client";

import Link from "next/link";
import { Network, BarChart3, MessageSquare, ChevronRight } from "lucide-react";

const ADMIN_TOOLS: Array<{
  href: string;
  title: string;
  description: string;
  icon: React.ReactNode;
}> = [
  {
    href: "/settings/team-structure",
    title: "Macierze przypisań",
    description: "TAC × kategorie kompetencji, TAC → DL, DL → klienci, LinkedIn farming.",
    icon: <Network className="w-5 h-5" />,
  },
  {
    href: "/settings/linkedin-metrics",
    title: "Aktywność LinkedIn",
    description: "Bulk edit dziennych liczb (CV / Msg / Resp) per TAC/sourcer.",
    icon: <BarChart3 className="w-5 h-5" />,
  },
  {
    href: "/settings/chats",
    title: "Globalny audyt czatów",
    description: "Przegląd wszystkich rozmów (projekty + kandydaci) z możliwością przeszukania treści.",
    icon: <MessageSquare className="w-5 h-5" />,
  },
];

export function AdminToolsGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {ADMIN_TOOLS.map((tool) => (
        <Link
          key={tool.href}
          href={tool.href}
          className="group bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 hover:border-primary hover:shadow-sm transition-all"
        >
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center flex-shrink-0">
              {tool.icon}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
                  {tool.title}
                </h3>
                <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-primary group-hover:translate-x-0.5 transition-all flex-shrink-0" />
              </div>
              <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">
                {tool.description}
              </p>
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

export default AdminToolsGrid;
