import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom doesn't ship ResizeObserver, but cmdk (used by Popover/Command-based
// filters) needs it to mount. Stub a no-op implementation.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).ResizeObserver = ResizeObserverStub;
}

// jsdom doesn't implement Element.prototype.scrollIntoView; cmdk calls it on
// every active item to keep it in view. Stub it to a no-op so tests don't crash.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}

// Ensure DOM is cleaned between tests
afterEach(() => {
  cleanup();
});
