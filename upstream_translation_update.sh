#!/bin/bash -xe
# Usage:
#   ./weblate_update.sh <PROJECT> <JOBNAME> <BRANCHNAME> <HORIZON_DIR>
#
# Required env:
#   WEBLATE_URL    (e.g. https://weblate.example.com)
#   WEBLATE_TOKEN  (Weblate personal token)
#   WEBLATE_SRC_LANG   (source language slug, e.g. en)
# Optional env:
#   WEBLATE_PROJECT    (defaults to $PROJECT)
#   WEBLATE_COMPONENT  (defaults to $PROJECT-$WEBLATE_BRANCH)
#   WEBLATE_INSECURE=1 (optional: curl -k)

PROJECT=$1
JOBNAME=$2
BRANCHNAME=$3
HORIZON_DIR=$4

# WEBLATE_BRANCH: normalize for slug ( '/' -> '-' )
WEBLATE_BRANCH=${BRANCHNAME//\//-}

SCRIPTSDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTSDIR/common_translation_update.sh"

# checks weblate env
: "${WEBLATE_URL:?Set WEBLATE_URL}"
: "${WEBLATE_TOKEN:?Set WEBLATE_TOKEN}"
: "${WEBLATE_SRC_LANG:?Set WEBLATE_SRC_LANG}"
WEBLATE_PROJECT="${WEBLATE_PROJECT:-$PROJECT}"
WEBLATE_COMPONENT="${WEBLATE_COMPONENT:-$PROJECT-$WEBLATE_BRANCH}"
AUTH_HEADER="Authorization: Token ${WEBLATE_TOKEN}"


# --- Check if the component exists in Weblate ---
weblate_component_check_or_skip() {
  local url="${WEBLATE_URL%/}/api/components/${WEBLATE_PROJECT}/${WEBLATE_COMPONENT}/"
  # Separate response body/code
  local tmp resp_code
  tmp="$(mktemp)"
  resp_code=$(curl "${CURL_OPTS[@]}" -w "%{http_code}" -H "$AUTH_HEADER" \
               "$url" -o "$tmp" || true)

  # If response is not 200 (component does not exist) → skip (exit 0)
  if [[ "$resp_code" != "200" ]]; then
    echo "[weblate] component unavailable (HTTP $resp_code) -> skip job"
    ERROR_ABORT=0
    rm -f "$tmp"
    exit 0
  fi

  # Check lock status
  if command -v jq >/dev/null 2>&1; then
    if jq -e '.locked==true or .is_locked==true' "$tmp" >/dev/null; then
      echo "[weblate] component locked -> skip job"
      ERROR_ABORT=0
      rm -f "$tmp"
      exit 0
    fi
  else
    if grep -qE '"(locked|is_locked)"[[:space:]]*:[[:space:]]*true' "$tmp"; then
      echo "[weblate] component locked -> skip job"
      ERROR_ABORT=0
      rm -f "$tmp"
      exit 0
    fi
  fi

  rm -f "$tmp"
}

init_branch "$BRANCHNAME"

# List of all modules to copy POT files from
ALL_MODULES=""

# Setup venv - needed for all projects for our tools
setup_venv

# Skip if component does not exist or is locked in Weblate
weblate_component_check_or_skip

setup_git

# Project setup and updating POT files.
case "$PROJECT" in
  api-site|openstack-manuals|security-doc)
    init_manuals "$PROJECT"
    setup_manuals "$PROJECT" "$WEBLATE_BRANCH"
    case "$PROJECT" in
      api-site)      ALL_MODULES="api-quick-start firstapp" ;;
      security-doc)  ALL_MODULES="security-guide" ;;
      *)             ALL_MODULES="doc" ;;
    esac
    if [[ "$WEBLATE_BRANCH" == "master" && -f releasenotes/source/conf.py ]]; then
      extract_messages_releasenotes
      ALL_MODULES="releasenotes $ALL_MODULES"
    fi
    ;;
  training-guides)
    setup_training_guides "$WEBLATE_BRANCH"
    ALL_MODULES="doc"
    ;;
  i18n)
    setup_i18n "$WEBLATE_BRANCH"
    ALL_MODULES="doc"
    ;;
  tripleo-ui)
    setup_reactjs_project "$PROJECT" "$WEBLATE_BRANCH"
    ALL_MODULES="i18n"
    ;;
  *)
    setup_project "$PROJECT" "$WEBLATE_BRANCH"

    module_names=$(get_modulename "$PROJECT" python)
    if [ -n "$module_names" ]; then
      if [[ "$WEBLATE_BRANCH" == "master" && -f releasenotes/source/conf.py ]]; then
        extract_messages_releasenotes
        ALL_MODULES="releasenotes $ALL_MODULES"
      fi
      for modulename in $module_names; do
        extract_messages_python "$modulename"
        ALL_MODULES="$modulename $ALL_MODULES"
      done
    fi

    module_names=$(get_modulename "$PROJECT" django)
    if [ -n "$module_names" ]; then
      install_horizon
      if [[ "$WEBLATE_BRANCH" == "master" && -f releasenotes/source/conf.py ]]; then
        extract_messages_releasenotes
        ALL_MODULES="releasenotes $ALL_MODULES"
      fi
      for modulename in $module_names; do
        extract_messages_django "$modulename"
        ALL_MODULES="$modulename $ALL_MODULES"
      done
    fi

    if [[ -f doc/source/conf.py ]]; then
      if [[ ${DOC_TARGETS[*]} =~ "$PROJECT" ]]; then
        extract_messages_doc
        ALL_MODULES="doc $ALL_MODULES"
      fi
    fi
    ;;
esac

# === Weblate API upload ===
copy_pot "$ALL_MODULES"
mkdir -p translation-source
mv .translation-source translation-source

# --- require msgen (GNU gettext) ---
if ! command -v msgen >/dev/null 2>&1; then
  echo "[error] 'msgen' not found. Please install GNU gettext (e.g., apt-get install gettext)."
  exit 1
fi

# POT upload
for pot in translation-source/*.pot; do
  [ -f "$pot" ] || continue
  
  msgen "$pot" -o "$pot"

  curl ${CURL_OPTS:+${CURL_OPTS[@]}} -X POST \
    -H "$AUTH_HEADER" \
    -H "Accept: application/json" \
    -F "file=@${pot}" \
    -F "method=replace" \
    "${WEBLATE_URL%/}/api/translations/${WEBLATE_PROJECT}/${WEBLATE_COMPONENT}/${WEBLATE_SRC_LANG}/file/" >/dev/null
done

# Tell finish function that everything is fine.
ERROR_ABORT=0
