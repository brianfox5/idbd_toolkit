#!/usr/bin/env bash
# Update the deployed workspace to the latest version of the repository.
#
#   sudo /opt/idbd/deploy/update.sh            # update, restart, verify
#   sudo /opt/idbd/deploy/update.sh --check    # only show what an update would bring
#
# Users' data in /var/lib/idbd is never touched. The script also tells you when an
# update needs a manual step: a changed service file, a changed Apache block, or new
# settings in the template.
set -euo pipefail

APP=${IDBD_APP_DIR:-/opt/idbd}
ENV_FILE=${IDBD_ENV_FILE:-/etc/idbd/idbd.env}
UNIT=${IDBD_UNIT_FILE:-/etc/systemd/system/idbd.service}
RUN_AS=${IDBD_RUN_AS:-idbd}
SYSTEMCTL=${IDBD_SYSTEMCTL:-systemctl}
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
as_app() { if [[ "$(id -un)" == "$RUN_AS" ]]; then "$@"; else sudo -u "$RUN_AS" "$@"; fi; }

cd "$APP"

# 1. Nothing edited by hand in the checkout (server settings belong in $ENV_FILE).
if [[ -n "$(as_app git status --porcelain --untracked-files=no)" ]]; then
    as_app git status --short --untracked-files=no
    fail "Files in $APP were edited on the server, so the update would conflict.
  Server-specific settings belong in $ENV_FILE. To discard the edits:
    sudo -u $RUN_AS git -C $APP checkout -- .
  then run this script again."
fi

# 2. What's new?
as_app git fetch --quiet
OLD=$(as_app git rev-parse HEAD)
NEW=$(as_app git rev-parse '@{u}')
if [[ "$OLD" == "$NEW" ]]; then
    bold "Already up to date ($(as_app git log -1 --format='%h %s'))."
    exit 0
fi
bold "Incoming changes:"
as_app git log --format='  %h %ad  %s' --date=short "$OLD..$NEW"
CHANGED=$(as_app git diff --name-only "$OLD" "$NEW")

notes=()
if grep -qx 'deploy/apache-idbd.conf' <<<"$CHANGED"; then
    notes+=("The Apache block changed. Update the block in your site's HTTPS config to match:
$(as_app git diff "$OLD" "$NEW" -- deploy/apache-idbd.conf | sed 's/^/      /')
    then: sudo apachectl configtest && sudo systemctl reload apache2")
fi
if grep -qx 'deploy/idbd.env.example' <<<"$CHANGED"; then
    notes+=("The settings template changed. New settings have safe defaults; add any you
    want to $ENV_FILE:
$(as_app git diff "$OLD" "$NEW" -- deploy/idbd.env.example | sed 's/^/      /')")
fi
if grep -q '^deploy/migrations/' <<<"$CHANGED"; then
    notes+=("This update includes a data migration in deploy/migrations/ — read its
    instructions before using the site.")
fi

# Does the incoming service definition differ from the installed copy?
if [[ -f "$UNIT" ]] && ! as_app git show "$NEW:deploy/idbd.service" | cmp -s - "$UNIT"; then
    notes+=("The service file in the repository differs from the installed one ($UNIT):
$(as_app git show "$NEW:deploy/idbd.service" | diff -u "$UNIT" - | sed 's/^/      /' || true)
    To install it (after this update): sudo cp $APP/deploy/idbd.service $UNIT \\
        && sudo systemctl daemon-reload && sudo systemctl restart idbd")
fi

if (( CHECK_ONLY )); then
    for n in ${notes[@]+"${notes[@]}"}; do warn "$n"; done
    bold "(--check: nothing was changed.)"
    exit 0
fi

# 3. Update the code and its dependencies.
as_app git pull --ff-only --quiet
if ! as_app env UV_PYTHON_INSTALL_DIR="$APP/.python" uv sync --extra web --locked --quiet; then
    as_app git reset --hard --quiet "$OLD"
    fail "Installing dependencies failed, so the code was put back to the previous version
  and the running site is unchanged. The usual cause is a uv.lock that wasn't committed
  after a dependency change: on your own machine run 'uv lock', commit uv.lock, push,
  and run this script again."
fi

# 4. Restart and check it answers.
"$SYSTEMCTL" restart idbd
PORT=$(sed -n 's/^IDBD_PORT=//p' "$ENV_FILE" 2>/dev/null | tail -1)
PORT=${PORT:-8000}
for _ in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/api/me" >/dev/null 2>&1; then
        bold "✓ Updated to $(as_app git log -1 --format='%h %s') and the app is answering on port $PORT."
        for n in ${notes[@]+"${notes[@]}"}; do warn "$n"; done
        echo "  Ask anyone with the site open to reload the page."
        exit 0
    fi
    sleep 1
done
journalctl -u idbd -n 30 --no-pager 2>/dev/null || true
fail "The app did not come back after the restart (log above). To return to the previous
  version:
    sudo -u $RUN_AS git -C $APP reset --hard $OLD
    sudo -u $RUN_AS env UV_PYTHON_INSTALL_DIR=$APP/.python uv sync --extra web --locked --project $APP
    sudo systemctl restart idbd"
