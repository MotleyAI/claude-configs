#!/bin/bash
# Retry a flaky network command: retry.sh [-n MAX] [-d SECONDS] -- cmd args...
max=4; delay=5
while [ $# -gt 0 ]; do
  case "$1" in
    -n) max="$2"; shift 2 ;;
    -d) delay="$2"; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: retry.sh [-n MAX] [-d SECONDS] -- cmd args..." >&2; exit 2; }
attempt=1
while true; do
  "$@" && exit 0
  rc=$?
  [ "$attempt" -ge "$max" ] && { echo "retry.sh: giving up after $attempt attempts (rc=$rc)" >&2; exit "$rc"; }
  echo "retry.sh: attempt $attempt failed (rc=$rc); retrying in ${delay}s" >&2
  sleep "$delay"; attempt=$((attempt + 1))
done
