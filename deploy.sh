#!/usr/bin/env bash
# Send the application source to the instance, build the image there, and run it.
#
# No container registry, and no Docker needed on this machine. Only the source
# is transferred, which is well under a megabyte.
#
# Usage:
#   ./deploy.sh                      # uses .static-ip and a key from ~/.ssh
#   PUBLIC_IP=1.2.3.4 SSH_KEY=~/.ssh/key.pem ./deploy.sh
#
# NOTE: this needs outbound SSH. If Cloudflare WARP or a similar tunnel is
# active, port 22 will time out — turn it off for the duration of the deploy.
set -euo pipefail

SSH_USER="${SSH_USER:-ec2-user}"
TAG="${IMAGE_TAG:-$(date -u +%Y%m%d-%H%M%S)}"
IMAGE="meditrack:${TAG}"
CONTAINER="meditrack"
VOLUME="meditrack-data"
REMOTE_DIR="/home/${SSH_USER}/meditrack-src"
TZ_NAME="${TZ_NAME:-Asia/Kolkata}"

# ---------------------------------------------------------------------------
# Resolve target and key
# ---------------------------------------------------------------------------
if [[ -z "${PUBLIC_IP:-}" ]]; then
  if [[ -f .static-ip ]]; then
    PUBLIC_IP="$(tr -d '[:space:]' < .static-ip)"
  else
    echo "PUBLIC_IP is not set and .static-ip does not exist." >&2
    echo "Usage: PUBLIC_IP=<ip> $0" >&2
    exit 1
  fi
fi

if [[ -z "${SSH_KEY:-}" ]]; then
  for candidate in "$HOME/.ssh/meditrack-key.pem" "$HOME/.ssh/hospital-key.pem" \
                   "$HOME/.ssh/pantry-key.pem" "$HOME/.ssh/mealie-key.pem"; do
    [[ -f "$candidate" ]] && { SSH_KEY="$candidate"; break; }
  done
fi
if [[ -z "${SSH_KEY:-}" || ! -f "$SSH_KEY" ]]; then
  echo "No SSH key found. Set SSH_KEY=/path/to/key.pem" >&2
  exit 1
fi

# SECRET_KEY signs session cookies. Generated once and remembered, so that
# redeploying does not sign everyone out.
if [[ -f .secret-key ]]; then
  SECRET_KEY="$(tr -d '[:space:]' < .secret-key)"
else
  SECRET_KEY="$(head -c 32 /dev/urandom | base64 | tr -d '=+/' | cut -c1-43)"
  printf '%s\n' "$SECRET_KEY" > .secret-key
  chmod 600 .secret-key
  echo "==> Generated .secret-key (keep it; it is gitignored)"
fi

# Object storage for session notes. With .aws-app-credentials present the
# deployed app uses S3; without it, it falls back to a directory inside the
# data volume, which still works but keeps notes on the instance.
#
# Lightsail has no IAM instance roles, which is why static credentials are
# needed here rather than a role. The file holds a user scoped to
# s3:PutObject/GetObject on one bucket prefix and nothing else.
STORAGE_ENV=()
if [[ -f .aws-app-credentials ]]; then
  # shellcheck disable=SC1091
  set -a; source .aws-app-credentials; set +a
  if [[ -z "${S3_BUCKET:-}" || -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
    echo "WARNING: .aws-app-credentials is missing S3_BUCKET or AWS_ACCESS_KEY_ID." >&2
    echo "         Falling back to local storage." >&2
  else
    STORAGE_ENV=(
      -e "STORAGE_BACKEND=s3"
      -e "S3_BUCKET=${S3_BUCKET}"
      -e "S3_PREFIX=${S3_PREFIX:-session-notes}"
      -e "AWS_REGION=${AWS_REGION:-ap-southeast-2}"
      -e "AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}"
      -e "AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}"
    )
    echo "==> Session notes -> s3://${S3_BUCKET}/${S3_PREFIX:-session-notes}"
  fi
fi
if [[ ${#STORAGE_ENV[@]} -eq 0 ]]; then
  STORAGE_ENV=(-e "STORAGE_BACKEND=local")
  echo "==> Session notes -> local storage on the instance (no .aws-app-credentials)"
fi

SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15
     "${SSH_USER}@${PUBLIC_IP}")

echo "==> Target : ${SSH_USER}@${PUBLIC_IP}"
echo "==> Image  : ${IMAGE}  (built on the instance)"
echo

# ---------------------------------------------------------------------------
# 1. Reachability
# ---------------------------------------------------------------------------
echo "==> Checking SSH"
if ! "${SSH[@]}" true 2>/dev/null; then
  echo >&2
  echo "Cannot SSH to ${PUBLIC_IP}:22." >&2
  echo >&2
  echo "Most likely causes, in order:" >&2
  echo "  1. A VPN or tunnel is intercepting outbound SSH. Check with:" >&2
  echo "       curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp=" >&2
  echo "     If it says warp=on, turn it off and retry." >&2
  echo "  2. The security group does not allow your current IP." >&2
  echo "     Your apparent IP: $(curl -fsS https://checkip.amazonaws.com 2>/dev/null || echo unknown)" >&2
  echo "  3. The instance is still booting." >&2
  exit 1
fi

if ! "${SSH[@]}" 'command -v docker >/dev/null && sudo systemctl is-active --quiet docker'; then
  echo "Docker is not installed or not running on the instance." >&2
  echo "On a fresh instance the user-data bootstrap may still be going:" >&2
  echo "  ssh -i $SSH_KEY ${SSH_USER}@${PUBLIC_IP} 'tail /var/log/cloud-init-output.log'" >&2
  exit 1
fi

DISK_GB="$("${SSH[@]}" "df -BG --output=avail / | tail -1 | tr -dc '0-9'" || echo 0)"
echo "    ${DISK_GB}GB free disk"
if (( DISK_GB < 3 )); then
  echo "Only ${DISK_GB}GB free; need ~3GB for the Python base image and build." >&2
  echo "  ssh -i $SSH_KEY ${SSH_USER}@${PUBLIC_IP} 'sudo docker system prune -af'" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Send the source
# ---------------------------------------------------------------------------
echo "==> Transferring source"
"${SSH[@]}" "rm -rf '${REMOTE_DIR}' && mkdir -p '${REMOTE_DIR}'"

tar czf - \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='data' \
  --exclude='*.db' \
  --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  -C app . \
  | "${SSH[@]}" "tar xzf - -C '${REMOTE_DIR}'"

echo "    sent $("${SSH[@]}" "du -sh '${REMOTE_DIR}' | cut -f1")"

# ---------------------------------------------------------------------------
# 3. Build and run
# ---------------------------------------------------------------------------
echo "==> Building and starting (a minute or two)"
"${SSH[@]}" "sudo bash -s" <<REMOTE
set -euo pipefail

cd '${REMOTE_DIR}'
docker build --tag '${IMAGE}' .

docker volume inspect '${VOLUME}' >/dev/null 2>&1 || docker volume create '${VOLUME}' >/dev/null

# Clear out any previous application on this box. Port 80 can only have one
# occupant, and the old images are worth reclaiming on a small disk.
#
# Data volumes are deliberately NOT removed: the recipe app's volume still
# holds its database, so removing only the container and image leaves that
# recoverable rather than destroying it.
for old in meditrack pantry mealie; do
  if docker ps -a --format '{{.Names}}' | grep -qx "\$old"; then
    echo "    removing previous container: \$old"
    docker rm -f "\$old" >/dev/null
  fi
done

for repo in pantry mealie ghcr.io/mealie-recipes/mealie; do
  ids=\$(docker images --filter "reference=\${repo}" --format '{{.ID}}' | sort -u)
  if [ -n "\$ids" ]; then
    echo "    removing previous images: \$repo"
    echo "\$ids" | xargs -r docker rmi -f >/dev/null 2>&1 || true
  fi
done

docker run -d \
  --name '${CONTAINER}' \
  --restart=always \
  -p 80:9000 \
  --memory=512m \
  -v '${VOLUME}':/data \
  -e DATA_DIR=/data \
  -e SECRET_KEY='${SECRET_KEY}' \
  -e TZ='${TZ_NAME}' \
  ${STORAGE_ENV[@]@Q} \
  '${IMAGE}'

# Keep the two most recent images for rollback; drop the rest and the cache.
docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep '^meditrack:' \
  | tail -n +3 \
  | xargs -r -n1 docker rmi -f >/dev/null 2>&1 || true
docker builder prune -af >/dev/null 2>&1 || true
REMOTE

# ---------------------------------------------------------------------------
# 4. Verify
# ---------------------------------------------------------------------------
echo "==> Waiting for the application to answer"
for _ in $(seq 1 40); do
  if [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${PUBLIC_IP}/healthz" || true)" == "200" ]]; then
    echo
    echo "Deployed.  http://${PUBLIC_IP}/"
    echo "Image:     ${IMAGE}"
    echo
    echo "Sign in with admin / admin123, then change the password from the"
    echo "Account page. The instance is publicly reachable on port 80."
    exit 0
  fi
  sleep 3
done

echo >&2
echo "The application did not become healthy within two minutes. Check:" >&2
echo "  ssh -i $SSH_KEY ${SSH_USER}@${PUBLIC_IP} 'sudo docker logs ${CONTAINER}'" >&2
exit 1
