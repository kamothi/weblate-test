#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weblate에 등록된 모든 언어를 삭제하는 스크립트
"""

import requests
import json
import argparse
from typing import Dict, List, Optional


class WeblateLanguageDeleter:
    """Weblate 언어 삭제 클라이언트"""
    
    def __init__(self, base_url: str, api_key: str):
        """
        Weblate 언어 삭제 클라이언트 초기화
        
        Args:
            base_url: Weblate 서버의 기본 URL
            api_key: Weblate API 키
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        
        # API 키 인증 헤더 설정
        self.session.headers.update({
            'Authorization': 'Token {api_key}',
            'Content-Type': 'application/json'
        })
    
    def get_all_languages(self) -> List[Dict]:
        """
        Weblate에 등록된 모든 언어 정보를 가져옵니다.
        페이지네이션을 지원하여 모든 페이지의 데이터를 수집합니다.
        
        Returns:
            언어 정보 리스트
        """
        all_languages = []
        url = f"{self.base_url}/api/languages/"
        
        try:
            while url:
                response = self.session.get(url)
                response.raise_for_status()
                
                data = response.json()
                results = data.get('results', [])
                all_languages.extend(results)
                
                # 다음 페이지 URL 확인
                url = data.get('next')
                
                if url:
                    print(f"다음 페이지 로딩 중... (현재 {len(all_languages)}개 언어 수집됨)")
            
            print(f"총 {len(all_languages)}개 언어 정보를 수집했습니다.")
            return all_languages
            
        except requests.exceptions.RequestException as e:
            print(f"언어 정보를 가져오는 중 오류 발생: {e}")
            return all_languages
    
    def delete_language(self, language_code: str) -> bool:
        """
        특정 언어를 삭제합니다.
        
        Args:
            language_code: 삭제할 언어 코드
            
        Returns:
            삭제 성공 여부
        """
        url = f"{self.base_url}/api/languages/{language_code}/"
        
        try:
            response = self.session.delete(url)
            response.raise_for_status()
            print(response.status_code)
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"언어 삭제 중 오류 발생: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"응답 내용: {e.response.text}")
            return False
    
    def delete_all_languages(self, dry_run: bool = True, exclude_languages: List[str] = None) -> Dict:
        """
        모든 언어를 삭제합니다.
        
        Args:
            dry_run: 실제 삭제하지 않고 시뮬레이션만 실행
            exclude_languages: 삭제에서 제외할 언어 코드 리스트
            
        Returns:
            삭제 결과 통계
        """
        if exclude_languages is None:
            exclude_languages = []
        
        print("=== Weblate 언어 삭제 시작 ===\n")
        
        # 1. 현재 등록된 언어 목록 가져오기
        print("1. 현재 등록된 언어 목록 조회 중...")
        languages = self.get_all_languages()
        
        if not languages:
            print("삭제할 언어가 없습니다.")
            return {
                'total': 0,
                'deleted': 0,
                'skipped': 0,
                'failed': 0
            }
        
        print(f"총 {len(languages)}개의 언어가 등록되어 있습니다.\n")
        
        # 2. 삭제할 언어 필터링
        languages_to_delete = []
        languages_to_skip = []
        
        for lang in languages:
            code = lang.get('code', '')
            name = lang.get('name', 'N/A')
            
            if code in exclude_languages:
                languages_to_skip.append((code, name))
            else:
                languages_to_delete.append((code, name))
        
        print(f"삭제 대상: {len(languages_to_delete)}개")
        print(f"제외 대상: {len(languages_to_skip)}개")
        
        if languages_to_skip:
            print("제외할 언어:")
            for code, name in languages_to_skip:
                print(f"  - {code}: {name}")
        print()
        
        # 3. 언어 삭제 실행
        print("2. 언어 삭제 실행 중...")
        deleted_count = 0
        failed_count = 0
        
        for code, name in languages_to_delete:
            print(f"처리 중: {code} ({name})")
            
            if dry_run:
                print(f"  [드라이 런] 삭제 시뮬레이션")
                deleted_count += 1
            else:
                if self.delete_language(code):
                    print(f"  ✓ 삭제 성공")
                    deleted_count += 1
                else:
                    print(f"  ✗ 삭제 실패")
                    failed_count += 1
        
        # 4. 결과 요약
        print(f"\n=== 삭제 완료 ===")
        print(f"총 언어 수: {len(languages)}개")
        print(f"삭제된 언어: {deleted_count}개")
        print(f"건너뛴 언어: {len(languages_to_skip)}개")
        print(f"실패한 언어: {failed_count}개")
        print(f"드라이 런: {dry_run}")
        
        return {
            'total': len(languages),
            'deleted': deleted_count,
            'skipped': len(languages_to_skip),
            'failed': failed_count
        }
    
    def backup_languages(self, filename: str = "weblate_languages_backup.json"):
        """
        현재 언어 정보를 백업 파일로 저장합니다.
        
        Args:
            filename: 백업 파일명
        """
        print(f"언어 정보 백업 중: {filename}")
        
        languages = self.get_all_languages()
        
        if languages:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(languages, f, indent=2, ensure_ascii=False)
            print(f"✓ 백업 완료: {len(languages)}개 언어")
        else:
            print("백업할 언어가 없습니다.")


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='Weblate 언어 삭제 도구')
    parser.add_argument('--apply', action='store_true', 
                       help='실제로 언어를 삭제합니다 (기본값: 드라이 런)')
    parser.add_argument('--exclude', nargs='+', default=['en', 'ko'],
                       help='삭제에서 제외할 언어 코드 (기본값: en ko)')
    parser.add_argument('--backup', action='store_true', default=True,
                       help='삭제 전 백업을 생성합니다 (기본값: True)')
    
    args = parser.parse_args()
    
    print("=== Weblate 언어 삭제 도구 ===\n")
    
    # Weblate 설정
    weblate_url = ""
    weblate_api_key = ""
    
    print(f"Weblate 서버: {weblate_url}")
    print(f"실행 모드: {'실제 삭제' if args.apply else '드라이 런'}")
    print(f"제외 언어: {args.exclude}")
    print(f"백업 생성: {'예' if args.backup else '아니오'}")
    print()
    
    # Weblate 언어 삭제 객체 생성
    deleter = WeblateLanguageDeleter(weblate_url, weblate_api_key)
    
    # 1. 연결 테스트
    print("1. Weblate 서버 연결 테스트...")
    try:
        languages = deleter.get_all_languages()
        print(f"✓ 연결 성공: {len(languages)}개 언어 발견")
    except Exception as e:
        print(f"✗ 연결 실패: {e}")
        return
    
    # 2. 백업 생성
    if args.backup:
        print("\n2. 언어 정보 백업 생성...")
        deleter.backup_languages()
    
    # 3. 삭제할 언어 확인
    print("\n3. 삭제할 언어 확인...")
    languages = deleter.get_all_languages()
    
    if languages:
        print("현재 등록된 언어:")
        for lang in languages[:10]:  # 처음 10개만 표시
            code = lang.get('code', 'N/A')
            name = lang.get('name', 'N/A')
            print(f"  - {code}: {name}")
        if len(languages) > 10:
            print(f"  ... 및 {len(languages) - 10}개 더")
    else:
        print("등록된 언어가 없습니다.")
    
    # 4. 삭제 실행
    print(f"\n4. {'실제 삭제' if args.apply else '드라이 런으로 삭제 테스트'}...")
    
    if not args.apply:
        print("⚠️  드라이 런 모드: 실제 삭제가 수행되지 않습니다.")
        print("실제로 삭제하려면 --apply 옵션을 사용하세요.")
        print()
    
    result = deleter.delete_all_languages(
        dry_run=not args.apply,
        exclude_languages=args.exclude
    )
    
    # 5. 결과 요약
    if args.apply:
        print("\n✅ 실제 삭제가 완료되었습니다!")
    else:
        print("\n📋 드라이 런 완료. 실제 삭제를 위해 --apply 옵션을 사용하세요.")


if __name__ == "__main__":
    main() 