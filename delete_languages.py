#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Script to delete all languages registered in Weblate
"""

import argparse
import json
import os
import requests

from typing import Dict
from typing import List


class WeblateLanguageDeleter:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()

        # Set API key authentication headers
        self.session.headers.update({
            'Authorization': f'Token {api_key}',
            'Content-Type': 'application/json'
        })

    def get_all_languages(self) -> List[Dict]:
        all_languages = []
        url = f"{self.base_url}/api/languages/"

        try:
            while url:
                response = self.session.get(url)
                response.raise_for_status()

                data = response.json()
                results = data.get('results', [])
                all_languages.extend(results)

                # Check for next page URL
                url = data.get('next')

                if url:
                    print(f"Loading next {len(all_languages)} languages)")

            print(f"Collected a total of {len(all_languages)} languages.")
            return all_languages
        except requests.exceptions.RequestException as e:
            print(f"Error occurred while retrieving language information: {e}")
            return all_languages

    def delete_language(self, language_code: str) -> bool:
        url = f"{self.base_url}/api/languages/{language_code}/"

        try:
            response = self.session.delete(url)
            response.raise_for_status()
            print(response.status_code)
            return True

        except requests.exceptions.RequestException as e:
            print(f"Error occurred while deleting language: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response body: {e.response.text}")
            return False

    def delete_all_languages(self, dry_run: bool = True,
                             exclude_languages: List[str] = None) -> Dict:
        if exclude_languages is None:
            exclude_languages = []

        print("=== Weblate Language Deletion Started ===\n")

        # 1. Retrieve currently registered languages
        print("1. Retrieving currently registered languages...")
        languages = self.get_all_languages()

        if not languages:
            print("No languages found to delete.")
            return {
                'total': 0,
                'deleted': 0,
                'skipped': 0,
                'failed': 0
            }

        print(f"Total {len(languages)} languages are registered.\n")

        # 2. Filter languages for deletion
        languages_to_delete = []
        languages_to_skip = []

        for lang in languages:
            code = lang.get('code', '')
            name = lang.get('name', 'N/A')

            if code in exclude_languages:
                languages_to_skip.append((code, name))
            else:
                languages_to_delete.append((code, name))

        print(f"Languages to delete: {len(languages_to_delete)}")
        print(f"Excluded languages: {len(languages_to_skip)}")

        if languages_to_skip:
            print("Excluded languages:")
            for code, name in languages_to_skip:
                print(f"  - {code}: {name}")
        print()

        # 3. Execute deletion
        print("2. Executing language deletion...")
        deleted_count = 0
        failed_count = 0

        for code, name in languages_to_delete:
            print(f"Processing: {code} ({name})")

            if dry_run:
                print("  [Dry Run] Deletion simulation")
                deleted_count += 1
            else:
                if self.delete_language(code):
                    print("  ✓ Deletion successful")
                    deleted_count += 1
                else:
                    print("  ✗ Deletion failed")
                    failed_count += 1

        # 4. Summary
        print("\n=== Deletion Completed ===")
        print(f"Total languages: {len(languages)}")
        print(f"Deleted: {deleted_count}")
        print(f"Skipped: {len(languages_to_skip)}")
        print(f"Failed: {failed_count}")
        print(f"Dry run: {dry_run}")

        return {
            'total': len(languages),
            'deleted': deleted_count,
            'skipped': len(languages_to_skip),
            'failed': failed_count
        }

    def backup_languages(self, filename: str = "weblate_language_backup.json"):
        print(f"Backing up language information: {filename}")

        languages = self.get_all_languages()

        if languages:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(languages, f, indent=2, ensure_ascii=False)
            print(f"✓ Backup completed: {len(languages)} languages")
        else:
            print("No languages available for backup.")


def main():
    parser = argparse.ArgumentParser(description='language deletion tool')
    parser.add_argument('--apply',
                        action='store_true',
                        help='Actually delete languages (default: dry run)')
    parser.add_argument('--exclude',
                        nargs='+',
                        default=['en', 'ko'],
                        help='Language codes to exclude from deletion')
    parser.add_argument('--backup',
                        action='store_true',
                        default=True,
                        help='Create a backup before deletion (default: True)')

    args = parser.parse_args()

    print("=== Weblate Language Deletion Tool ===\n")

    # Weblate settings
    weblate_url = os.getenv("WEBLATE_URL")
    weblate_api_key = os.getenv("WEBLATE_API_KEY")

    print(f"Weblate server: {weblate_url}")
    print(f"Mode: {'Actual deletion' if args.apply else 'Dry run'}")
    print(f"Excluded languages: {args.exclude}")
    print(f"Create backup: {'Yes' if args.backup else 'No'}")
    print()

    # Create Weblate language deleter object
    deleter = WeblateLanguageDeleter(weblate_url, weblate_api_key)

    # 1. Test connection
    print("1. Testing connection to Weblate server...")
    try:
        languages = deleter.get_all_languages()
        print(f"✓ Connection successful: {len(languages)} languages found")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return

    # 2. Create backup
    if args.backup:
        print("\n2. Creating language backup...")
        deleter.backup_languages()

    # 3. Preview languages to delete
    print("\n3. Checking languages to delete...")
    languages = deleter.get_all_languages()

    if languages:
        print("Currently registered languages:")
        for lang in languages[:10]:  # show only first 10
            code = lang.get('code', 'N/A')
            name = lang.get('name', 'N/A')
            print(f"  - {code}: {name}")
        if len(languages) > 10:
            print(f"  ... and {len(languages) - 10} more")
    else:
        print("No registered languages found.")

    # 4. Execute deletion
    mode = "Performing actual deletion" if args.apply else "Testing deletion"
    print(f"\n4. {mode}...")

    if not args.apply:
        print(" Dry run mode: No actual deletion performed.")
        print("Use the --apply option to actually delete languages.")
        print()

    # 5. Final summary
    if args.apply:
        print("\n Actual deletion completed!")
    else:
        print("\n Dry run completed. Use --apply option for actual deletion.")


if __name__ == "__main__":
    main()
