#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weblate 언어 일괄 생성/갱신 스크립트
- 입력: code -> plural-forms 맵(JSON)
- 동작:
  * 언어가 없으면 생성(코드/이름/복수형 공식)
  * 언어가 있으면 plural(number/formula)만 업데이트
- 기본 드라이런, --apply 로 실제 반영, --yes 로 확인 프롬프트 생략
- 환경변수: WEBLATE_URL, WEBLATE_API_KEY (옵션: CLI 기본값을 덮어씀)
"""

import os, sys, json, argparse, urllib.parse, re
import requests
from typing import Dict, Any, Tuple

def load_mapping(path: str) -> Dict[str, str]:
    """입력 JSON을 읽어 {code: plural_equation} 딕셔너리로 반환"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    mapping: Dict[str, str] = {}

    if isinstance(data, dict):
        # {"en":"nplurals=2; plural=...","ko":"..."}
        for k, v in data.items():
            if isinstance(v, str):
                mapping[k] = v.strip()
    elif isinstance(data, list):
        # [{"en":"..."}, {"ko":"..."}] 또는 [{"code":"en","plural":"..."}]
        for item in data:
            if isinstance(item, dict):
                if "code" in item and ("plural" in item or "plural_equation" in item):
                    pf = item.get("plural") or item.get("plural_equation")
                    mapping[item["code"]] = (pf or "").strip()
                else:
                    # {"en":"..."} 형태 지원
                    for k, v in item.items():
                        if isinstance(v, str):
                            mapping[k] = v.strip()
    else:
        raise ValueError("지원하지 않는 JSON 형식입니다.")
    return mapping

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

    def create_language(self, code: str, plural_number: int, plural_formula: str,
                        name: str = None, direction: str = None) -> Tuple[int, str]:
        payload = {
            "code": code,
            "name": name or code,
            "plural": {
                "number": plural_number,
                "formula": plural_formula,
            },
        }
        if direction in ("ltr", "rtl"):
            payload["direction"] = direction
        r = self.session.post(f"{self.base}/api/languages/", json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
            return r.status_code, ""
        except requests.exceptions.HTTPError:
            return r.status_code, r.text

    def update_language(self, code: str, plural_number: int, plural_formula: str) -> Tuple[int, str]:
        payload = {
            "plural": {
                "number": plural_number,
                "formula": plural_formula,
            }
        }
        r = self.session.patch(self._lang_url(code), json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
            return r.status_code, ""
        except requests.exceptions.HTTPError:
            return r.status_code, r.text

def parse_plural_forms(pf: str):
    """
    'nplurals=2; plural=(n != 1);' → (2, 'n != 1')
    유효하지 않으면 None 반환
    """
    if not pf:
        return None
    s = pf.strip().rstrip(";")
    m_num = re.search(r"nplurals\s*=\s*(\d+)", s, re.IGNORECASE)
    m_for = re.search(r"plural\s*=\s*([^;]+)", s, re.IGNORECASE)
    if not m_num or not m_for:
        return None
    number = int(m_num.group(1))
    formula = m_for.group(1).strip()
    if formula.startswith("(") and formula.endswith(")"):
        formula = formula[1:-1].strip()
    formula = formula.rstrip(";").strip()
    if not formula or formula.count("(") != formula.count(")"):
        return None
    return number, formula

def main():
    p = argparse.ArgumentParser(description="Weblate 언어 일괄 생성/갱신")
    p.add_argument("-i", "--input", required=True, help="코드→Plural-Forms 맵 JSON 경로")
    p.add_argument("--apply", action="store_true", help="실제로 Weblate에 반영")
    p.add_argument("--yes", action="store_true", help="실반영 시 확인 프롬프트 없이 진행")
    p.add_argument("--timeout", type=int, default=int(os.getenv("WEBLATE_TIMEOUT", "30")), help="요청 타임아웃(초), 기본 30")
    p.add_argument("--url", default=os.getenv("WEBLATE_URL", ""), help="Weblate URL (기본: 환경변수 WEBLATE_URL")
    p.add_argument("--token", default=os.getenv("WEBLATE_API_KEY", ""), help="Weblate API Token (기본: 환경변수 WEBLATE_API_KEY)")
    p.add_argument("--name-like-code", action="store_true", help="생성 시 name을 코드와 동일하게 저장(기본 동작)")
    p.add_argument("--rtl-codes", nargs="*", default=[], help="우측-좌측 언어코드 목록(예: ar he fa ug) 생성 시 direction=rtl 설정")
    args = p.parse_args()

    if not args.token:
        print("ERROR: WEBLATE_API_KEY 또는 --token 을 지정하세요.", file=sys.stderr)
        sys.exit(1)

    # 1) 입력 읽기
    mapping = load_mapping(args.input)
    if not mapping:
        print("입력 맵이 비어있습니다. 작업을 종료합니다.")
        return

    # 2) 클라이언트 준비
    cli = WeblateClient(args.url, args.token, timeout=args.timeout)

    # 3) 실행 모드 안내
    print("=== Weblate 언어 생성/갱신 도구 ===")
    print(f"- 서버: {args.url}")
    print(f"- 입력: {args.input} (총 {len(mapping)}개)")
    print(f"- 모드: {'실제 반영' if args.apply else '드라이런'}")
    print()

    if args.apply and not args.yes:
        sure = input("⚠️  실제로 생성/갱신을 진행합니다. 계속하려면 'APPLY' 입력: ").strip()
        if sure != "APPLY":
            print("중단합니다.")
            return

    created = 0
    updated = 0
    skipped = 0
    failed = 0
    failures = []

    # 4) 각 코드 처리
    rtl_set = set(args.rtl_codes)
    for code, pf in mapping.items():
        parsed = parse_plural_forms(pf)
        if not parsed:
            print(f"- {code}: 입력 plural-forms 파싱 실패 → 스킵")
            failed += 1
            failures.append((code, 0, "invalid plural-forms string"))
            continue

        num, formula = parsed
        status, data = cli.get_language(code)
        if status == 200:
            current = data.get("plural") or {}
            curr_num = current.get("number")
            curr_for = (current.get("formula") or "").strip()
            if curr_num == num and curr_for == formula:
                print(f"- {code}: 이미 동일한 plural. 스킵")
                skipped += 1
                continue
            print(f"- {code}: 업데이트 ( {curr_num}/{curr_for!r} -> {num}/{formula!r} )")
            if args.apply:
                s, body = cli.update_language(code, num, formula)
                if s in (200, 202):
                    updated += 1
                else:
                    failed += 1
                    failures.append((code, s, body[:300]))
            else:
                updated += 1
        elif status == 404:
            dir_flag = "rtl" if code in rtl_set else None
            print(f"- {code}: 생성 (number={num}, formula={formula!r}{', direction=rtl' if dir_flag else ''})")
            if args.apply:
                s, body = cli.create_language(code, num, formula, name=(code if args.name_like_code else None), direction=dir_flag)
                if s in (200, 201):
                    created += 1
                else:
                    failed += 1
                    failures.append((code, s, body[:300]))
            else:
                created += 1
        else:
            print(f"- {code}: 조회 실패(HTTP {status}) → 스킵")
            failed += 1
            failures.append((code, status, "lookup_failed"))

    # 5) 요약
    print("\n=== 요약 ===")
    print(f"생성 예정/완료: {created}")
    print(f"갱신 예정/완료: {updated}")
    print(f"스킵: {skipped}")
    print(f"실패: {failed}")
    print(f"모드: {'실제 반영' if args.apply else '드라이런'}")

    if failures:
        print("\n실패 상세:")
        for code, s, body in failures[:30]:
            print(f"  - {code}: HTTP {s} body={body}")

if __name__ == "__main__":
    main()
