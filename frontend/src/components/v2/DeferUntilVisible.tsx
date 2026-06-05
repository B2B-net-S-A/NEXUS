"use client";

import * as React from "react";

/**
 * Mounts `children` only once the wrapper scrolls within `rootMargin` of the
 * viewport. Used to keep below-the-fold widgets (which each fire their own API
 * calls on mount) out of the initial page-load request burst — they load when
 * the user actually scrolls near them. Reserves `minHeight` until mounted so
 * the page layout/scroll position doesn't jump when content appears.
 */
export function DeferUntilVisible({
  children,
  minHeight = 120,
  rootMargin = "300px",
  className,
}: {
  children: React.ReactNode;
  minHeight?: number;
  rootMargin?: string;
  className?: string;
}) {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = React.useState(false);

  React.useEffect(() => {
    if (visible) return;
    const el = ref.current;
    if (!el) return;
    // SSR / older browsers: render eagerly rather than hide content forever.
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible, rootMargin]);

  return (
    <div ref={ref} className={className} style={visible ? undefined : { minHeight }}>
      {visible ? children : null}
    </div>
  );
}
