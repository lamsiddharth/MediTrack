#!/bin/bash
# User-data for the PRIVATE instance (application tier).
#
# Installs Docker and nothing else. The application image is built here from
# source sent over SSH by deploy.sh, which reaches this host through the
# frontend instance acting as a bastion.
#
# Outbound package installs work because the private subnet routes 0.0.0.0/0
# to the NAT Gateway. Nothing inbound from the internet can reach this host.
set -eux

if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

dnf install -y docker tar gzip
systemctl enable --now docker
usermod -aG docker ec2-user || true

echo DONE > /opt/bootstrap-backend-done
