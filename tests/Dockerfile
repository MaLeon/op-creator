FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash jq util-linux iproute2 systemd systemd-sysv dbus dbus-user-session \
    sudo shellcheck python3 ca-certificates git procps \
    && rm -rf /var/lib/apt/lists/*
ARG OPENCLAW_VERSION=2026.9.5
RUN npm install -g "openclaw@${OPENCLAW_VERSION}"
RUN useradd -m -g operator -s /bin/bash operator && mkdir -p /var/lib/systemd/linger \
    && touch /var/lib/systemd/linger/operator
ENV container=docker
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
