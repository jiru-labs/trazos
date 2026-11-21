#!/usr/bin/env bash
# Prepare one original (photo or scan) for review. Nothing here touches your repo:
# output goes to a staging folder OUTSIDE git on purpose, because git history is
# forever. A piece enters pieces/ only after a human has looked at it.
#
#   tools/prepare.sh <original.heic|jpg|png> <id>      e.g. 2026-001
#
# Env: TRAZOS_STAGING (default ~/trazos-staging), TRAZOS_OCR_LANGS (default eng; e.g. spa+eng)
# Needs: ImageMagick (with HEIC support for iPhone photos), exiftool, tesseract.
set -euo pipefail
[[ $# -eq 2 ]] || { sed -n '5p' "$0" >&2; exit 2; }
src=$1 id=$2
[[ $id =~ ^[0-9]{4}-[0-9]{3}$ ]] || { echo "id must look like 2026-001" >&2; exit 1; }
[[ -r $src ]] || { echo "cannot read $src" >&2; exit 1; }
im=$(command -v magick || command -v convert) || { echo "ImageMagick not found" >&2; exit 1; }
for tool in exiftool tesseract; do command -v $tool >/dev/null || { echo "$tool not found" >&2; exit 1; }; done

stage=${TRAZOS_STAGING:-$HOME/trazos-staging}/$id
mkdir -p "$stage"
"$im" "$src" -auto-orient -resize '1600x1600>' -strip -quality 82 "$stage/$id.jpg"
"$im" "$stage/$id.jpg" -resize '600x600>' -strip -quality 78 "$stage/$id-thumb.jpg"
exiftool -q -all= -overwrite_original "$stage/$id.jpg" "$stage/$id-thumb.jpg"
# Proof that nothing identifying is left: any GPS/date/camera tag fails here.
# One file per call: with several files exiftool prints "==== name" headers, which would always match.
for f in "$stage/$id.jpg" "$stage/$id-thumb.jpg"; do
  if exiftool -s -s -s -GPS:all -DateTimeOriginal -Make -Model "$f" | grep -q .; then
    echo "metadata left in $f" >&2; exit 1
  fi
done
# Text a reviewer must read before publishing: a signed surname, a school, a street.
tesseract "$stage/$id.jpg" - -l "${TRAZOS_OCR_LANGS:-eng}" 2>/dev/null > "$stage/ocr.txt" || true
year=${id%%-*}
[[ -e $stage/$id.md ]] || cat > "$stage/$id.md" <<MD
---
id: $id
year: $year
age:
technique:
title: ""
tags:
favourite: no
---
MD
echo "staged $stage ($(du -k "$stage/$id.jpg" | cut -f1) KB). OCR text to review:"
sed 's/^/  | /' "$stage/ocr.txt"
