#!/usr/bin/env bash
# Three security groups, chained so each tier only accepts traffic from the one
# in front of it. Rules reference other security groups rather than CIDR
# ranges, so they stay correct if instances are replaced or re-addressed.
#
#   frontend  :80 from the internet, :22 from the admin address
#   backend   :9000 from the frontend SG only, :22 from the frontend SG only
#   database  :5432 from the backend SG only
#
#   ./infra/20-security-groups.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/00-config.sh
require VPC_ID

ADMIN_CIDR="${ADMIN_CIDR:-$(curl -fsS https://checkip.amazonaws.com)/32}"
echo "==> Admin access will be allowed from ${ADMIN_CIDR}"
echo "    (if a VPN or WARP is on, this is the tunnel's address, not yours)"

make_sg() {  # name, description -> id
  local name="$1" desc="$2" id
  id="$(aws ec2 describe-security-groups \
        --filters "Name=group-name,Values=${name}" "Name=vpc-id,Values=${VPC_ID}" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null | grep -v '^None$' || true)"
  if [[ -z "$id" ]]; then
    id="$(aws ec2 create-security-group --group-name "$name" --description "$desc" \
      --vpc-id "$VPC_ID" --query 'GroupId' --output text)"
  fi
  echo "$id"
}

# allow <sg> <proto> <port> from-cidr <cidr> | from-sg <sg>
allow() {
  local sg="$1" proto="$2" port="$3" kind="$4" src="$5"
  if [[ "$kind" == "from-cidr" ]]; then
    aws ec2 authorize-security-group-ingress --group-id "$sg" \
      --ip-permissions "IpProtocol=${proto},FromPort=${port},ToPort=${port},IpRanges=[{CidrIp=${src}}]" \
      >/dev/null 2>&1 || true
  else
    aws ec2 authorize-security-group-ingress --group-id "$sg" \
      --ip-permissions "IpProtocol=${proto},FromPort=${port},ToPort=${port},UserIdGroupPairs=[{GroupId=${src}}]" \
      >/dev/null 2>&1 || true
  fi
}

echo "==> Security groups"
SG_FRONTEND="$(make_sg "${PROJECT}-sg-frontend" "Presentation tier: public reverse proxy")"
SG_BACKEND="$(make_sg "${PROJECT}-sg-backend"  "Application tier: private app server")"
SG_DATABASE="$(make_sg "${PROJECT}-sg-database" "Data tier: RDS PostgreSQL")"

save_state SG_FRONTEND "$SG_FRONTEND"
save_state SG_BACKEND "$SG_BACKEND"
save_state SG_DATABASE "$SG_DATABASE"

# --- frontend: the only tier exposed to the internet -----------------------
echo "==> frontend: :80 from anywhere, :22 from admin only"
allow "$SG_FRONTEND" tcp 80 from-cidr 0.0.0.0/0
allow "$SG_FRONTEND" tcp 22 from-cidr "$ADMIN_CIDR"

# --- backend: reachable only from the frontend ------------------------------
# No internet ingress at all. The frontend proxies to :9000, and the frontend
# doubles as the bastion for SSH, so the private instance needs no public path.
echo "==> backend: :9000 and :22 from the frontend security group only"
allow "$SG_BACKEND" tcp 9000 from-sg "$SG_FRONTEND"
allow "$SG_BACKEND" tcp 22   from-sg "$SG_FRONTEND"

# --- database: reachable only from the backend -----------------------------
echo "==> database: :5432 from the backend security group only"
allow "$SG_DATABASE" tcp 5432 from-sg "$SG_BACKEND"

echo
echo "Security groups ready."
echo
echo "Chain:  internet --:80--> frontend --:9000--> backend --:5432--> RDS"
echo "Nothing in the private subnets accepts a connection from the internet."
