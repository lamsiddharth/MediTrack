#!/bin/bash
# User-data for the PUBLIC instance (presentation tier).
#
# Installs nginx as a reverse proxy. This instance holds no application code,
# no database credentials and no AWS credentials: it terminates the public
# connection and forwards to the private application tier.
#
# __BACKEND_HOST__ is substituted by infra/40-instances.sh once the backend's
# private address is known.
set -eux

dnf install -y nginx

cat > /etc/nginx/conf.d/meditrack.conf <<'NGINX'
upstream meditrack_backend {
    # Private address of the application tier. Reachable only inside the VPC:
    # the private subnet has no Internet Gateway route, so this host cannot be
    # addressed from outside regardless of security group rules.
    server __BACKEND_HOST__:9000;

    # Reuse connections to the backend rather than reconnecting per request.
    keepalive 16;
}

server {
    listen 80 default_server;
    server_name _;

    # No Route 53 in this design, so there is no hostname to match on; the
    # instance is reached by its Elastic IP and this server block answers for
    # anything.

    client_max_body_size 12m;   # attachments are capped at 10m by the app

    location / {
        proxy_pass http://meditrack_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # The application needs the original client details to build correct
        # redirects and to log the real source address, since from the
        # backend's point of view every request arrives from this proxy.
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 5s;
        proxy_read_timeout    60s;
    }

    # Served by the proxy itself so a health check does not depend on the
    # backend being reachable; useful for telling the tiers apart when
    # diagnosing a fault.
    location = /nginx-health {
        access_log off;
        return 200 "frontend ok\n";
        add_header Content-Type text/plain;
    }
}
NGINX

# Remove the stock server block, which would otherwise own port 80.
sed -i '/^\s*server\s*{/,/^\s*}/d' /etc/nginx/nginx.conf 2>/dev/null || true

nginx -t
systemctl enable --now nginx

echo DONE > /opt/bootstrap-frontend-done
