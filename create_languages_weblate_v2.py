#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weblate 언어 일괄 생성/갱신 스크립트 (이름=Zanata, 복수형=입력 JSON 우선)
- 입력1: code -> plural-forms 맵(JSON)
- 입력2: Zanata locales JSON (배열)

동작:
  * 언어가 없으면 생성(코드/이름/복수형 공식)
  * 언어가 있으면 name/plural(number,formula)만 diff 적용(PATCH)
우선순위:
  * plural: 입력1(사용자 json) > Zanata pluralForms > 없으면 스킵
  * name: Zanata displayName 우선, 없으면 nativeName, 없으면 code

기타:
  * 코드 정규화: '-' → '_' 강제 (예: tr-TR → tr_TR)
  * RTL 후보 언어는 direction=rtl 로 생성(업데이트에선 direction은 변경하지 않음)
  * 기본 드라이런, --apply 로 실제 반영
"""

import os, sys, json, argparse, urllib.parse, re
import requests
from typing import Dict, Any, Tuple, Optional

# ---- 코드 정규화 -------------------------------------------------------------
def canon(code: str) -> str:
    """코드를 Weblate 표준으로 정규화: '-' → '_', 맨 앞만 소문자"""
    if not code:
        return ""
    normalized = code.strip().replace("-", "_")
    return normalized[0].lower() + normalized[1:] if normalized else normalized

# ---- plural 파서 -------------------------------------------------------------
def parse_plural_forms(pf: str) -> Optional[Tuple[int, str]]:
    """'nplurals=2; plural=(n != 1);' → (2, 'n != 1')"""
    if not pf:
        return None
    s = pf.strip().rstrip(";")
    m_num = re.search(r"nplurals\s*=\s*(\d+)", s, re.IGNORECASE)
    m_for = re.search(r"plural\s*=\s*([^;]+)", s, re.IGNORECASE)
    if not (m_num and m_for):
        return None
    number = int(m_num.group(1))
    formula = m_for.group(1).strip()
    if formula.startswith("(") and formula.endswith(")"):
        formula = formula[1:-1].strip()
    formula = formula.rstrip(";").strip()
    if not formula or formula.count("(") != formula.count(")"):
        return None
    return number, formula

# ---- 입력 로더 ---------------------------------------------------------------
def load_plural_map(path: str) -> Dict[str, str]:
    """입력 plural JSON → {canon_code: 'nplurals=..; plural=..'}"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: Dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str):
                out[canon(k)] = v.strip()
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if "code" in item and ("plural" in item or "plural_equation" in item):
                    pf = item.get("plural") or item.get("plural_equation")
                    if isinstance(pf, str):
                        out[canon(item["code"])] = pf.strip()
                else:
                    for k, v in item.items():
                        if isinstance(v, str):
                            out[canon(k)] = v.strip()
    else:
        raise ValueError("지원하지 않는 JSON 형식(Plural Map)")
    return out

def load_zanata_locales(path: str) -> Dict[str, Dict[str, Any]]:
    """Zanata JSON(배열) → {canon_code: {"name": str, "rtl": bool, "pluralForms": str}}"""
    with open(path, "r", encoding="utf-8") as f:
        arr = json.load(f)
    if not isinstance(arr, list):
        raise ValueError("Zanata JSON은 배열이어야 합니다.")
    out: Dict[str, Dict[str, Any]] = {}
    rtl_langs = {"ar", "fa", "he", "ur", "ug", "dv", "ps", "ku_Arab"}
    for it in arr:
        if not isinstance(it, dict):
            continue
        raw = it.get("localeId") or it.get("id") or ""
        code = canon(raw)
        if not code:
            continue
        disp = (it.get("displayName") or "").strip()
        native = (it.get("nativeName") or "").strip()
        name = disp or native or code
        pf = (it.get("pluralForms") or "").strip()
        base = code.split("_", 1)[0]
        rtl = base in rtl_langs
        out[code] = {"name": name, "rtl": rtl, "pluralForms": pf}
    return out

# ---- Weblate API -------------------------------------------------------------
class WeblateClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self.timeout = timeout

    def _lang_url(self, code: str) -> str:
        return f"{self.base}/api/languages/{urllib.parse.quote(code, safe='')}/"

    def get_language(self, code: str) -> Tuple[int, Dict[str, Any]]:
        r = self.session.get(self._lang_url(code), timeout=self.timeout)
        if r.status_code == 200:
            return 200, r.json()
        return r.status_code, {}

    def create_language(self, code: str, name: str, plural_number: int, plural_formula: str,
                        direction: Optional[str]) -> Tuple[int, str]:
        payload = {
            "code": code,
            "name": name or code,
            "plural": {"number": plural_number, "formula": plural_formula},
        }
        if direction in ("ltr", "rtl"):
            payload["direction"] = direction
        r = self.session.post(f"{self.base}/api/languages/", json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
            return r.status_code, ""
        except requests.exceptions.HTTPError:
            return r.status_code, r.text

    def update_language(self, code: str, name: Optional[str],
                        plural_number: Optional[int], plural_formula: Optional[str]) -> Tuple[int, str]:
        payload: Dict[str, Any] = {}
        if name:
            payload["name"] = name
        if plural_number is not None and plural_formula:
            payload["plural"] = {"number": plural_number, "formula": plural_formula}
        if not payload:
            return 200, ""  # 변경사항 없음
        r = self.session.patch(self._lang_url(code), json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
            return r.status_code, ""
        except requests.exceptions.HTTPError:
            return r.status_code, r.text

# ---- 메인 --------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Weblate 언어 일괄 생성/갱신")
    p.add_argument("-i", "--input", required=True, help="Plural-Forms 맵 JSON")
    p.add_argument("-z", "--zanata", required=True, help="Zanata locales JSON")
    p.add_argument("--apply", action="store_true", help="실제로 Weblate에 반영")
    args = p.parse_args()

    url = os.getenv("WEBLATE_URL", "")
    token = os.getenv("WEBLATE_API_KEY", "")
    if not token:
        print("ERROR: WEBLATE_API_KEY 환경변수를 지정하세요.", file=sys.stderr)
        sys.exit(1)

    plural_map = load_plural_map(args.input)
    zanata_map = load_zanata_locales(args.zanata)
    print(f"=== 계획 ===\n- plural entries: {len(plural_map)}\n- zanata entries: {len(zanata_map)}")
    print(f"- 모드: {'실제 반영' if args.apply else '드라이런'}\n")

    cli = WeblateClient(url, token)

    created = updated = skipped = failed = 0
    failures = []

    for code, zinfo in zanata_map.items():
        name = (zinfo.get("name") or code).strip()
        direction = "rtl" if zinfo.get("rtl") else None
        pf_str = plural_map.get(code)
        if not pf_str:
            base = code.split("_", 1)[0]
            pf_base = plural_map.get(base)
            if pf_base:
                print(f"  · {code}: plural을 기본언어 {base}에서 상속")
                pf_str = pf_base

        parsed = parse_plural_forms(pf_str or "")
        if not parsed:
            print(f"- {code}: plural 미확정(입력 JSON에 {code}도 {code.split('_',1)[0]}도 없음) → 스킵")
            skipped += 1
            continue
        num, formula = parsed

        status, data = cli.get_language(code)
        if status == 200:
            cur = data.get("plural") or {}
            cur_num = cur.get("number")
            cur_for = (cur.get("formula") or "").strip()
            cur_name = (data.get("name") or "").strip()
            need_name = (name and name != cur_name)
            need_plural = not (cur_num == num and cur_for == formula)
            if not (need_name or need_plural):
                print(f"- {code}: 동일 → 스킵")
                skipped += 1
                continue
            print(f"- {code}: 업데이트 name={cur_name!r}->{name!r} plural={cur_num}/{cur_for}->{num}/{formula}")
            if args.apply:
                s, body = cli.update_language(code, name if need_name else None,
                                              num if need_plural else None,
                                              formula if need_plural else None)
                if s in (200, 202): updated += 1
                else:
                    failed += 1; failures.append((code, s, body[:300]))
            else: updated += 1
        elif status == 404:
            print(f"- {code}: 생성 name={name!r} plural=({num},{formula}) {direction or ''}")
            if args.apply:
                s, body = cli.create_language(code, name, num, formula, direction)
                if s in (200, 201): created += 1
                else:
                    failed += 1; failures.append((code, s, body[:300]))
            else: created += 1
        else:
            print(f"- {code}: 조회 실패 HTTP {status}")
            failed += 1; failures.append((code, status, "lookup_failed"))

    print(f"\n=== 결과 ===\n생성:{created} 갱신:{updated} 스킵:{skipped} 실패:{failed}")
    if failures:
        print("\n실패 상세:")
        for code, s, body in failures[:30]:
            print(f"  - {code}: HTTP {s} body={body}")

if __name__ == "__main__":
    main()