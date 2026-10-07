#!/usr/bin/env bash
# Isolated real systemd/OpenClaw test. No host HOME or Docker socket is mounted.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
container="openclaw-instance-integration-$$"
image=openclaw-instance-test:2026.9.5
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker build -t "$image" -f "$root/tests/Dockerfile" "$root"
docker run -d --name "$container" --privileged --cgroupns=private \
    --tmpfs /run --tmpfs /run/lock -v "$root:/work:ro" "$image" >/dev/null
uid=$(docker exec "$container" id -u operator)
run() {
    docker exec -i -u operator -e HOME=/home/operator -e XDG_RUNTIME_DIR="/run/user/$uid" \
        "$container" "$@"
}
wait_manager() {
    local i
    for ((i=0;i<30;i++)); do
        if run systemctl --user show-environment >/dev/null 2>&1; then return; fi
        sleep 1
    done
    echo 'systemd 用户管理器未启动' >&2; return 1
}
wait_manager
run /work/scripts/install.sh
run /home/operator/.local/bin/openclaw-instance preflight

# An actual unmanaged profile and service must survive every manager operation.
run bash -s <<'SH'
set -euo pipefail
openclaw --profile legacy setup --baseline --workspace "$HOME/.openclaw-legacy/workspace" >/dev/null 2>&1
node -e 'console.log(JSON.stringify({gateway:{mode:"local",bind:"loopback",port:19600,auth:{mode:"token",token:require("node:crypto").randomBytes(32).toString("hex")}}}))' \
  | openclaw --profile legacy config patch --stdin >/dev/null 2>&1
openclaw --profile legacy gateway install --port 19600 >/dev/null 2>&1
sha256sum "$HOME/.openclaw-legacy/openclaw.json" "$HOME/.config/systemd/user/openclaw-gateway-legacy.service" > "$HOME/legacy.sha256"
SH
run /home/operator/.local/bin/openclaw-instance create alpha
run /home/operator/.local/bin/openclaw-instance create bravo
run bash -s <<'SH'
set -euo pipefail
manager="$HOME/.local/bin/openclaw-instance"
registry="$HOME/.local/state/openclaw-instance-manager/instances.json"
jq -e '.instances.alpha.port==19000 and .instances.bravo.port==19200' "$registry" >/dev/null
cmp -s "$HOME/.openclaw-alpha/openclaw.json" "$HOME/.openclaw-bravo/openclaw.json" && exit 1
if openclaw --profile alpha gateway health --port 19000 --token deliberately-wrong --timeout 2000 --json >/dev/null 2>&1; then
    echo '错误 token 不应通过鉴权' >&2; exit 1
fi
"$manager" stop alpha
"$manager" doctor bravo
"$manager" start alpha
"$manager" restart bravo
"$manager" remove alpha
test -f "$HOME/.openclaw-alpha/openclaw.json"
"$manager" start alpha
"$manager" logs alpha > /dev/null
sha256sum -c "$HOME/legacy.sha256"
SH
echo '重启隔离 systemd 容器，验证服务持久化……'
docker restart "$container" >/dev/null
wait_manager
run bash -s <<'SH'
set -euo pipefail
manager="$HOME/.local/bin/openclaw-instance"
for name in alpha bravo; do
    for ((i=0;i<30;i++)); do
        if "$manager" doctor "$name" >/dev/null 2>&1; then break; fi
        sleep 1
    done
    "$manager" doctor "$name"
done
"$manager" purge alpha --confirm alpha
test ! -e "$HOME/.openclaw-alpha"
"$manager" doctor bravo
"$manager" purge bravo --confirm bravo
test "$("$manager" list --json)" = '[]'
sha256sum -c "$HOME/legacy.sha256"
systemctl --user is-active openclaw-gateway-legacy.service
printf 'INTEGRATION PASS — OpenClaw '
openclaw --version
SH
