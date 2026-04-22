/**
 * Public apply layout — minimal shell (no sidebar/topbar, no auth).
 * Theme: light, cream canvas consistent with v2.
 */

export default function ApplyLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      data-ui="v2"
      data-ui-theme="apply-light"
      className="min-h-screen bg-[hsl(var(--bg-canvas))] text-[hsl(var(--text-body))]"
    >
      {children}
    </div>
  );
}
