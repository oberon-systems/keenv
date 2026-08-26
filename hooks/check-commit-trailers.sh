#!/usr/bin/env bash
#
# Reject attribution trailers and generated-by footers in the commit message.
#
# The message format is wyld-cz: a "[type][scope]: subject" line and a
# four-space-indented body, and it ends there. Co-authorship and tool-attribution
# trailers are not part of it, and the ones tools append on their own -- Claude,
# Copilot, Cursor and the rest -- are forbidden outright.
#
# Matching is anchored at the start of a line, so a trailer is only a trailer
# when it sits in trailer position; the same words inside an indented body read
# as prose and pass. Git's own comment lines are stripped first, otherwise the
# commented-out template would trip the check.

set -euo pipefail

msg_file=${1:?usage: check-commit-trailers.sh COMMIT_MSG_FILE}

# Trailer keys that attribute the commit to someone or something other than its
# author. "authored-by" also covers "co-authored-by" and is listed for clarity.
trailers='co-authored-by|authored-by|generated-by|helped-by|assisted-by|written-by'

# The footer form the same tools use when they do not reach for a trailer:
# "Generated with [Claude Code]", "Co-created with Copilot", robot emoji, etc.
footers='(generated|created|written|assisted) (with|by) .*(claude|copilot|cursor|chatgpt|gpt-|openai|anthropic|codex|gemini)'

body=$(git stripspace --strip-comments <"$msg_file")

if offenders=$(printf '%s\n' "$body" |
    grep -inE "^[[:space:]]*(($trailers)[[:space:]]*:|$footers)"); then
    cat >&2 <<EOF
ERROR: the commit message carries an attribution trailer or footer.

$offenders

Co-Authored-By, generated-by and tool-attribution footers are forbidden in
this repository. The message ends with its body; delete the offending lines
and commit again through 'git cz c'.
EOF
    exit 1
fi

exit 0
