#!/bin/bash
set -e

echo "=== Step 1: Start nginx with init config for ACME challenge ==="
cp nginx-init.conf /tmp/nginx-init.conf
sudo docker compose down || true

# Temporarily use the init config
sudo docker compose run -d --name nginx-init \
  -p 80:80 \
  -v /tmp/nginx-init.conf:/etc/nginx/conf.d/default.conf:ro \
  -v onlycat-tool_certbot_www:/var/www/certbot:ro \
  nginx nginx -g 'daemon off;'

sleep 2

echo "=== Step 2: Request certificates ==="
sudo docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d oni.slederer.com -d slederer.com -d www.slederer.com \
  --email stefan.a.lederer@gmail.com \
  --agree-tos --no-eff-email

echo "=== Step 3: Stop temp nginx, start full stack ==="
sudo docker stop nginx-init && sudo docker rm nginx-init || true
sudo docker compose up -d --build

echo "=== Done! HTTPS is live ==="
