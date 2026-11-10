#!/usr/bin/env bash
# Shared settings for the provisioning scripts. Source this, do not run it.
#
#   source infra/00-config.sh
#
# Every script in infra/ is idempotent: re-running reuses existing resources
# rather than creating duplicates. IDs are recorded in infra/state.env.

export AWS_PROFILE="${AWS_PROFILE:-new}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-southeast-2}"

# Region and Availability Zones. Subnets are created in BOTH zones so the
# architecture can become multi-AZ later without re-addressing the network,
# but compute and the database are only launched in AZ_A for now.
export REGION="ap-southeast-2"          # Asia Pacific (Sydney)
export AZ_A="ap-southeast-2a"           # active zone
export AZ_B="ap-southeast-2b"           # standby zone, subnets only

export PROJECT="meditrack"

# Addressing. A /16 with room to grow; /24 subnets are far larger than needed
# but keep the arithmetic obvious.
export VPC_CIDR="10.20.0.0/16"
export SUBNET_PUBLIC_A="10.20.1.0/24"   # presentation tier, AZ a
export SUBNET_PUBLIC_B="10.20.2.0/24"   # presentation tier, AZ b (unused)
export SUBNET_PRIVATE_A="10.20.11.0/24" # application + data tier, AZ a
export SUBNET_PRIVATE_B="10.20.12.0/24" # application + data tier, AZ b (RDS subnet group)

# Instances
export FRONTEND_TYPE="t3.micro"
export BACKEND_TYPE="t3.micro"
export KEY_NAME="${PROJECT}-key"

# Database
export DB_IDENTIFIER="${PROJECT}-db"
export DB_NAME="meditrack"
export DB_USER="meditrack"
export DB_CLASS="db.t4g.micro"
export DB_ENGINE_VERSION="16.4"
export DB_STORAGE_GB="20"

# Object storage. Already provisioned; see README.
# Not committed: the bucket name embeds an AWS account id. Set S3_BUCKET in
# the environment, or put the name in .s3-bucket at the repository root.
if [[ -z "${S3_BUCKET:-}" && -f "$(dirname "${BASH_SOURCE[0]}")/../.s3-bucket" ]]; then
  S3_BUCKET="$(tr -d '[:space:]' < "$(dirname "${BASH_SOURCE[0]}")/../.s3-bucket")"
fi
export S3_BUCKET="${S3_BUCKET:-}"
export S3_PREFIX="session-notes"

STATE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/state.env"
export STATE_FILE

# Record a resource id so later scripts can find it.
save_state() {
  local key="$1" value="$2"
  touch "$STATE_FILE"
  grep -v "^export ${key}=" "$STATE_FILE" > "${STATE_FILE}.tmp" 2>/dev/null || true
  mv "${STATE_FILE}.tmp" "$STATE_FILE"
  echo "export ${key}=${value}" >> "$STATE_FILE"
  export "${key}=${value}"
  echo "    ${key}=${value}"
}

load_state() {
  # shellcheck disable=SC1090
  [[ -f "$STATE_FILE" ]] && source "$STATE_FILE"
}

require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: ${name} is not set. Run the earlier infra/ scripts first." >&2
    exit 1
  fi
}

load_state
