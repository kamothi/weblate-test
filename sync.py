#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weblate 보수적 동기화:
- 삭제: zanata.json 기준으로 매칭(코드/alias)에 실패한 Weblate 언어만 삭제
- 유지/갱신: 코드 일치 또는 alias 일치한 언어는 name/plural만 갱신
- 생성: zanata에만 있고 Weblate에 (코드/alias) 모두 없는 언어는 생성
- plural은 zanata-plural.json 우선, 없으면 base 코드 폴백(ko_KR -> ko)
기본 드라이런, --apply로 실제 반영
"""

import os, sys, json, argparse, urllib.parse, re
import requests
from typing import Dict, Any, Tuple, Optional, Set

# ---------- 정규화 ----------
def canon(code: str) -> str:
    """'-'→'_' 변환 + 맨 앞 글자만 소문자 (tr-TR→tr_TR, Ro→ro). 나머지 대문자 보존."""
    if not code:
        return ""
    t = code.strip().replace("-", "_")
    return (t[0].lower() + t[1:]) if t else t

# ---------- plural 파서 ----------
def parse_plural_forms(pf: str) -> Optional[Tuple[int, str]]:
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

# ---------- 입력 로더 ----------
def load_plural_map(path: str) -> Dict[str, str]:
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
    with open(path, "r", encoding="utf-8") as f:
        arr = json.load(f)
    if not isinstance(arr, list):
        raise ValueError("Zanata JSON은 배열이어야 합니다.")
    out: Dict[str, Dict[str, Any]] = {}
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
        out[code] = {"name": name}
    return out

# ---------- Weblate API ----------
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

    def list_languages(self, page_size: int = 100) -> Dict[str, Dict[str, Any]]:
        """모든 언어 {code: obj} 로 반환"""
        url = f"{self.base}/api/languages/?page_size={page_size}"
        out: Dict[str, Dict[str, Any]] = {}
        while url:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                out[item["code"]] = item
            url = data.get("next")
        return out

    def create_language(self, code: str, name: str, number: int, formula: str) -> Tuple[int, str]:
        payload = {"code": code, "name": name, "plural": {"number": number, "formula": formula}}
        r = self.session.post(f"{self.base}/api/languages/", json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
            return r.status_code, ""
        except requests.exceptions.HTTPError:
            return r.status_code, r.text

    def patch_language(self, code: str, name: Optional[str], number: Optional[int], formula: Optional[str]) -> Tuple[int, str]:
        payload: Dict[str, Any] = {}
        if name:
            payload["name"] = name
        if number is not None and formula:
            payload["plural"] = {"number": number, "formula": formula}
        if not payload:
            return 200, ""
        r = self.session.patch(self._lang_url(code), json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
            return r.status_code, ""
        except requests.exceptions.HTTPError:
            return r.status_code, r.text

    def delete_language(self, code: str) -> Tuple[int, str]:
        r = self.session.delete(self._lang_url(code), timeout=self.timeout)
        if r.status_code in (200, 202, 204):
            return r.status_code, ""
        return r.status_code, r.text

# ---------- 유틸 ----------
def pick_plural(plural_map: Dict[str, str], code: str) -> Optional[Tuple[int, str, str]]:
    """정확코드 → base 폴백. 반환: (number, formula, from_key)"""
    pf = plural_map.get(code)
    if not pf:
        base = code.split("_", 1)[0]
        pf = plural_map.get(base)
        from_key = base if pf else ""
    else:
        from_key = code
    if not pf:
        return None
    parsed = parse_plural_forms(pf)
    if not parsed:
        return None
    num, formula = parsed
    return num, formula, from_key

def any_alias_match(lang_obj: Dict[str, Any], target_codes: Set[str]) -> Optional[str]:
    """해당 Weblate 언어의 aliases 중 하나라도 target과 맞으면 그 alias 코드(정규화된)를 반환"""
    aliases = lang_obj.get("aliases") or []
    for a in aliases:
        ca = canon(a)
        if ca in target_codes:
            return ca
    return None

# ---------- 메인 ----------
def main():
    ap = argparse.ArgumentParser(description="Weblate 보수적 동기화 (zanata.json만 남기고 이름/Plural 맞춤)")
    ap.add_argument("-z", "--zanata", required=True, help="zanata locales JSON (배열)")
    ap.add_argument("-p", "--plural", required=True, help="zanata-plural.json")
    ap.add_argument("--apply", action="store_true", help="실제 반영")
    ap.add_argument("--exclude", nargs="*", default=["en", "ko"], help="삭제 제외 코드")
    ap.add_argument("--url", default=os.getenv("WEBLATE_URL", ""))
    ap.add_argument("--token", default=os.getenv("WEBLATE_API_KEY", ""))
    args = ap.parse_args()

    if not args.token:
        print("ERROR: WEBLATE_API_KEY 또는 --token 필요", file=sys.stderr)
        sys.exit(1)

    # 입력 준비
    zanata = load_zanata_locales(args.zanata)     # {code: {name}}
    plural_map = load_plural_map(args.plural)      # {code: 'nplurals=..; plural=..'}
    target_codes: Set[str] = set(zanata.keys())

    print("=== 계획 ===")
    print(f"- 대상(Zanata): {len(target_codes)}개")
    print(f"- plural 엔트리 : {len(plural_map)}개")
    print(f"- 모드: {'실제 반영' if args.apply else '드라이런'}\n")

    cli = WeblateClient(args.url, args.token)
    current = cli.list_languages()
    print(f"- 현재 Weblate 언어: {len(current)}개\n")

    keep_codes: Set[str] = set()     # 남기는 Weblate 코드(매칭됨)
    create_list: Set[str] = set()    # zanata에 있는데 Weblate에 없어 생성할 코드
    delete_list: Set[str] = set()    # 제거할 Weblate 코드

    # (1) 존재하는 Weblate 언어들: 코드/alias로 매칭 시도
    for w_code, obj in current.items():
        cw = canon(w_code)
        matched_by = None
        z_code_for_this = None

        if cw in target_codes:
            matched_by = "code"
            z_code_for_this = cw
        else:
            hit = any_alias_match(obj, target_codes)
            if hit:
                matched_by = f"alias({hit})"
                z_code_for_this = hit

        if matched_by:
            keep_codes.add(w_code)
            # 이름/Plural 갱신
            want_name = zanata[z_code_for_this]["name"]
            have_name = (obj.get("name") or "").strip()

            # plural 선택 (z_code 기준으로 선택하되, 없으면 cw 기준도 시도)
            picked = pick_plural(plural_map, z_code_for_this) or pick_plural(plural_map, cw)
            need_plural = False
            num = formula = None
            from_key = ""
            if picked:
                num, formula, from_key = picked
                cur = obj.get("plural") or {}
                cur_num = cur.get("number")
                cur_for = (cur.get("formula") or "").strip()
                need_plural = not (cur_num == num and cur_for == formula)

            need_name = (want_name and want_name != have_name)

            if not (need_name or need_plural):
                print(f"- {w_code}: 유지 (이름/Plural 동일) [{matched_by}]")
            else:
                print(f"- {w_code}: 갱신 [{matched_by}]"
                      f"{' [name]' if need_name else ''}"
                      f"{' [plural]' if need_plural else ''}"
                      f"  name: {have_name!r} -> {want_name!r}"
                      f"{f'  plural: {cur_num}/{cur_for!r} -> {num}/{formula!r} (from {from_key})' if need_plural else ''}")
                if args.apply:
                    status, body = cli.patch_language(
                        w_code,
                        want_name if need_name else None,
                        num if need_plural else None,
                        formula if need_plural else None
                    )
                    if status not in (200, 202):
                        print(f"  ✗ PATCH 실패: HTTP {status} body={body[:200]}")

        else:
            # 대상이 아니면 삭제 후보
            if canon(w_code) in args.exclude:
                print(f"- {w_code}: 대상 아님이지만 exclude 보호 → 유지")
                keep_codes.add(w_code)
            else:
                delete_list.add(w_code)

    # (2) 생성 대상: zanata에 있는데(정규화 코드), Weblate 코드/alias로도 못 찾은 것
    existing_codes_and_aliases: Set[str] = set(canon(c) for c in current.keys())
    for obj in current.values():
        for a in (obj.get("aliases") or []):
            existing_codes_and_aliases.add(canon(a))

    for z_code in target_codes:
        if z_code not in existing_codes_and_aliases:
            create_list.add(z_code)

    # (3) 실행
    print("\n=== 실행 계획 요약 ===")
    print(f"- 유지/갱신: {len(keep_codes)}개")
    print(f"- 생성: {len(create_list)}개")
    print(f"- 삭제: {len(delete_list)}개")
    print(f"- 모드: {'실제 반영' if args.apply else '드라이런'}\n")

    # 생성
    for code in sorted(create_list):
        want_name = zanata[code]["name"]
        picked = pick_plural(plural_map, code)
        if not picked:
            print(f"- {code}: 생성 스킵 (plural 부재)")
            continue
        num, formula, from_key = picked
        print(f"- {code}: 생성 name={want_name!r} plural=({num},{formula!r}) (from {from_key})")
        if args.apply:
            s, body = cli.create_language(code, want_name, num, formula)
            if s not in (200, 201):
                print(f"  ✗ 생성 실패: HTTP {s} body={body[:200]}")

    # 삭제
    for code in sorted(delete_list):
        print(f"- {code}: 삭제")
        if args.apply:
            s, body = cli.delete_language(code)
            if s not in (200, 202, 204):
                print(f"  ✗ 삭제 실패: HTTP {s} body={body[:200]}")

    print("\n✅ 완료")

if __name__ == "__main__":
    main()
