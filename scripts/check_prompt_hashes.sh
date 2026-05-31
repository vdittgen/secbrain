#!/usr/bin/env bash
# Verify frozen prompt template hashes + golden fixtures.
#
# Runs the parametrized tests in
# tests/unit/models/prompts/test_golden_prompts.py — failure means
# either a `.txt` file in src/models/prompts/ was edited (silent
# prompt-cache buster) or a render fixture drifted.
#
# Suggested pre-commit hook:
#
#     echo '#!/usr/bin/env bash' >> .git/hooks/pre-commit
#     echo 'scripts/check_prompt_hashes.sh' >> .git/hooks/pre-commit
#     chmod +x .git/hooks/pre-commit
#
# sensitivity_tier: 1

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [ ! -x .venv/bin/python ]; then
    echo "check_prompt_hashes: .venv/bin/python not found; activate your venv first" >&2
    exit 2
fi

.venv/bin/python -m pytest \
    tests/unit/models/prompts/test_golden_prompts.py -q
