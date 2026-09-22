#!/usr/bin/env bash
# Pack files related to a described feature. Writes only under output_dir.
set -euo pipefail

: "${input_dir:?set input_dir}"
: "${feature_query:?set feature_query}"
output_dir="${output_dir:-./out}"
extra_keywords="${extra_keywords:-}"

root="$(cd "$(dirname "$0")/.." && pwd)"
python3 "${root}/scripts/pack_feature.py" "$input_dir" "$feature_query" "$output_dir" "$extra_keywords"
