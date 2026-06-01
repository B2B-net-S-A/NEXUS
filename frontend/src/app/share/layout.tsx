/**
 * Minimal layout for public /share/* routes.
 *
 * Wraps server-rendered share pages WITHOUT the authenticated app chrome –
 * no sidebar, no topbar, no QueryProvider, no theme/auth stores. The share
 * portal is public, cold-cache, SEO/copy-paste-friendly. Every byte of
 * client JS we skip lowers time-to-content for the recipient.
 *
 * The root layout still wraps this (it's a Next.js rule) – it sets
 * `data-ui` on <html> and loads fonts. But `AppShellV2.isSharePage` detects
 * `/share/*` and returns children without shell chrome, so no Sidebar/Topbar
 * render. This layout just scopes share-dark styling and strips extra DOM.
 */
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Nexus · Udostępnione",
  description: "Widok udostępniony przez Nexus ATS",
  robots: { index: false, follow: false },
};

export default function ShareLayout({ children }: { children: React.ReactNode }) {
  return <div data-share-root="true">{children}</div>;
}
