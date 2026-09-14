// Production images with Sentry enabled must not silently skip symbol upload.
// Local builds and CI without a DSN can still run without production secrets.
if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  if (!process.env.SENTRY_AUTH_TOKEN || !/^[0-9a-f]{40}$/i.test(process.env.NEXT_PUBLIC_GIT_SHA ?? '')) {
    console.error('SENTRY_BUILD_CONFIGURATION_FAILED: upload token and full release SHA required');
    process.exit(1);
  }
  console.log(`SENTRY_BUILD_CONFIGURATION_OK release=${process.env.NEXT_PUBLIC_GIT_SHA}; upload failures abort the build`);
} else {
  console.log('SENTRY_BUILD_DISABLED: no browser DSN configured');
}
