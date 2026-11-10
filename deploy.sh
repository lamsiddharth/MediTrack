#!/usr/bin/env bash
# Deploy both tiers to the EC2 instance.
#
# Uses AWS Systems Manager rather than SSH, so no inbound port 22 is needed on
# the instance at all. The source is staged in S3 and the instance pulls it
# using its own instance role; configuration comes from Parameter Store the
# same way. No credential is ever passed on a command line or stored on the
# instance.
#
#   ./deploy.sh
#
# Requires: aws cli v2 with permission to call ssm:SendCommand and to write
# the deploy prefix of the bucket. The instance needs the SSM agent running
# (Amazon Linux 2023 ships it) and an instance profile — see README.
set -euo pipefail

# Pinned under its own name for the same reason as the region below: an
# ambient AWS_PROFILE pointing at a different account would otherwise be
# inherited silently, and every lookup would come back empty.
MEDITRACK_PROFILE="${MEDITRACK_PROFILE:-new}"
export AWS_PROFILE="$MEDITRACK_PROFILE"

# Pinned under its own name on purpose. AWS_REGION is often already set in a
# shell for some unrelated account, and it takes precedence over
# AWS_DEFAULT_REGION, so `${AWS_REGION:-...}` would silently inherit the wrong
# region and every lookup here would come back empty. Override with
# MEDITRACK_REGION if this ever moves.
MEDITRACK_REGION="${MEDITRACK_REGION:-ap-southeast-2}"
export AWS_REGION="$MEDITRACK_REGION"
export AWS_DEFAULT_REGION="$MEDITRACK_REGION"

# The bucket name embeds an AWS account id, so it is not committed. Set
# S3_BUCKET, or put the name in .s3-bucket (gitignored).
if [[ -z "${S3_BUCKET:-}" && -f .s3-bucket ]]; then
  S3_BUCKET="$(tr -d '[:space:]' < .s3-bucket)"
fi
if [[ -z "${S3_BUCKET:-}" ]]; then
  echo "S3_BUCKET is not set and .s3-bucket does not exist." >&2
  echo "  echo <your-bucket-name> > .s3-bucket" >&2
  exit 1
fi
BUCKET="$S3_BUCKET"
PARAM_PREFIX="${PARAM_PREFIX:-/meditrack}"
REMOTE_DIR="/opt/meditrack"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
ARTIFACT="meditrack-${STAMP}.tar.gz"
S3_KEY="deploy/${ARTIFACT}"

# ---------------------------------------------------------------------------
# Find the instance by tag, so no id has to be remembered.
# ---------------------------------------------------------------------------
INSTANCE="${INSTANCE_ID:-$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=meditrack" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null | grep -v '^None$' || true)}"

if [[ -z "$INSTANCE" ]]; then
  echo "No running instance tagged Name=meditrack in ${AWS_REGION}." >&2
  echo "Launch one first — see README, Deploying." >&2
  exit 1
fi

PUBLIC_IP="$(aws ec2 describe-instances --instance-ids "$INSTANCE" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"

echo "==> Instance : ${INSTANCE}  (${PUBLIC_IP})"
echo "==> Transport: AWS Systems Manager (no SSH)"
echo

# ---------------------------------------------------------------------------
# 1. The agent must be reachable before anything is uploaded.
# ---------------------------------------------------------------------------
echo "==> Checking the SSM agent"
PING="$(aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=${INSTANCE}" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)"
if [[ "$PING" != "Online" ]]; then
  echo "The SSM agent is not Online (status: ${PING:-none})." >&2
  echo "Check that the instance profile includes AmazonSSMManagedInstanceCore" >&2
  echo "and that the instance can reach the SSM endpoints." >&2
  exit 1
fi
echo "    Online"

# ---------------------------------------------------------------------------
# 2. Package and stage the source.
# ---------------------------------------------------------------------------
echo "==> Packaging source"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

tar czf "${TMP}/${ARTIFACT}" \
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
  app frontend docker-compose.yml

echo "    $(du -h "${TMP}/${ARTIFACT}" | cut -f1)"

echo "==> Staging to s3://${BUCKET}/${S3_KEY}"
aws s3 cp "${TMP}/${ARTIFACT}" "s3://${BUCKET}/${S3_KEY}" --only-show-errors
echo "    uploaded"

# ---------------------------------------------------------------------------
# 3. Tell the instance to pull it and bring the stack up.
#
# Everything sensitive is read on the instance from Parameter Store using the
# instance role, so this command document contains no secrets — which matters,
# because SSM retains command history and parameters are visible in it.
# ---------------------------------------------------------------------------
read -r -d '' REMOTE <<'REMOTE_SCRIPT' || true
set -eux
echo "=== deploy $(date -u +%FT%TZ) ==="

REGION="$(curl -sf -H "X-aws-ec2-metadata-token: $(curl -sf -X PUT \
  http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" \
  http://169.254.169.254/latest/meta-data/placement/region)"

param() { aws ssm get-parameter --name "$1" --with-decryption \
            --region "$REGION" --query Parameter.Value --output text; }

rm -rf "__REMOTE_DIR__" && mkdir -p "__REMOTE_DIR__"
aws s3 cp "s3://__BUCKET__/__S3_KEY__" /tmp/src.tar.gz --region "$REGION" --only-show-errors
tar xzf /tmp/src.tar.gz -C "__REMOTE_DIR__"
rm -f /tmp/src.tar.gz
cd "__REMOTE_DIR__"

# Configuration is assembled here, on the instance, from Parameter Store.
umask 077
{
  echo "SECRET_KEY=$(param __PARAM_PREFIX__/secret-key)"
  echo "STORAGE_BACKEND=s3"
  echo "S3_BUCKET=$(param __PARAM_PREFIX__/s3-bucket)"
  echo "S3_PREFIX=$(param __PARAM_PREFIX__/s3-prefix)"
  echo "AWS_REGION=${REGION}"
  echo "TZ_NAME=Asia/Kolkata"
  # Optional: present only once an RDS endpoint has been stored.
  if url="$(aws ssm get-parameter --name __PARAM_PREFIX__/database-url \
             --with-decryption --region "$REGION" \
             --query Parameter.Value --output text 2>/dev/null)"; then
    echo "DATABASE_URL=${url}"
  fi
} > .env

# Clear anything from a previous application that would hold port 80.
for old in meditrack pantry mealie; do
  docker ps -a --format '{{.Names}}' | grep -qx "$old" && docker rm -f "$old" >/dev/null || true
done

docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null 2>&1 || true

echo "=== containers ==="
docker compose ps
echo "DEPLOY_OK"
REMOTE_SCRIPT

REMOTE="${REMOTE//__REMOTE_DIR__/$REMOTE_DIR}"
REMOTE="${REMOTE//__BUCKET__/$BUCKET}"
REMOTE="${REMOTE//__S3_KEY__/$S3_KEY}"
REMOTE="${REMOTE//__PARAM_PREFIX__/$PARAM_PREFIX}"

echo "==> Building on the instance (first run pulls base images; several minutes)"
# The request is assembled as JSON. The shorthand --parameters syntax cannot
# carry a multi-line value: it collapses the script to one line with literal
# backslash-n sequences, which then fails to parse on the instance.
printf '%s' "$REMOTE" > "${TMP}/remote.sh"
python3 - "$INSTANCE" "$STAMP" "${TMP}/remote.sh" "${TMP}/ssm.json" <<'ENCODE'
import json, sys
instance, stamp, script_path, out_path = sys.argv[1:5]
script = open(script_path).read()
request = {
    "InstanceIds": [instance],
    "DocumentName": "AWS-RunShellScript",
    "Comment": f"MediTrack deploy {stamp}"[:100],
    "Parameters": {
        "executionTimeout": ["3600"],
        # One element per line; SSM rejoins them with newlines.
        "commands": script.splitlines(),
    },
}
json.dump(request, open(out_path, "w"))
ENCODE

CMD_ID="$(aws ssm send-command --cli-input-json "file://${TMP}/ssm.json" \
  --query 'Command.CommandId' --output text)"
echo "    command: ${CMD_ID}"

# ---------------------------------------------------------------------------
# 4. Wait, reporting progress rather than sitting silent.
# ---------------------------------------------------------------------------
STATUS="Pending"
for _ in $(seq 1 120); do
  STATUS="$(aws ssm get-command-invocation --command-id "$CMD_ID" \
    --instance-id "$INSTANCE" --query Status --output text 2>/dev/null || echo Pending)"
  case "$STATUS" in
    Success|Failed|Cancelled|TimedOut) break ;;
  esac
  printf '.'
  sleep 10
done
echo
echo "    ${STATUS}"

OUT="$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE" \
  --query StandardOutputContent --output text 2>/dev/null || true)"

if [[ "$STATUS" != "Success" ]]; then
  echo >&2
  echo "Deployment failed. Last output:" >&2
  printf '%s\n' "$OUT" | tail -40 | sed 's/^/  /' >&2
  aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE" \
    --query StandardErrorContent --output text 2>/dev/null | tail -20 | sed 's/^/  err: /' >&2
  echo >&2
  echo "Full log on the instance: /var/log/meditrack-deploy.log" >&2
  exit 1
fi

printf '%s\n' "$OUT" | tail -15 | sed 's/^/    /'

# ---------------------------------------------------------------------------
# 5. Verify from outside, which is the only check that matters.
# ---------------------------------------------------------------------------
echo "==> Verifying over HTTP"
for _ in $(seq 1 40); do
  if [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${PUBLIC_IP}/healthz" || true)" == "200" ]]; then
    SHELL_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${PUBLIC_IP}/" || true)"
    echo
    echo "Deployed.  http://${PUBLIC_IP}/"
    echo "  api : healthy"
    echo "  web : HTTP ${SHELL_CODE} on /"
    echo
    echo "Sign in with admin / admin123, then change the password from the"
    echo "Account page. The instance is publicly reachable on port 80."
    exit 0
  fi
  sleep 3
done

echo >&2
echo "The stack built but did not answer on http://${PUBLIC_IP}/ within two minutes." >&2
echo "Check the container logs:" >&2
echo "  aws ssm send-command --instance-ids ${INSTANCE} --document-name AWS-RunShellScript \\" >&2
echo "    --parameters 'commands=[\"cd ${REMOTE_DIR} && docker compose logs --tail=50\"]'" >&2
exit 1
