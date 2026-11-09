#!/bin/bash
# EC2 user-data: prepare the host to build and run the application container.
# Log: /var/log/cloud-init-output.log
#
# Needs no AWS credentials and no instance role for its own sake. Pass this
# file verbatim as user-data; it has no placeholders to substitute.
#
# ./deploy.sh then sends the source here, builds both tiers and starts them.
set -eux

# Two Docker CLI plugins have to be installed by hand on Amazon Linux 2023.
#
# Compose: `dnf install docker-compose-plugin` fails with "Unable to find a
# match" — the package does not exist in the AL2023 repos, and under `set -e`
# that aborts this script before Docker is ever enabled.
#
# Buildx: the `docker` package does ship one, but an old build (0.12), and
# Compose v5 refuses to build with anything below 0.17 ("compose build requires
# buildx 0.17.0 or later"). So a current one is needed too.
COMPOSE_VERSION="${COMPOSE_VERSION:-v5.7.0}"
BUILDX_VERSION="${BUILDX_VERSION:-v0.38.2}"

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

# /usr/local/lib takes precedence over the /usr/libexec path the dnf package
# uses, so these shadow the bundled plugin without clobbering a managed file.
PLUGIN_DIR=/usr/local/lib/docker/cli-plugins
mkdir -p "$PLUGIN_DIR"
ARCH="$(uname -m)"   # x86_64 or aarch64, matching the release asset names

# --retry covers the 5xx that the release CDN intermittently returns; without
# it a transient 504 fails the entire launch.
fetch_plugin() {  # url, destination
  curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 10 \
    "$1" -o "$2"
  chmod +x "$2"
}

fetch_plugin \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
  "$PLUGIN_DIR/docker-compose"

# buildx comes from its official image rather than a GitHub release asset.
# The release CDN returns a persistent 504 for this particular file, and the
# instance already depends on Docker Hub for base images, so this adds no new
# dependency while removing a flaky one.
# The image is built FROM scratch and holds only the binary, so it has no
# shell to run a copy with. Create a container without starting it and copy
# the file out instead.
# The trailing /buildx is a command argument, which `docker create` insists on
# even for a container that is never started; the image declares none.
buildx_cid="$(docker create "docker/buildx-bin:${BUILDX_VERSION#v}" /buildx)"
docker cp "${buildx_cid}:/buildx" "$PLUGIN_DIR/docker-buildx"
docker rm "$buildx_cid" >/dev/null
chmod +x "$PLUGIN_DIR/docker-buildx"

# Fail loudly here rather than leaving a host that looks ready but cannot
# bring the stack up.
docker compose version
docker buildx version

# Lets the login user run docker without sudo after the next login. deploy.sh
# uses sudo regardless, so it does not depend on this.
usermod -aG docker ec2-user || true

echo DONE > /opt/bootstrap-done
