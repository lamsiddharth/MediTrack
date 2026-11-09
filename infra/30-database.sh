#!/usr/bin/env bash
# RDS PostgreSQL in the private subnets.
#
# The DB subnet group spans both Availability Zones because RDS requires at
# least two, but the instance is created single-AZ (--no-multi-az). That is a
# deliberate cost decision and the main availability gap in this design: see
# the report, Results and Limitations.
#
#   ./infra/30-database.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/00-config.sh
require VPC_ID
require SUBNET_PRV_A_ID
require SUBNET_PRV_B_ID
require SG_DATABASE

# ---------------------------------------------------------------------------
# Subnet group: both private subnets, so RDS is satisfied and a later move to
# Multi-AZ needs no network change.
# ---------------------------------------------------------------------------
if ! aws rds describe-db-subnet-groups --db-subnet-group-name "${PROJECT}-db-subnets" >/dev/null 2>&1; then
  echo "==> Creating DB subnet group across ${AZ_A} and ${AZ_B}"
  aws rds create-db-subnet-group \
    --db-subnet-group-name "${PROJECT}-db-subnets" \
    --db-subnet-group-description "Private subnets for ${PROJECT} RDS" \
    --subnet-ids "$SUBNET_PRV_A_ID" "$SUBNET_PRV_B_ID" >/dev/null
else
  echo "==> Reusing DB subnet group"
fi

# ---------------------------------------------------------------------------
# Password. Generated locally and kept in a gitignored file; the report notes
# Secrets Manager as the correct destination for this.
# ---------------------------------------------------------------------------
if [[ -f .db-password ]]; then
  DB_PASSWORD="$(tr -d '[:space:]' < .db-password)"
  echo "==> Reusing .db-password"
else
  # Alphanumeric only: RDS rejects several punctuation characters in passwords.
  DB_PASSWORD="$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32)"
  printf '%s\n' "$DB_PASSWORD" > .db-password
  chmod 600 .db-password
  echo "==> Generated .db-password (mode 600, gitignored)"
fi

# ---------------------------------------------------------------------------
# Instance
# ---------------------------------------------------------------------------
if aws rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" >/dev/null 2>&1; then
  echo "==> Reusing existing RDS instance ${DB_IDENTIFIER}"
else
  echo "==> Creating RDS PostgreSQL ${DB_ENGINE_VERSION} (${DB_CLASS}), single-AZ in ${AZ_A}"
  echo "    This takes roughly 10 minutes."
  aws rds create-db-instance \
    --db-instance-identifier "$DB_IDENTIFIER" \
    --db-instance-class "$DB_CLASS" \
    --engine postgres \
    --engine-version "$DB_ENGINE_VERSION" \
    --master-username "$DB_USER" \
    --master-user-password "$DB_PASSWORD" \
    --db-name "$DB_NAME" \
    --allocated-storage "$DB_STORAGE_GB" \
    --storage-type gp3 \
    --storage-encrypted \
    --db-subnet-group-name "${PROJECT}-db-subnets" \
    --vpc-security-group-ids "$SG_DATABASE" \
    --availability-zone "$AZ_A" \
    --no-multi-az \
    --no-publicly-accessible \
    --backup-retention-period 7 \
    --preferred-backup-window "17:00-18:00" \
    --copy-tags-to-snapshot \
    --deletion-protection \
    --tags "Key=Name,Value=${DB_IDENTIFIER}" >/dev/null

  echo "==> Waiting for the instance to become available"
  aws rds wait db-instance-available --db-instance-identifier "$DB_IDENTIFIER"
fi

DB_ENDPOINT="$(aws rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" \
  --query 'DBInstances[0].Endpoint.Address' --output text)"
DB_AZ="$(aws rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" \
  --query 'DBInstances[0].AvailabilityZone' --output text)"

save_state DB_ENDPOINT "$DB_ENDPOINT"
save_state DB_AZ "$DB_AZ"

echo
echo "RDS ready."
echo "  endpoint : ${DB_ENDPOINT}"
echo "  zone     : ${DB_AZ}  (single-AZ, no standby)"
echo "  reachable only from the backend security group, on 5432"
echo
echo "Connection string for the application tier:"
echo "  postgresql+psycopg://${DB_USER}:<password>@${DB_ENDPOINT}:5432/${DB_NAME}"
