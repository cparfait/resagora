#!/bin/sh
# Démarrage sans root : base de signatures initiale si absente, freshclam en tâche de fond, clamd au premier plan.
set -eu
CONF=/etc/clamav-ville
if [ ! -f /var/lib/clamav/main.cvd ] && [ ! -f /var/lib/clamav/main.cld ]; then
    freshclam --config-file="$CONF/freshclam.conf" --foreground=true
fi
freshclam --config-file="$CONF/freshclam.conf" --daemon --foreground=false
exec clamd --config-file="$CONF/clamd.conf"
