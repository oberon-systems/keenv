#!/usr/bin/env bash
#
# Refuse the commit unless this clone carries its own author identity.
#
# Without a repository-local user.name and user.email git falls back to the
# global config, or to whatever the surrounding environment happens to have set
# up, and the commit lands under that name instead of under whoever owns this
# checkout. On a machine where an agent or a CI runner shares the account, the
# global identity is exactly the one that must not end up in this history.

set -euo pipefail

name=$(git config --local user.name || true)
email=$(git config --local user.email || true)

if [ -n "$name" ] && [ -n "$email" ]; then
    exit 0
fi

cat >&2 <<'EOF'
ERROR: this clone has no local git author.

Commits made under the global or default environment identity are not
accepted here. Set the author on the repository itself:

    git config --local user.name "Your Name"
    git config --local user.email "your.email@example.com"
EOF

exit 1
