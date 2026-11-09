#!/bin/bash
# EC2 user-data: prepare the host to build and run the application container.
# Log: /var/log/cloud-init-output.log
#
# Needs no AWS credentials and no instance role for its own sake. Pass this
# file verbatim as user-data; it has no placeholders to substitute.
#
# ./deploy.sh then sends the source here, builds both tiers and starts them.
set -eux

# Docker Compose v2+ is distributed as a CLI plugin binary, not as an Amazon
# Linux 2023 package. `dnf install docker-compose-plugin` fails on AL2023 with
# "Unable to find a match", which under `set -e` aborts this whole script
# before Docker is ever enabled. So it is fetched directly below.
COMPOSE_VERSION="${COMPOSE_VERSION:-v5.7.0}"

# 1 GiB of RAM is comfortable for this application: two small containers, no
# separate database server, and the frontend bundle builds in seconds. A modest
# swapfile is still worth having as a safety margin during image builds.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

dnf install -y docker tar gzip
systemctl enable --now docker

# Install the Compose plugin where the Docker CLI looks for it.
PLUGIN_DIR=/usr/libexec/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"
ARCH="$(uname -m)"   # x86_64 or aarch64, matching the release asset names
curl -fsSL \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
  -o "$PLUGIN_DIR/docker-compose"
chmod +x "$PLUGIN_DIR/docker-compose"

# Fail loudly here rather than leaving a host that looks ready but cannot
# bring the stack up.
docker compose version

# Lets the login user run docker without sudo after the next login. deploy.sh
# uses sudo regardless, so it does not depend on this.
usermod -aG docker ec2-user || true

echo DONE > /opt/bootstrap-done
