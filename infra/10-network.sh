#!/usr/bin/env bash
# Build the VPC: subnets across two AZs, an Internet Gateway for the public
# tier, a NAT Gateway for the private tier's outbound traffic, route tables,
# and a Gateway VPC Endpoint for S3.
#
#   ./infra/10-network.sh
#
# Idempotent: existing resources are found by their Name tag and reused.
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/00-config.sh

echo "==> Region ${REGION}, zones ${AZ_A} (active) and ${AZ_B} (standby)"

# ---------------------------------------------------------------------------
# VPC
# ---------------------------------------------------------------------------
find_by_tag() {  # resource-type, name  ->  id or empty
  aws ec2 describe-"$1"s \
    --filters "Name=tag:Name,Values=$2" "Name=state,Values=available,pending" \
    --query "$(tr '[:lower:]' '[:upper:]' <<< "${1:0:1}")${1:1}s[0].${3}" \
    --output text 2>/dev/null | grep -v '^None$' || true
}

VPC_ID="$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=${PROJECT}-vpc" \
          --query 'Vpcs[0].VpcId' --output text 2>/dev/null | grep -v '^None$' || true)"

if [[ -z "$VPC_ID" ]]; then
  echo "==> Creating VPC ${VPC_CIDR}"
  VPC_ID="$(aws ec2 create-vpc --cidr-block "$VPC_CIDR" \
    --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=${PROJECT}-vpc}]" \
    --query 'Vpc.VpcId' --output text)"
  aws ec2 wait vpc-available --vpc-ids "$VPC_ID"
  # Private DNS names for instances. This is what lets the frontend address the
  # backend without Route 53: the VPC resolver answers for internal names.
  aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support
  aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames
else
  echo "==> Reusing VPC"
fi
save_state VPC_ID "$VPC_ID"

# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------
make_subnet() {  # name, cidr, az, public?
  local name="$1" cidr="$2" az="$3" public="$4" id
  id="$(aws ec2 describe-subnets --filters "Name=tag:Name,Values=${name}" \
        "Name=vpc-id,Values=${VPC_ID}" --query 'Subnets[0].SubnetId' \
        --output text 2>/dev/null | grep -v '^None$' || true)"
  if [[ -z "$id" ]]; then
    id="$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "$cidr" \
      --availability-zone "$az" \
      --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${name}}]" \
      --query 'Subnet.SubnetId' --output text)"
    aws ec2 wait subnet-available --subnet-ids "$id"
    if [[ "$public" == "yes" ]]; then
      aws ec2 modify-subnet-attribute --subnet-id "$id" --map-public-ip-on-launch
    fi
  fi
  echo "$id"
}

echo "==> Subnets"
save_state SUBNET_PUB_A_ID "$(make_subnet "${PROJECT}-public-a"  "$SUBNET_PUBLIC_A"  "$AZ_A" yes)"
save_state SUBNET_PUB_B_ID "$(make_subnet "${PROJECT}-public-b"  "$SUBNET_PUBLIC_B"  "$AZ_B" yes)"
save_state SUBNET_PRV_A_ID "$(make_subnet "${PROJECT}-private-a" "$SUBNET_PRIVATE_A" "$AZ_A" no)"
save_state SUBNET_PRV_B_ID "$(make_subnet "${PROJECT}-private-b" "$SUBNET_PRIVATE_B" "$AZ_B" no)"

# ---------------------------------------------------------------------------
# Internet Gateway. Gives the public subnet two-way internet reachability:
# inbound so users reach the frontend, outbound for package installs.
# ---------------------------------------------------------------------------
IGW_ID="$(aws ec2 describe-internet-gateways \
  --filters "Name=attachment.vpc-id,Values=${VPC_ID}" \
  --query 'InternetGateways[0].InternetGatewayId' --output text 2>/dev/null | grep -v '^None$' || true)"

if [[ -z "$IGW_ID" ]]; then
  echo "==> Creating and attaching Internet Gateway"
  IGW_ID="$(aws ec2 create-internet-gateway \
    --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Name,Value=${PROJECT}-igw}]" \
    --query 'InternetGateway.InternetGatewayId' --output text)"
  aws ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID"
fi
save_state IGW_ID "$IGW_ID"

# ---------------------------------------------------------------------------
# NAT Gateway, in the public subnet. Lets the private tier reach out (yum
# updates, AWS APIs) while remaining unreachable from the internet, because
# NAT translates outbound connections only.
# ---------------------------------------------------------------------------
NAT_ID="$(aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=${VPC_ID}" "Name=state,Values=available,pending" \
  --query 'NatGateways[0].NatGatewayId' --output text 2>/dev/null | grep -v '^None$' || true)"

if [[ -z "$NAT_ID" ]]; then
  echo "==> Allocating Elastic IP for NAT"
  NAT_EIP_ALLOC="$(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=${PROJECT}-nat-eip}]" \
    --query 'AllocationId' --output text)"
  save_state NAT_EIP_ALLOC "$NAT_EIP_ALLOC"

  echo "==> Creating NAT Gateway in ${AZ_A} public subnet (takes a few minutes)"
  NAT_ID="$(aws ec2 create-nat-gateway --subnet-id "$SUBNET_PUB_A_ID" \
    --allocation-id "$NAT_EIP_ALLOC" \
    --tag-specifications "ResourceType=natgateway,Tags=[{Key=Name,Value=${PROJECT}-nat}]" \
    --query 'NatGateway.NatGatewayId' --output text)"
  aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_ID"
fi
save_state NAT_ID "$NAT_ID"

# ---------------------------------------------------------------------------
# Route tables
# ---------------------------------------------------------------------------
make_rt() {  # name -> id
  local name="$1" id
  id="$(aws ec2 describe-route-tables --filters "Name=tag:Name,Values=${name}" \
        "Name=vpc-id,Values=${VPC_ID}" --query 'RouteTables[0].RouteTableId' \
        --output text 2>/dev/null | grep -v '^None$' || true)"
  if [[ -z "$id" ]]; then
    id="$(aws ec2 create-route-table --vpc-id "$VPC_ID" \
      --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=${name}}]" \
      --query 'RouteTable.RouteTableId' --output text)"
  fi
  echo "$id"
}

associate() {  # route-table-id, subnet-id
  aws ec2 associate-route-table --route-table-id "$1" --subnet-id "$2" >/dev/null 2>&1 || true
}

echo "==> Route tables"
RT_PUBLIC="$(make_rt "${PROJECT}-rt-public")"
save_state RT_PUBLIC "$RT_PUBLIC"
# Public subnets: default route to the internet via the IGW.
aws ec2 create-route --route-table-id "$RT_PUBLIC" \
  --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID" >/dev/null 2>&1 || true
associate "$RT_PUBLIC" "$SUBNET_PUB_A_ID"
associate "$RT_PUBLIC" "$SUBNET_PUB_B_ID"

RT_PRIVATE="$(make_rt "${PROJECT}-rt-private")"
save_state RT_PRIVATE "$RT_PRIVATE"
# Private subnets: default route to the NAT Gateway. No IGW route exists here,
# which is precisely what makes these subnets private.
aws ec2 create-route --route-table-id "$RT_PRIVATE" \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_ID" >/dev/null 2>&1 || true
associate "$RT_PRIVATE" "$SUBNET_PRV_A_ID"
associate "$RT_PRIVATE" "$SUBNET_PRV_B_ID"

# ---------------------------------------------------------------------------
# S3 Gateway Endpoint. Session-note traffic then travels over the AWS network
# via a route table entry rather than out through the NAT Gateway: no per-GB
# NAT processing charge, and S3 access no longer depends on the NAT at all.
# ---------------------------------------------------------------------------
VPCE_ID="$(aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=${VPC_ID}" "Name=service-name,Values=com.amazonaws.${REGION}.s3" \
  --query 'VpcEndpoints[0].VpcEndpointId' --output text 2>/dev/null | grep -v '^None$' || true)"

if [[ -z "$VPCE_ID" ]]; then
  echo "==> Creating S3 Gateway Endpoint"
  VPCE_ID="$(aws ec2 create-vpc-endpoint --vpc-id "$VPC_ID" \
    --service-name "com.amazonaws.${REGION}.s3" \
    --vpc-endpoint-type Gateway \
    --route-table-ids "$RT_PRIVATE" \
    --tag-specifications "ResourceType=vpc-endpoint,Tags=[{Key=Name,Value=${PROJECT}-s3-endpoint}]" \
    --query 'VpcEndpoint.VpcEndpointId' --output text)"
fi
save_state VPCE_S3_ID "$VPCE_ID"

echo
echo "Network ready. State written to ${STATE_FILE}"
