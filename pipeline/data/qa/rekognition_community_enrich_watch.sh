#!/bin/bash
set -euo pipefail
cd /Users/juanpabloduque/Documents/what-fear-looks-like/pipeline
export AWS_PROFILE=sandbox AWS_DEFAULT_REGION=us-east-1 AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY || true
PIDF=data/qa/rekognition_community_enrich.pid
LOG=data/qa/rekognition_community_enrich.log
KEEP=87189
while kill -0 "$KEEP" 2>/dev/null; do sleep 30; done
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) keep dead; checking remaining" >> "$LOG"
if /bin/ps -ax -o command= | /usr/bin/grep -F 'rekognition_enrich.py --ids-file' | /usr/bin/grep -v grep >/dev/null; then
  echo "another enrich running; watcher exit" >> "$LOG"
  exit 0
fi
/Users/juanpabloduque/miniforge3/bin/python3 - <<'PY'
from pathlib import Path
import csv
DATA=Path('data')
rek=set(int(float(r['id'])) for r in csv.DictReader(open(DATA/'rekognition.csv')))
miss=sorted(int(p.stem) for p in (DATA/'posters').glob('*.jpg') if p.stem.isdigit() and int(p.stem) not in rek)
(DATA/'qa'/'rekognition_missing_ids.txt').write_text(chr(10).join(map(str,miss))+chr(10))
print('resume_missing', len(miss))
PY
nohup /Users/juanpabloduque/miniforge3/bin/python3 -u rekognition_enrich.py   --ids-file data/qa/rekognition_missing_ids.txt   --workers 10 --min-interval 0.04 --save-every 25   --sidecar data/qa/rekognition_community_enrich.csv --merge-main   >> "$LOG" 2>&1 &
echo $! > "$PIDF"
echo "watcher launched $(cat $PIDF)" >> "$LOG"
