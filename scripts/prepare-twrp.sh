#!/usr/bin/env bash
# Fetch TWRP sources for b5q. Does not build or flash.
set -euo pipefail

WORKSPACE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TWRP_SOURCE="${TWRP_SOURCE:-${WORKSPACE_ROOT}/sources/twrp}"
TWRP_SYNC_JOBS="${TWRP_SYNC_JOBS:-8}"
REPO_TOOL="${WORKSPACE_ROOT}/artifacts/tools/repo"
mkdir -p "$(dirname -- "${REPO_TOOL}")" "${TWRP_SOURCE}"
# Keep GitHub transfers on HTTPS even if the host rewrites GitHub URLs to SSH.
# These per-process settings leave the user's Git configuration unchanged.
TWRP_GIT_CONFIG_COUNT="${GIT_CONFIG_COUNT:-0}"
for TWRP_GITHUB_ORG in TeamWin LineageOS dmXq-twrp-development phhusson minimal-manifest-twrp GerritCodeReview; do
    export "GIT_CONFIG_KEY_${TWRP_GIT_CONFIG_COUNT}=url.https://github.com/${TWRP_GITHUB_ORG}/.insteadOf"
    export "GIT_CONFIG_VALUE_${TWRP_GIT_CONFIG_COUNT}=https://github.com/${TWRP_GITHUB_ORG}/"
    TWRP_GIT_CONFIG_COUNT=$((TWRP_GIT_CONFIG_COUNT + 1))
done
export GIT_CONFIG_COUNT="${TWRP_GIT_CONFIG_COUNT}"
if [[ ! -f "${REPO_TOOL}" ]]; then
    curl -fL --retry 3 https://raw.githubusercontent.com/GerritCodeReview/git-repo/main/repo -o "${REPO_TOOL}"
    chmod +x "${REPO_TOOL}"
fi
cd -- "${TWRP_SOURCE}"
# Prevent concurrent syncs from writing the same Git object databases.
exec 9>"${TWRP_SOURCE}/.b5q-sync.lock"
if ! flock -n 9; then
    echo "Another b5q source sync is already running in ${TWRP_SOURCE}" >&2
    exit 1
fi
if [[ ! -d .repo/manifests ]]; then
    "${REPO_TOOL}" init \
        --repo-url=https://github.com/GerritCodeReview/git-repo.git \
        --repo-rev=refs/tags/v2.54 \
        -u https://github.com/minimal-manifest-twrp/platform_manifest_twrp_aosp.git \
        -b twrp-12.1 --depth=1 --no-clone-bundle
fi
mkdir -p .repo/local_manifests
cp "${WORKSPACE_ROOT}/manifests/twrp-b5q.xml" .repo/local_manifests/b5q.xml
"${REPO_TOOL}" sync -c --no-clone-bundle --no-tags --optimized-fetch -j"${TWRP_SYNC_JOBS}"
