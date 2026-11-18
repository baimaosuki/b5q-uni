#!/usr/bin/env bash
# Build b5q recovery and package a recovery-only Odin tar. Does not flash devices.
set -e -o pipefail

WORKSPACE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TWRP_SOURCE="${TWRP_SOURCE:-${WORKSPACE_ROOT}/sources/twrp}"
TWRP_JOBS="${TWRP_JOBS:-8}"
TWRP_OUT="${TWRP_OUT:-${WORKSPACE_ROOT}/artifacts/twrp-b5q}"
REPO_TOOL="${WORKSPACE_ROOT}/artifacts/tools/repo"

if [[ ! -f "${TWRP_SOURCE}/build/envsetup.sh" ]]; then
    echo "TWRP sources are incomplete: ${TWRP_SOURCE}/build/envsetup.sh" >&2
    exit 1
fi
mkdir -p "${TWRP_OUT}" "${WORKSPACE_ROOT}/logs"
cd -- "${TWRP_SOURCE}"
export ALLOW_MISSING_DEPENDENCIES=true
export LC_ALL=C
for TWRP_PATCH in "${WORKSPACE_ROOT}"/patches/twrp-soong/*.patch; do
    [[ -f "${TWRP_PATCH}" ]] || continue
    if git -C build/soong apply --reverse --check "${TWRP_PATCH}" >/dev/null 2>&1; then
        continue
    fi
    git -C build/soong apply --check "${TWRP_PATCH}"
    git -C build/soong apply "${TWRP_PATCH}"
done
source build/envsetup.sh
lunch twrp_b5q-eng
m -j"${TWRP_JOBS}" recoveryimage

PRODUCT_DIR="${TWRP_SOURCE}/out/target/product/b5q"
python3 "${WORKSPACE_ROOT}/scripts/package-twrp.py" \
    --image "${PRODUCT_DIR}/recovery.img" --output "${TWRP_OUT}"
python3 "${WORKSPACE_ROOT}/scripts/verify-twrp-ramdisk.py"     --image "${TWRP_OUT}/recovery.img"     --lz4 "${TWRP_SOURCE}/out/host/linux-x86/bin/lz4" --output "${TWRP_OUT}"
"${REPO_TOOL}" manifest -r -o "${TWRP_OUT}/source-manifest.xml"
