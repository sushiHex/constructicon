#!/bin/bash
# Run one apt-get command within a wall-clock bound, or refuse with a named reason.
#
# apt's own per-connection timeouts do not bound a whole command: a mirror
# fallback once stalled `apt-get update` silently until the 30-minute job
# budget expired (#291). The bound is total time for one command, including
# apt's download methods. Exit status: 0 on success, 124 when the bound
# expired, otherwise apt-get's own failure status. Nothing is retried.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "bounded-apt-usage: bounded_apt.sh SECONDS APT_GET_ARGUMENT..." >&2
  exit 2
fi
bound=$1
shift
case "$bound" in
  '' | 0 | *[!0-9]*)
    echo "bounded-apt-usage: SECONDS must be a positive integer" >&2
    exit 2
    ;;
esac

status=0
# Without --foreground, timeout signals apt-get's whole process group, so the
# download methods it started stop too. A command that ignores TERM is killed.
timeout --kill-after=10 "$bound" apt-get "$@" || status=$?
case "$status" in
  0)
    exit 0
    ;;
  124 | 137)
    echo "::error title=APT provisioning bound::apt-get $* did not finish within ${bound}s"
    echo "apt-provisioning-timeout: apt-get $* exceeded ${bound}s" >&2
    exit 124
    ;;
  *)
    echo "::error title=APT provisioning failed::apt-get $* exited ${status}"
    echo "apt-provisioning-failed: apt-get $* exited ${status}" >&2
    exit "$status"
    ;;
esac
