#!/bin/sh
# Flatpak launcher, installed as /app/bin/pepper or /app/bin/salt.
#
# bin/pepper and bin/salt suit a checkout but not the sandbox. They put the
# app in the background, and the sandbox closes as soon as its first process
# exits. They also log to /tmp, which is private to the sandbox. This runs
# the app in the foreground and logs where the host can read it, e.g.
#   tail -n 200 ~/.var/app/com.jacksonv.Pepper/cache/pepper.log
# truncated on each launch, as the checkout's log is.
app=$(basename "$0")
export PYTHONPATH="/app/share/$app"
exec python3 -m "$app.main" "$@" >"$XDG_CACHE_HOME/$app.log" 2>&1
