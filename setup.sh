#!/usr/bin/env bash
# One-command setup for KasiBiz on macOS and Linux.
#
#     bash setup.sh
#
# Windows users: follow docs/LOCAL_SETUP_AND_RUN_GUIDE.md instead. PowerShell
# activation works differently and is better done step by step.
#
# This script is safe to run more than once. It will not overwrite an existing
# .env, and it will not wipe a database that already has data in it.

set -euo pipefail

cd "$(dirname "$0")"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    %s\033[0m\n' "$1"; }

# ----------------------------------------------------------------- python
say "Looking for Python 3.12"
PYTHON=""
for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
        if [ "$version" = "3.12" ]; then PYTHON="$candidate"; break; fi
        [ -z "$PYTHON" ] && PYTHON="$candidate"
    fi
done

if [ -z "$PYTHON" ]; then
    echo "No Python found. Install Python 3.12 and run this again."
    exit 1
fi

echo "    using $PYTHON ($($PYTHON --version))"
if [ "$($PYTHON -c 'import sys; print("%d.%d" % sys.version_info[:2])')" != "3.12" ]; then
    warn "This is not Python 3.12. Some pinned packages have no wheels for other"
    warn "versions and the install may fail. Continuing anyway."
fi

# ------------------------------------------------------------ environment
say "Creating the virtual environment (.venv)"
if [ -d .venv ]; then
    echo "    .venv already exists, reusing it"
else
    "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

say "Installing dependencies"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
echo "    done"

# -------------------------------------------------------------------- env
say "Setting up .env"
if [ -f .env ]; then
    echo "    .env already exists, leaving it alone"
else
    cp .env.example .env
    echo "    created .env from .env.example"
    warn "Add your OPENAI_API_KEY to .env if you want AI wording."
    warn "KasiBiz runs fine without it."
fi

# --------------------------------------------------------------- the data
say "Building the knowledge base"
python scripts/rag_ingest.py --local

say "Loading the demonstration shop"
python scripts/seed_demo.py

# -------------------------------------------------------------- check it
say "Running the health check"
python scripts/health_check.py

cat <<'DONE'

------------------------------------------------------------------
Ready.

  source .venv/bin/activate
  streamlit run streamlit_app/app.py

Then open http://localhost:8501

Other things you can run:
  python scripts/demo_journey.py --pause   the recorded walkthrough
  python scripts/kasibiz.py --chat         the terminal version
  python -m pytest tests/ -q               the test suite
------------------------------------------------------------------
DONE
