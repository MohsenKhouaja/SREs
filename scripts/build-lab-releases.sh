#!/usr/bin/env sh
set -eu

docker build --build-arg RELEASE=v1 -t sres-sample-api:v1 sample-apps
docker build --build-arg RELEASE=v2 -t sres-sample-api:v2 sample-apps
