#!/usr/bin/env bash
set -euo pipefail
[[ $(uname -s) == Linux && $EUID != 0 ]] || { echo '请在 Linux 上以普通用户安装。' >&2; exit 1; }
((BASH_VERSINFO[0] >= 5)) || { echo '需要 Bash 5+' >&2; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
target="$HOME/.local/bin"
mkdir -p -- "$target"
install -m 0755 -- "$source_dir/bin/openclaw-instance" "$target/openclaw-instance"
printf '已安装到 %s/openclaw-instance\n请确保 ~/.local/bin 在 PATH 中，然后运行 openclaw-instance preflight。\n' "$target"
