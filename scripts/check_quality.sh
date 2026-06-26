#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/check_quality.sh [--with-pytest | --pytest <args...>] [--help]

Runs the focused repository quality gate:
  - ruff check apps services libs scripts --select B904,SIM105,SIM117,F401,F841
  - bandit -q -r apps services libs scripts -x tests -lll
  - npm audit --audit-level=moderate in apps/web
  - npm run build in apps/web

Note: apps/web currently overrides PostCSS to the root fixed version so Next's
nested dependency also satisfies npm audit.

Pytest is intentionally opt-in because the full suite is slower than the
default lint/security/frontend gate.

Options:
  --with-pytest   Also run pytest -q after backend lint/security checks.
  --pytest        Run pytest with the remaining arguments.
  -h, --help      Show this help text.

Examples:
  bash scripts/check_quality.sh
  bash scripts/check_quality.sh --with-pytest
  bash scripts/check_quality.sh --pytest tests/test_run_persistence.py -q
EOF
}

run() {
  printf '\n+'
  printf ' %q' "$@"
  printf '\n'
  "$@"
}

RUN_PYTEST=0
PYTEST_ARGS=(-q)

while (($#)); do
  case "$1" in
    --with-pytest)
      RUN_PYTEST=1
      shift
      ;;
    --pytest)
      RUN_PYTEST=1
      shift
      if (($#)); then
        PYTEST_ARGS=("$@")
      fi
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

cd "$REPO_ROOT"
run ruff check apps services libs scripts --select B904,SIM105,SIM117,F401,F841
run bandit -q -r apps services libs scripts -x tests -lll

if ((RUN_PYTEST)); then
  run pytest "${PYTEST_ARGS[@]}"
else
  echo
  echo "Skipping pytest by default; pass --with-pytest or --pytest <args...> to include it."
fi

cd "$REPO_ROOT/apps/web"
run npm audit --audit-level=moderate
run npm run build
