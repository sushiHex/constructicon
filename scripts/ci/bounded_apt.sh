#!/bin/bash
# Run one apt-get command within a wall-clock bound, or refuse with a named reason.
#
# apt's own per-connection timeouts do not bound a whole command: a mirror
# fallback once stalled `apt-get update` silently until the 30-minute job
# budget expired (#291). The bound is total time for one command, including
# apt's download methods. Exit status: 0 on success; 124 when the bound expired
# and TERM ended the command; 137 when the command was killed, which is either
# the escalation after an ignored TERM or a SIGKILL from elsewhere, so its cause
# is not asserted; otherwise apt-get's own failure status. Nothing is retried.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "bounded-apt-usage: bounded_apt.sh SECONDS APT_GET_ARGUMENT..." >&2
  exit 2
fi
bound=$1
shift
# Canonical digits only: timeout reads 0 (and so 00) as no bound at all.
case "$bound" in
  '' | 0* | *[!0-9]*)
    echo "bounded-apt-usage: SECONDS must be a positive integer without leading zeros" >&2
    exit 2
    ;;
esac

status=0
# Without --foreground, timeout leads its own process group and sends TERM to
# the whole group, so the download methods apt-get started stop too. Its later
# KILL reaches only apt-get, so after any bound or kill the group is killed
# here as well: a descendant that ignored TERM must not hold the step open.
timeout --kill-after=10 "$bound" apt-get "$@" &
group=$!
wait "$group" || status=$?
if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
  kill -KILL -- "-$group" 2> /dev/null || true
fi
case "$status" in
  0)
    exit 0
    ;;
  124)
    echo "::error title=APT provisioning bound::apt-get $* did not finish within ${bound}s"
    echo "apt-provisioning-timeout: apt-get $* exceeded ${bound}s" >&2
    exit 124
    ;;
  137)
    echo "::error title=APT provisioning killed::apt-get $* was killed; cause not established"
    echo "apt-provisioning-killed: apt-get $* was killed (bound ${bound}s); cause not established" >&2
    exit 137
    ;;
  *)
    echo "::error title=APT provisioning failed::apt-get $* exited ${status}"
    echo "apt-provisioning-failed: apt-get $* exited ${status}" >&2
    exit "$status"
    ;;
esac
