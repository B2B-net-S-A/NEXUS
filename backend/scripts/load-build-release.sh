# Image metadata takes precedence over mutable platform environment variables.
# A default/missing file retains host-native and legacy image behavior.
load_build_release() {
    [ -f "$1" ] || return 0
    local build_sha
    build_sha=$(cat "$1")
    if [[ "$build_sha" =~ ^[0-9a-f]{40}$ ]]; then
        export GIT_SHA="$build_sha"
    fi
}
