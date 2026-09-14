#!/bin/sh
# Executed ONLY by the remote Coolify builder, after it has tagged the
# generated compose services with the actual checked-out commit.
set -eu

fail() { echo "NEXUS_RELEASE_BUILD_FAILED: $1" >&2; exit 1; }
[ "$#" -eq 4 ] || fail "expected project directory and build env file"
[ "$1" = "--project-directory" ] && [ "$3" = "--env-file" ] || fail "invalid arguments"
project_dir=$2
build_env=$4
[ -f "$project_dir/docker-compose.yml" ] || fail "missing generated compose file"
[ -f "$build_env" ] || fail "missing Coolify build environment"

compose() {
    docker compose --project-directory "$project_dir" \
        --env-file "$build_env" -f "$project_dir/docker-compose.yml" "$@"
}

# Never print full compose config: it contains secrets. Only image names
# leave `config`, and even those are kept out of logs.
images=$(compose config --images) || fail "cannot inspect generated image tags"
backend_image=$(printf '%s\n' "$images" | grep -E '^[a-z0-9]+_backend:[0-9a-f]{40}$' || true)
sha=${backend_image##*:}
[ "${#sha}" -eq 40 ] || fail "missing or ambiguous backend commit tag"
printf '%s' "$sha" | grep -Eq '^[0-9a-f]{40}$' || fail "invalid backend commit tag"
# A second backend image would make backend_image multiline, even if its
# last SHA happens to be valid. Require exactly the expected single value.
app_prefix=${backend_image%_backend:*}
case "$app_prefix" in
    ""|*[!a-z0-9]*) fail "ambiguous application image tags" ;;
esac
printf '%s\n' "$images" | grep -Fxq "${app_prefix}_frontend:${sha}" || fail "frontend/backend commit tags disagree"

echo "NEXUS_RELEASE_BUILD_VERIFIED release=$sha source=coolify-image-tags"
# Explicit CLI build args override any stale/default values in parsed YAML.
# Other build arguments (including the source-map token) stay in Coolify's
# generated configuration/env file and are never echoed by this wrapper.
compose build --pull --build-arg "GIT_SHA=$sha" --build-arg "NEXT_PUBLIC_GIT_SHA=$sha"
