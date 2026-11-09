#!/usr/bin/env bash
# Send the source to the instance, build both tiers there, and start them.
#
# No container registry, and no Docker needed on this machine. Only the source
# is transferred, which is a few megabytes.
#
# Usage:
#   ./deploy.sh                      # uses .static-ip and a key from ~/.ssh
#   PUBLIC_IP=1.2.3.4 SSH_KEY=~/.ssh/key.pem ./deploy.sh
#
# NOTE: this needs outbound SSH. If Cloudflare WARP or a similar tunnel is
# active, port 22 will time out — turn it off for the duration of the deploy.
set -euo pipefail

SSH_USER="${SSH_USER:-ec2-user}"
REMOTE_DIR="/home/${SSH_USER}/meditrack"
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

SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15
     "${SSH_USER}@${PUBLIC_IP}")

echo "==> Target : ${SSH_USER}@${PUBLIC_IP}"
echo "==> Tiers  : web (nginx + React) and api (FastAPI), built on the instance"
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

if ! "${SSH[@]}" 'docker compose version >/dev/null 2>&1 || sudo docker compose version >/dev/null 2>&1'; then
  echo "The Docker Compose plugin is missing on the instance." >&2
  echo "bootstrap.sh installs it; on an older instance run:" >&2
  echo "  sudo dnf install -y docker-compose-plugin" >&2
  exit 1
fi

DISK_GB="$("${SSH[@]}" "df -BG --output=avail / | tail -1 | tr -dc '0-9'" || echo 0)"
echo "    ${DISK_GB}GB free disk"
if (( DISK_GB < 5 )); then
  echo "Only ${DISK_GB}GB free; the node and python base images need ~5GB." >&2
  echo "  ssh -i $SSH_KEY ${SSH_USER}@${PUBLIC_IP} 'sudo docker system prune -af'" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Send the source for both tiers
# ---------------------------------------------------------------------------
echo "==> Transferring source"
"${SSH[@]}" "rm -rf '${REMOTE_DIR}' && mkdir -p '${REMOTE_DIR}'"

tar czf - \
  --exclude='node_modules' \
  --exclude='dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='data' \
  --exclude='*.db' \
  --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  --exclude='*.tsbuildinfo' \
  app frontend docker-compose.yml \
  | "${SSH[@]}" "tar xzf - -C '${REMOTE_DIR}'"

echo "    sent $("${SSH[@]}" "du -sh '${REMOTE_DIR}' | cut -f1")"

# ---------------------------------------------------------------------------
# 3. Write the environment file on the instance
# ---------------------------------------------------------------------------
# Built locally so credentials are never echoed into the remote shell's
# history or process list.
ENV_CONTENT="SECRET_KEY=${SECRET_KEY}
TZ_NAME=${TZ_NAME}
"
if [[ -f .aws-app-credentials ]]; then
  # shellcheck disable=SC1091
  set -a; source .aws-app-credentials; set +a
  if [[ -n "${S3_BUCKET:-}" && -n "${AWS_ACCESS_KEY_ID:-}" ]]; then
    ENV_CONTENT+="STORAGE_BACKEND=s3
S3_BUCKET=${S3_BUCKET}
S3_PREFIX=${S3_PREFIX:-session-notes}
AWS_REGION=${AWS_REGION:-ap-southeast-2}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
"
    echo "==> Session notes -> s3://${S3_BUCKET}/${S3_PREFIX:-session-notes}"
  else
    ENV_CONTENT+="STORAGE_BACKEND=local
"
    echo "WARNING: .aws-app-credentials incomplete; using local storage." >&2
  fi
else
  ENV_CONTENT+="STORAGE_BACKEND=local
"
  echo "==> Session notes -> local storage on the instance (no .aws-app-credentials)"
fi

if [[ -f .database-url ]]; then
  ENV_CONTENT+="DATABASE_URL=$(tr -d '[:space:]' < .database-url)
"
  echo "==> Database -> RDS (from .database-url)"
else
  echo "==> Database -> SQLite in the data volume (no .database-url)"
fi

printf '%s' "$ENV_CONTENT" | "${SSH[@]}" "cat > '${REMOTE_DIR}/.env' && chmod 600 '${REMOTE_DIR}/.env'"

# ---------------------------------------------------------------------------
# 4. Build and start both tiers
# ---------------------------------------------------------------------------
echo "==> Building and starting (first run pulls base images; allow a few minutes)"
"${SSH[@]}" "sudo bash -s" <<REMOTE
set -euo pipefail
cd '${REMOTE_DIR}'

# Clear anything from a previous application that would hold port 80.
for old in meditrack pantry mealie; do
  if docker ps -a --format '{{.Names}}' | grep -qx "\$old"; then
    echo "    removing previous container: \$old"
    docker rm -f "\$old" >/dev/null
  fi
done

docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null 2>&1 || true

echo "    containers:"
docker compose ps --format '      {{.Service}}  {{.Status}}  {{.Ports}}'
REMOTE

# ---------------------------------------------------------------------------
# 5. Verify
# ---------------------------------------------------------------------------
echo "==> Waiting for the application to answer"
for _ in $(seq 1 40); do
  if [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${PUBLIC_IP}/healthz" || true)" == "200" ]]; then
    # The SPA shell must also be served, not just the proxied API.
    shell="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${PUBLIC_IP}/" || true)"
    echo
    echo "Deployed.  http://${PUBLIC_IP}/"
    echo "  api  : healthy"
    echo "  web  : HTTP ${shell} on /"
    echo
    echo "Sign in with admin / admin123, then change the password from the"
    echo "Account page. The instance is publicly reachable on port 80."
    exit 0
  fi
  sleep 3
done

echo >&2
echo "The stack did not become healthy within two minutes. Check:" >&2
echo "  ssh -i $SSH_KEY ${SSH_USER}@${PUBLIC_IP} 'cd ${REMOTE_DIR} && sudo docker compose logs --tail=50'" >&2
exit 1
