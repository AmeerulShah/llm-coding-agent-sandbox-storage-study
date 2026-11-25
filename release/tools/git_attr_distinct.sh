#!/bin/bash
# Total vs distinct failed .gitattributes lookups of a git history search (run in a Django sandbox at a task's base commit).
for q in "$@"; do
  strace -f -qq -e trace=openat,newfstatat,statx,access,lstat,stat -o /tmp/h.trace git log -S "$q" --oneline >/dev/null 2>&1
  echo "$q total=$(grep -c '\.gitattributes.*ENOENT' /tmp/h.trace) distinct=$(grep '\.gitattributes.*ENOENT' /tmp/h.trace | sed -E 's/.*"([^"]*\.gitattributes)".*/\1/' | sort -u | wc -l)"
done
