#!/usr/bin/env bash
# Update the deployed workspace to the latest version of the repository.
# Run on the server:  sudo /opt/idbd/deploy/update.sh
# Users' data in /var/lib/idbd is untouched.
set -euo pipefail
cd /opt/idbd
sudo -u idbd git pull --ff-only
sudo -u idbd env UV_PYTHON_INSTALL_DIR=/opt/idbd/.python uv sync --extra web --frozen
systemctl restart idbd
sleep 2
systemctl --no-pager --lines=5 status idbd
