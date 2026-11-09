#!/bin/sh
cd "$(dirname "$0")" || exit 1

sudo docker-compose --env-file .env -f deploy/docker-compose.yml up -d