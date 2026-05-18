#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "usage: $0 <input-file> [output-dir]" >&2
    exit 2
fi

INPUT="$1"
OUTDIR="${2:-/tmp/office-convert}"

mkdir -p "$OUTDIR"

filename=$(basename -- "$INPUT")
stem="${filename%.*}"
ext="${filename##*.}"
ext=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')

case "$ext" in
    doc) target="docx" ;;
    xls) target="xlsx" ;;
    ppt) target="pptx" ;;
    *)
        echo "unsupported legacy office format: .$ext" >&2
        exit 1
        ;;
esac

soffice --headless --convert-to "$target" --outdir "$OUTDIR" "$INPUT" >/dev/null

OUTPUT="$OUTDIR/$stem.$target"
if [ ! -f "$OUTPUT" ]; then
    echo "conversion did not produce expected file: $OUTPUT" >&2
    exit 1
fi

printf '%s\n' "$OUTPUT"
