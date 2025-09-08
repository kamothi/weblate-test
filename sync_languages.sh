#!/usr/bin/env bash
set -euo pipefail

# ================== 설정 ==================
# Weblate 접속 정보 (필수 → 직접 넣으세요)
export WEBLATE_URL=""
export WEBLATE_API_KEY=""

# Plural forms JSON (예: zanata-plural.json)
PLURAL_JSON="./zanata-plural.json"

# Zanata locales JSON (예: zanata.json)
ZANATA_JSON="./zanata.json"

# Python 실행 환경 (venv 쓰고 있으면 경로 맞추세요)
PYTHON_BIN="python"
# =========================================

echo "=== Weblate 언어 동기화 시작 ==="

# 1) 전체 언어 삭제 (en, ko 제외)
echo
echo "1) 기존 언어 삭제"
$PYTHON_BIN delete_languages.py --apply

# 2) zanata-language check
echo
echo "2) zanata 언어들 가져오기"
curl -s -w "\n%{http_code}\n" \
  -H "Accept: application/json" \
  -H "X-Auth-User: " \
  -H "X-Auth-Token: " \
  -o /directory/zanata.json \
  "https://translate.openstack.org/rest/locales/ui"

# 3) zanata 기반 언어 생성/갱신
echo
echo "3) Zanata 기반 언어 생성/갱신…"
$PYTHON_BIN create_language_weblate.py \
  -i "$PLURAL_JSON" \
  -z "$ZANATA_JSON" \
  --apply

echo
echo "=== 완료 ==="
