#!/usr/bin/env bash
# Install this expert-harvest skill package on macOS/Linux.
# Usage: ./scripts/install.sh [dest_root]
# Default dest: ${EH_SKILL_HOME:-$HOME/.agents/skills}/function-files-pack
set -euo pipefail

flow_id="function-files-pack"
src="$(cd "$(dirname "$0")/.." && pwd)"
dest_root="${1:-${EH_SKILL_HOME:-$HOME/.agents/skills}}"
dest="${dest_root}/${flow_id}"

if [[ ! -f "${src}/SKILL.md" ]]; then
  echo "SKILL.md missing in ${src}" >&2
  exit 1
fi

mkdir -p "${dest}"
cp -R "${src}/." "${dest}/"
chmod +x "${dest}/scripts/"*.sh 2>/dev/null || true
printf '%s\n' "${dest}" > "${dest}/.installed-path"

echo "installed ${flow_id}"
echo "path=${dest}"
echo "entry=${dest}/SKILL.md"
echo "run=${dest}/scripts/run.sh"
