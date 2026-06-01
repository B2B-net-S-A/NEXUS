/**
 * DynaReporter section layout (Faza B.1).
 *
 * Wszystkie strony pod `/dynareporter/*` dziedziczą po nim. Auth + AppShellV2
 * (Sidebar + Topbar) wnoszone z root layout. Tutaj tylko ewentualne
 * sub-navigation per moduł – nadal puste, dochodzi w B.2.
 */
import { ReactNode } from "react";

export default function DynaReporterLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <section className="dynareporter-section">{children}</section>;
}
