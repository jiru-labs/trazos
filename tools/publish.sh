#!/usr/bin/env bash
# Move a reviewed piece from staging into a content folder's pieces/, then build.
# Run it only after a human has checked the image and its OCR text.
#
#   tools/publish.sh <id> [CONTENT_DIR]      (default CONTENT_DIR: current directory)
set -euo pipefail
id=$1 content=${2:-$PWD}
engine=$(cd "$(dirname "$0")/.." && pwd)
stage=${TRAZOS_STAGING:-$HOME/trazos-staging}/$id
for f in "$id.jpg" "$id-thumb.jpg" "$id.md"; do [[ -s $stage/$f ]] || { echo "missing $stage/$f" >&2; exit 1; }; done
mkdir -p "$content/pieces"
cp "$stage/$id.jpg" "$stage/$id-thumb.jpg" "$stage/$id.md" "$content/pieces/"
python3 "$engine/build.py" "$content"
echo "next: git -C $content add pieces/$id* && git -C $content commit -m 'Add $id' && git -C $content push"
