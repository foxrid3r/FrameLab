#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root in an MSYS2 UCRT64 shell. The revisions are
# deliberately pinned so release binaries can always be reproduced.
readonly FFMPEG_REVISION="1c2c67c0b9f7f66ab32c19dcf7f227bcd290aa4c" # n8.1.2
readonly X264_REVISION="b35605ace3ddf7c1a5d67a2eb553f034aef41d55"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BUILD_ROOT="${REPO_ROOT}/build/ffmpeg-minimal"
readonly SOURCE_ROOT="${BUILD_ROOT}/sources"
readonly PREFIX="${BUILD_ROOT}/prefix"
readonly OUTPUT="${BUILD_ROOT}/dist"
readonly SOURCE_OUTPUT="${OUTPUT}/sources"

mkdir -p "${SOURCE_ROOT}" "${PREFIX}" "${OUTPUT}" "${SOURCE_OUTPUT}"

clone_at_revision() {
    local url="$1"
    local revision="$2"
    local destination="$3"
    if [[ ! -d "${destination}/.git" ]]; then
        git clone --filter=blob:none --no-checkout "${url}" "${destination}"
    fi
    git -C "${destination}" fetch --depth 1 origin "${revision}"
    git -C "${destination}" checkout --detach --force FETCH_HEAD
}

clone_at_revision \
    "https://code.videolan.org/videolan/x264.git" \
    "${X264_REVISION}" \
    "${SOURCE_ROOT}/x264"

pushd "${SOURCE_ROOT}/x264"
if [[ -f config.mak ]]; then
    make distclean
fi
./configure \
    --prefix="${PREFIX}" \
    --enable-static \
    --disable-cli \
    --disable-opencl \
    --bit-depth=8 \
    --chroma-format=420
make -j"$(nproc)"
make install
popd

clone_at_revision \
    "https://git.ffmpeg.org/ffmpeg.git" \
    "${FFMPEG_REVISION}" \
    "${SOURCE_ROOT}/ffmpeg"

readonly FFMPEG_CONFIGURE=(
    --prefix="${PREFIX}"
    --arch=x86_64
    --target-os=mingw32
    --pkg-config-flags=--static
    --extra-cflags="-I${PREFIX}/include"
    --extra-ldflags="-L${PREFIX}/lib -static"
    --enable-gpl
    --enable-libx264
    --enable-static
    --disable-shared
    --disable-autodetect
    --disable-everything
    --disable-doc
    --disable-debug
    --disable-network
    --enable-small
    --enable-ffmpeg
    --disable-ffprobe
    --enable-protocol=file,pipe
    --enable-demuxer=mov,avi,matroska,asf
    --enable-decoder=h264,hevc,mjpeg,mpeg4,mpeg2video,vc1,wmv1,wmv2,wmv3
    --enable-parser=h264,hevc,mjpeg,mpeg4video,mpegvideo,vc1
    --enable-encoder=libx264
    --enable-muxer=mp4
    --enable-filter=buffer,buffersink,format,scale,null
    --enable-swscale
)

pushd "${SOURCE_ROOT}/ffmpeg"
if [[ -f ffbuild/config.mak ]]; then
    make distclean
fi
PKG_CONFIG_PATH="${PREFIX}/lib/pkgconfig" ./configure "${FFMPEG_CONFIGURE[@]}"
make -j"$(nproc)"
strip ffmpeg.exe
cp ffmpeg.exe "${OUTPUT}/ffmpeg.exe"
cp COPYING.GPLv2 "${OUTPUT}/FFmpeg-COPYING.GPLv2.txt"
cp ../x264/COPYING "${OUTPUT}/x264-COPYING.txt"
popd

{
    echo "FrameLab minimal FFmpeg build"
    echo "FFmpeg revision: ${FFMPEG_REVISION} (tag n8.1.2)"
    echo "FFmpeg commit: $(git -C "${SOURCE_ROOT}/ffmpeg" rev-parse HEAD)"
    echo "x264 revision: ${X264_REVISION}"
    echo "x264 commit: $(git -C "${SOURCE_ROOT}/x264" rev-parse HEAD)"
    echo "Toolchain: $(gcc --version | head -n 1)"
    echo
    echo "x264 configure arguments:"
    echo "  --enable-static"
    echo "  --disable-cli"
    echo "  --disable-opencl"
    echo "  --bit-depth=8"
    echo "  --chroma-format=420"
    echo
    echo "FFmpeg configure arguments:"
    for argument in "${FFMPEG_CONFIGURE[@]}"; do
        printf '  %q\n' "${argument//${PREFIX}/BUILD_PREFIX}"
    done
} > "${OUTPUT}/BUILD-INFO.txt"

git -C "${SOURCE_ROOT}/ffmpeg" archive \
    --format=tar.gz \
    --prefix=ffmpeg-n8.1.2/ \
    --output="${SOURCE_OUTPUT}/ffmpeg-n8.1.2-source.tar.gz" \
    HEAD
git -C "${SOURCE_ROOT}/x264" archive \
    --format=tar.gz \
    --prefix=x264-${X264_REVISION}/ \
    --output="${SOURCE_OUTPUT}/x264-${X264_REVISION}-source.tar.gz" \
    HEAD
cp "${REPO_ROOT}/tools/build_minimal_ffmpeg.sh" "${OUTPUT}/build_minimal_ffmpeg.sh"

(
    cd "${OUTPUT}"
    find . -type f ! -name SHA256SUMS.txt -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        > SHA256SUMS.txt
)

"${OUTPUT}/ffmpeg.exe" -hide_banner -version
du -h "${OUTPUT}/ffmpeg.exe"
