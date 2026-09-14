// Sentry-enabled production builds require a verifiable release and map upload.
if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  const missing = [];
  if (!process.env.SENTRY_AUTH_TOKEN) missing.push('SENTRY_AUTH_TOKEN (source maps not uploaded)');
  if (!/^[0-9a-f]{40}$/i.test(process.env.NEXT_PUBLIC_GIT_SHA ?? '')) {
    missing.push('full release SHA');
  }
  if (missing.length > 0) {
    console.error(`SENTRY_BUILD_CONFIGURATION_INCOMPLETE: ${missing.join('; ')}`);
    process.exit(1);
  } else {
    console.log(`SENTRY_BUILD_CONFIGURATION_OK release=${process.env.NEXT_PUBLIC_GIT_SHA}; upload failures abort the build`);
  }
} else {
  console.log('SENTRY_BUILD_DISABLED: no browser DSN configured');
}
