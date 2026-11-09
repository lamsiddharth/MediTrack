#!/bin/bash
# EC2 user-data: prepare the host to build and run the application container.
# Log: /var/log/cloud-init-output.log
#
# Needs no AWS credentials and no instance role. Pass this file verbatim as
# user-data; it has no placeholders to substitute.
#
# ./deploy.sh then sends the source here, builds the image and starts it.
set -eux

# 1 GiB of RAM is comfortable for this application: it is a single Python
# process with no frontend build and no separate database server. A modest
# swapfile is still worth having as a safety margin.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

dnf install -y docker tar gzip
systemctl enable --now docker

# Lets the login user run docker without sudo after the next login. deploy.sh
# uses sudo regardless, so it does not depend on this.
usermod -aG docker ec2-user || true

echo DONE > /opt/bootstrap-done
