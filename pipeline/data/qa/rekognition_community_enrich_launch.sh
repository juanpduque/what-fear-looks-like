#!/bin/bash
cd /Users/juanpabloduque/Documents/what-fear-looks-like/pipeline || exit 1
export AWS_PROFILE=sandbox
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
  no_proxy NO_PROXY
mkdir -p data/qa
: > data/qa/rekognition_community_enrich.log
nohup /Users/juanpabloduque/miniforge3/bin/python3 -u rekognition_enrich.py \
  --ids-file data/qa/rekognition_missing_ids.txt \
  --workers 10 \
  --min-interval 0.04 \
  --save-every 25 \
  --sidecar data/qa/rekognition_community_enrich.csv \
  --merge-main \
  > data/qa/rekognition_community_enrich.log 2>&1 &
echo $! > data/qa/rekognition_community_enrich.pid
echo "LAUNCHED:$(cat data/qa/rekognition_community_enrich.pid)"
sleep 2
head -5 data/qa/rekognition_community_enrich.log
