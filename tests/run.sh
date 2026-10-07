#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
docker build -t openclaw-instance-test:2026.9.5 -f "$root/tests/Dockerfile" "$root"
docker run --rm -e LANG=C.UTF-8 -v "$root:/work:ro" --entrypoint /bin/bash \
    openclaw-instance-test:2026.9.5 -c \
    'shellcheck /work/bin/openclaw-instance /work/scripts/install.sh /work/tests/*.sh && su -s /bin/bash operator -c "python3 /work/tests/test_manager.py"'
