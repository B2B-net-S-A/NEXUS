#!/usr/bin/env bash
# wznawiaj po restarcie bazy/Qdranta, aż powstanie wynik
cd /root/nexus-search-research/s30
for i in $(seq 1 8); do
  ./run.sh /research/critical_full.py >> critical_full.log 2>&1
  test -f out_critical_full.json && break
  sleep 90
done
