#!/bin/bash -xe
# Usage:
#   ./weblate_update.sh <PROJECT> <JOBNAME> <BRANCHNAME> <HORIZON_DIR>
#
# Required env:
#   WEBLATE_API_URL    (e.g. https://weblate.example.com)
#   WEBLATE_API_TOKEN  (Weblate personal token)
#   WEBLATE_SRC_LANG   (source language slug, e.g. en)
# Optional env:
#   WEBLATE_PROJECT    (defaults to $PROJECT)
#   WEBLATE_COMPONENT  (defaults to $PROJECT-$WEBLATE_BRANCH)
#   WEBLATE_INSECURE=1 (optional: curl -k)

PROJECT=$1
JOBNAME=$2
BRANCHNAME=$3
HORIZON_DIR=$4

# WEBLATE_BRANCH: slug용 정규화( '/' -> '-' )
WEBLATE_BRANCH=${BRANCHNAME//\//-}

SCRIPTSDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTSDIR/common_translation_update.sh"

# checks weblate env
: "${WEBLATE_API_URL:?Set WEBLATE_API_URL}"
: "${WEBLATE_API_TOKEN:?Set WEBLATE_API_TOKEN}"
: "${WEBLATE_SRC_LANG:?Set WEBLATE_SRC_LANG}"
WEBLATE_PROJECT="${WEBLATE_PROJECT:-$PROJECT}"
WEBLATE_COMPONENT="${WEBLATE_COMPONENT:-$PROJECT-$WEBLATE_BRANCH}"
AUTH_HEADER="Authorization: Token ${WEBLATE_API_TOKEN}"


# --- weblate에서 컴포넌트 존재 유무 확인 ---
weblate_component_check_or_skip() {
  local url="${WEBLATE_API_URL%/}/api/components/${WEBLATE_PROJECT}/${WEBLATE_COMPONENT}/"
  # 응답 바디/코드를 분리해 받기
  local tmp resp_code
  tmp="$(mktemp)"
  resp_code=$(curl "${CURL_OPTS[@]}" -w "%{http_code}" -H "$AUTH_HEADER" \
               "$url" -o "$tmp" || true)

  # 200이 아닌 즉, 컴포넌트가 없다면 스킵(exit 0)
  if [[ "$resp_code" != "200" ]]; then
    echo "[weblate] component unavailable (HTTP $resp_code) -> skip job"
    ERROR_ABORT=0
    rm -f "$tmp"
    exit 0
  fi

  # lock 유무 확인
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

# Weblate에 컴포넌트가 없거나 lock이 걸려 있을 경우 스킵
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

# === Weblate API upload (no repo commit/push; pure upload) ===
copy_pot "$ALL_MODULES"
mkdir -p translation-source
mv .translation-source translation-source

# POT 업로드(소스 언어로)
for pot in translation-source/**/*.pot translation-source/*.pot; do
  [ -f "$pot" ] || continue
  curl "${CURL_OPTS[@]}" -X POST \
    -H "$AUTH_HEADER" \
    -F "file=@${pot}" \
    -F "method=upload" \
    "${WEBLATE_API_URL%/}/api/translations/${WEBLATE_PROJECT}/${WEBLATE_COMPONENT}/${WEBLATE_SRC_LANG}/file/" >/dev/null
done

# Tell finish function that everything is fine.
ERROR_ABORT=0
