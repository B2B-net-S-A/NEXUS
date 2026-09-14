// Production images with Sentry enabled must not SILENTLY skip symbol upload —
// but a missing upload token or release SHA must not fail the image either.
// The shared observability standard for all apps says builds pass without
// SENTRY_AUTH_TOKEN (upload becomes a no-op). A hard exit here, together with
// Coolify not supplying SOURCE_COMMIT at build time, meant no frontend image
// could be built at all (14.09.2026). So: loud, grep-able warning, exit 0.
if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  const missing = [];
  if (!process.env.SENTRY_AUTH_TOKEN) missing.push('SENTRY_AUTH_TOKEN (source maps not uploaded)');
  if (!/^[0-9a-f]{40}$/i.test(process.env.NEXT_PUBLIC_GIT_SHA ?? '')) {
    missing.push(`full release SHA (got "${process.env.NEXT_PUBLIC_GIT_SHA ?? ''}")`);
  }
  if (missing.length > 0) {
    console.warn(`SENTRY_BUILD_CONFIGURATION_INCOMPLETE: ${missing.join('; ')} — build continues`);
  } else {
    console.log(`SENTRY_BUILD_CONFIGURATION_OK release=${process.env.NEXT_PUBLIC_GIT_SHA}; upload failures abort the build`);
  }
} else {
  console.log('SENTRY_BUILD_DISABLED: no browser DSN configured');
}
