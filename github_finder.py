#!/usr/bin/env python3
"""
Enhanced GitHub Python Repository Finder with Active Testing
Searches for Python repositories with recent merged PRs containing test changes
Features:
- Repository size filtering (< 100MB)
- Lines changed tracking in PRs
- Enhanced persistence and caching
- Robust error handling and rate limiting
- Live output updates
"""

import requests
import json
import csv
import time
import os
import pickle
from datetime import datetime, timedelta
from typing import List, Dict, Any, Set, Optional
import argparse
import re
from pathlib import Path

class GitHubTestRepoFinder:
    def __init__(self, token: str = None, cache_file: str = "repo_cache.pkl"):
        self.token = token
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Test-Repo-Finder'
        }
        if token:
            self.headers['Authorization'] = f'token {token}'
        
        self.base_url = 'https://api.github.com'
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # Enhanced cache management
        self.cache_file = cache_file
        self.processed_repos: Set[str] = set()
        self.repo_metadata: Dict[str, Dict] = {}
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = None
        
        # Live output tracking
        self.output_files = {}
        self.live_update_enabled = False
        self.current_results = []
        
        self.load_cache()
    
    def load_cache(self):
        """Load previously processed repositories from cache"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                    self.processed_repos = cache_data.get('processed_repos', set())
                    self.repo_metadata = cache_data.get('repo_metadata', {})
                print(f"📂 Loaded cache with {len(self.processed_repos)} previously processed repositories")
            except Exception as e:
                print(f"⚠️  Warning: Could not load cache file: {e}")
                self.processed_repos = set()
                self.repo_metadata = {}
    
    def save_cache(self):
        """Save processed repositories to cache"""
        try:
            cache_data = {
                'processed_repos': self.processed_repos,
                'repo_metadata': self.repo_metadata,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            print(f"💾 Cache saved with {len(self.processed_repos)} repositories")
        except Exception as e:
            print(f"⚠️  Warning: Could not save cache file: {e}")
    
    def clear_cache(self):
        """Clear the repository cache"""
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
            print(f"🗑️  Cache file {self.cache_file} deleted")
        self.processed_repos = set()
        self.repo_metadata = {}
    
    def check_rate_limit(self):
        """Check and handle rate limiting"""
        try:
            response = self.session.get(f'{self.base_url}/rate_limit')
            if response.status_code == 200:
                data = response.json()
                core_limit = data.get('resources', {}).get('core', {})
                self.rate_limit_remaining = core_limit.get('remaining', 0)
                self.rate_limit_reset = core_limit.get('reset', 0)
                
                if self.rate_limit_remaining < 10:
                    reset_time = datetime.fromtimestamp(self.rate_limit_reset)
                    wait_time = (reset_time - datetime.now()).total_seconds() + 10
                    print(f"⚠️  Rate limit low ({self.rate_limit_remaining}). Waiting {wait_time:.0f} seconds...")
                    time.sleep(max(wait_time, 0))
        except Exception as e:
            print(f"Warning: Could not check rate limit: {e}")
    
    def handle_request_with_retry(self, url: str, params: dict = None, max_retries: int = 3) -> Optional[requests.Response]:
        """Handle requests with retry logic and rate limiting"""
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params)
                
                if response.status_code == 403:
                    if 'rate limit' in response.text.lower():
                        print(f"⚠️  Rate limit exceeded. Waiting 60 seconds... (attempt {attempt + 1})")
                        time.sleep(60)
                        continue
                    else:
                        print(f"⚠️  Access forbidden for {url}")
                        return None
                
                if response.status_code == 404:
                    return None
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"Error after {max_retries} attempts: {e}")
                    return None
                time.sleep(2 ** attempt)
        
        return None
    
    def enable_live_output(self, output_prefix: str, output_formats: List[str] = ['csv']):
        """Enable live updating of output files"""
        self.live_update_enabled = True
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        for format_type in output_formats:
            filename = f"{output_prefix}_{timestamp}.{format_type}"
            self.output_files[format_type] = filename
            
            if format_type == 'csv':
                self._initialize_csv_file(filename)
            elif format_type == 'json':
                self._initialize_json_file(filename)
            elif format_type == 'txt':
                self._initialize_txt_file(filename)
        
        print(f"📝 Live output enabled for formats: {', '.join(output_formats)}")
        for format_type, filename in self.output_files.items():
            print(f"   {format_type.upper()}: {filename}")
    
    def _initialize_csv_file(self, filename: str):
        """Initialize CSV file with headers"""
        fieldnames = [
            'repo_name', 'repo_url', 'repo_stars', 'repo_size_mb', 'repo_description',
            'pr_number', 'pr_title', 'pr_url', 'pr_merged_at',
            'total_lines_changed', 'total_additions', 'total_deletions',
            'new_test_cases_count', 'test_files_with_new_cases', 'test_additions_only',
            'code_files_changed', 'new_test_files_added',
            'test_file_line_changes', 'code_file_line_changes',
            'test_files_list', 'code_files_list'
        ]
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
    
    def _initialize_json_file(self, filename: str):
        """Initialize JSON file with basic structure"""
        initial_data = {
            'generated_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'total_prs': 0,
            'unique_repos': 0,
            'data': []
        }
        
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            json.dump(initial_data, jsonfile, indent=2, ensure_ascii=False)
    
    def _initialize_txt_file(self, filename: str):
        """Initialize TXT file with header"""
        with open(filename, 'w', encoding='utf-8') as txtfile:
            txtfile.write("GitHub Python Test Repository Analysis Results (Live Updates)\n")
            txtfile.write("=" * 60 + "\n")
            txtfile.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            txtfile.write("Note: This file is updated in real-time as results are found.\n\n")
    
    def _append_to_csv(self, pr_data: Dict):
        """Append a single PR result to CSV file"""
        if 'csv' not in self.output_files:
            return
        
        filename = self.output_files['csv']
        repo = pr_data['repository']
        pr = pr_data['pr']
        analysis = pr_data['analysis']
        
        row = {
            'repo_name': repo['full_name'],
            'repo_url': repo['html_url'],
            'repo_stars': repo['stargazers_count'],
            'repo_size_mb': round(repo.get('size', 0) / 1024, 2),
            'repo_description': (repo.get('description') or '').replace('\n', ' ').replace('\r', ' '),
            'pr_number': pr['number'],
            'pr_title': pr['title'].replace('\n', ' ').replace('\r', ' '),
            'pr_url': pr['html_url'],
            'pr_merged_at': pr['merged_at'],
            'total_lines_changed': analysis['total_changes'],
            'total_additions': analysis['total_additions'],
            'total_deletions': analysis['total_deletions'],
            'new_test_cases_count': analysis['new_test_cases_count'],
            'test_files_with_new_cases': len(analysis['test_files_with_new_cases']),
            'test_additions_only': analysis['test_additions_only'],
            'code_files_changed': len(analysis['code_files']),
            'new_test_files_added': len(analysis['new_test_files']),
            'test_file_line_changes': analysis['test_file_changes'],
            'code_file_line_changes': analysis['code_file_changes'],
            'test_files_list': '; '.join([tf['filename'] for tf in analysis['test_files_with_new_cases']]),
            'code_files_list': '; '.join(analysis['code_files'][:10])
        }
        
        fieldnames = list(row.keys())
        
        with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writerow(row)
    
    def _update_json_file(self):
        """Update the entire JSON file with current results"""
        if 'json' not in self.output_files:
            return
        
        filename = self.output_files['json']
        
        unique_repos = set(pr_data['repository']['full_name'] for pr_data in self.current_results)
        
        export_data = {
            'generated_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'total_prs': len(self.current_results),
            'unique_repos': len(unique_repos),
            'data': []
        }
        
        for pr_data in self.current_results:
            repo = pr_data['repository']
            pr = pr_data['pr']
            analysis = pr_data['analysis']
            
            export_data['data'].append({
                'repository': {
                    'name': repo['full_name'],
                    'url': repo['html_url'],
                    'stars': repo['stargazers_count'],
                    'size_mb': round(repo.get('size', 0) / 1024, 2),
                    'description': repo.get('description', '')
                },
                'pull_request': {
                    'number': pr['number'],
                    'title': pr['title'],
                    'url': pr['html_url'],
                    'merged_at': pr['merged_at']
                },
                'analysis': analysis
            })
        
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            json.dump(export_data, jsonfile, indent=2, ensure_ascii=False)
    
    def _append_to_txt(self, pr_data: Dict):
        """Append a single PR result to TXT file"""
        if 'txt' not in self.output_files:
            return
        
        filename = self.output_files['txt']
        repo = pr_data['repository']
        pr = pr_data['pr']
        analysis = pr_data['analysis']
        
        with open(filename, 'a', encoding='utf-8') as txtfile:
            current_repo_count = len(set(pr_data['repository']['full_name'] for pr_data in self.current_results))
            
            if len(self.current_results) == 1 or pr_data == self.current_results[0] or \
               (len(self.current_results) > 1 and 
                self.current_results[-2]['repository']['full_name'] != repo['full_name']):
                
                txtfile.write(f"\n{current_repo_count}. REPOSITORY: {repo['full_name']}\n")
                txtfile.write(f"   URL: {repo['html_url']}\n")
                txtfile.write(f"   Stars: {repo['stargazers_count']}\n")
                txtfile.write(f"   Size: {repo.get('size', 0)/1024:.2f} MB\n")
                txtfile.write(f"   Description: {repo.get('description', 'N/A')}\n")
                txtfile.write("   " + "-" * 50 + "\n")
            
            txtfile.write(f"   PR #{pr['number']}: {pr['title']}\n")
            txtfile.write(f"   URL: {pr['html_url']}\n")
            txtfile.write(f"   Merged: {pr['merged_at']}\n")
            txtfile.write(f"   Total lines changed: {analysis['total_changes']} (+{analysis['total_additions']}/-{analysis['total_deletions']})\n")
            txtfile.write(f"   New test cases: {analysis['new_test_cases_count']}\n")
            txtfile.write(f"   Test files changed: {len(analysis['test_files_with_new_cases'])} ({analysis['test_file_changes']} lines)\n")
            txtfile.write(f"   Code files changed: {len(analysis['code_files'])} ({analysis['code_file_changes']} lines)\n")
            if analysis['new_test_files']:
                txtfile.write(f"   New test files: {len(analysis['new_test_files'])}\n")
            txtfile.write("\n")
    
    def _update_live_outputs(self, pr_data: Dict):
        """Update all enabled live output files with new PR data"""
        if not self.live_update_enabled:
            return
        
        self.current_results.append(pr_data)
        
        try:
            self._append_to_csv(pr_data)
            self._update_json_file()
            self._append_to_txt(pr_data)
            
            unique_repos = len(set(pr_data['repository']['full_name'] for pr_data in self.current_results))
            print(f"    📝 Live update: {len(self.current_results)} PRs from {unique_repos} repos saved")
            
        except Exception as e:
            print(f"    ⚠️  Warning: Could not update live output files: {e}")
    
    def is_repo_processed(self, repo_name: str, max_age_days: int = 7) -> bool:
        """Check if repository was recently processed"""
        if repo_name not in self.processed_repos:
            return False
        
        metadata = self.repo_metadata.get(repo_name, {})
        last_processed = metadata.get('last_processed')
        
        if last_processed:
            try:
                last_date = datetime.fromisoformat(last_processed)
                if datetime.now() - last_date < timedelta(days=max_age_days):
                    return True
            except ValueError:
                pass
        
        return False
    
    def mark_repo_processed(self, repo_name: str, found_prs: int = 0, repo_size: int = 0):
        """Mark repository as processed with enhanced metadata"""
        self.processed_repos.add(repo_name)
        self.repo_metadata[repo_name] = {
            'last_processed': datetime.now().isoformat(),
            'prs_found': found_prs,
            'repo_size_kb': repo_size
        }
    
    def get_repo_size(self, repo_full_name: str) -> Optional[int]:
        """Get repository size in KB"""
        url = f'{self.base_url}/repos/{repo_full_name}'
        response = self.handle_request_with_retry(url)
        
        if response:
            try:
                repo_data = response.json()
                return repo_data.get('size', 0)
            except Exception as e:
                print(f"Error getting repo size for {repo_full_name}: {e}")
        
        return None
    
    def search_python_repos(self, min_stars: int = 100, days_back: int = 30, 
                           max_repos: int = 1000, max_size_mb: int = 100) -> List[Dict]:
        """Search for popular Python repositories with size filtering"""
        max_size_kb = max_size_mb * 1024
        all_repos = []
        
        date_ranges = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        date_ranges.append((start_date, end_date))
        
        if max_repos > 1000:
            num_splits = min(10, (max_repos // 1000) + 1)
            days_per_split = days_back // num_splits
            
            date_ranges = []
            for i in range(num_splits):
                range_end = end_date - timedelta(days=i * days_per_split)
                range_start = range_end - timedelta(days=days_per_split)
                if range_start < start_date:
                    range_start = start_date
                date_ranges.append((range_start, range_end))
        
        print(f"🔍 Searching for repositories (will filter by size < {max_size_mb}MB)...")
        
        for date_range_idx, (range_start, range_end) in enumerate(date_ranges):
            if len(all_repos) >= max_repos:
                break
                
            since_date = range_start.strftime('%Y-%m-%d')
            until_date = range_end.strftime('%Y-%m-%d')
            
            query = f'language:python stars:>={min_stars} pushed:{since_date}..{until_date}'
            
            url = f'{self.base_url}/search/repositories'
            page = 1
            
            while len(all_repos) < max_repos:
                params = {
                    'q': query,
                    'sort': 'updated',
                    'order': 'desc',
                    'per_page': 100,
                    'page': page
                }
                
                response = self.handle_request_with_retry(url, params)
                if not response:
                    break
                
                try:
                    data = response.json()
                    items = data.get('items', [])
                    
                    if not items:
                        break
                    
                    filtered_items = []
                    for repo in items:
                        repo_size = repo.get('size', 0)
                        if repo_size <= max_size_kb:
                            filtered_items.append(repo)
                        else:
                            print(f"    ⏭️  Skipping {repo['full_name']} (size: {repo_size/1024:.1f}MB)")
                    
                    all_repos.extend(filtered_items)
                    page += 1
                    
                    if len(items) < 100 or page > 10:
                        break
                        
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f"Error processing search results: {e}")
                    break
            
            if len(all_repos) >= max_repos:
                break
                
            if date_range_idx < len(date_ranges) - 1:
                time.sleep(1)
        
        print(f"📊 Found {len(all_repos)} repositories under {max_size_mb}MB")
        return all_repos[:max_repos]
    
    def get_recent_merged_prs(self, repo_full_name: str, days_back: int = 30, max_prs: int = 100) -> List[Dict]:
        """Get recently merged pull requests for a repository"""
        since_date = (datetime.now() - timedelta(days=days_back)).isoformat()
        
        url = f'{self.base_url}/repos/{repo_full_name}/pulls'
        all_prs = []
        page = 1
        
        while len(all_prs) < max_prs:
            params = {
                'state': 'closed',
                'sort': 'updated',
                'direction': 'desc',
                'per_page': 100,
                'page': page
            }
            
            response = self.handle_request_with_retry(url, params)
            if not response:
                break
            
            try:
                prs = response.json()
                
                if not prs:
                    break
                
                merged_prs = []
                for pr in prs:
                    merged_at = pr.get('merged_at')
                    if merged_at and merged_at >= since_date:
                        merged_prs.append(pr)
                    elif merged_at and merged_at < since_date:
                        break
                
                all_prs.extend(merged_prs)
                page += 1
                
                if len(prs) < 100:
                    break
                    
                time.sleep(0.2)
                
            except Exception as e:
                print(f"Error getting PRs for {repo_full_name}: {e}")
                break
        
        return all_prs[:max_prs]
    
    def get_pr_files_with_stats(self, repo_full_name: str, pr_number: int) -> Dict[str, Any]:
        """Get files changed in a pull request with line change statistics"""
        url = f'{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/files'
        
        response = self.handle_request_with_retry(url)
        if not response:
            return {'files': [], 'total_additions': 0, 'total_deletions': 0, 'total_changes': 0}
        
        try:
            files = response.json()
            total_additions = sum(f.get('additions', 0) for f in files)
            total_deletions = sum(f.get('deletions', 0) for f in files)
            total_changes = sum(f.get('changes', 0) for f in files)
            
            return {
                'files': files,
                'total_additions': total_additions,
                'total_deletions': total_deletions,
                'total_changes': total_changes
            }
        except Exception as e:
            print(f"Error getting PR files for {repo_full_name}#{pr_number}: {e}")
            return {'files': [], 'total_additions': 0, 'total_deletions': 0, 'total_changes': 0}
    
    def has_testing_suite(self, repo_full_name: str) -> bool:
        """Check if repository has testing suite"""
        test_indicators = [
            'tests/', 'test/', 'testing/',
            'pytest.ini', 'tox.ini', 'setup.cfg',
            '.github/workflows/', 'conftest.py'
        ]
        
        url = f'{self.base_url}/repos/{repo_full_name}/contents'
        response = self.handle_request_with_retry(url)
        
        if not response:
            return True
        
        try:
            contents = response.json()
            
            if not isinstance(contents, list):
                return False
            
            root_files = [item.get('name', '') for item in contents if isinstance(item, dict)]
            
            for indicator in test_indicators:
                if any(indicator in file_name for file_name in root_files):
                    return True
            
            for item in contents:
                if isinstance(item, dict) and item.get('name', '').startswith('test_'):
                    return True
                    
            return False
            
        except Exception:
            return True
    
    def analyze_pr_for_tests(self, files_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze PR files to determine if they contain NEW test cases being added"""
        test_file_patterns = [
            'test_', '_test.py', '/test/', '/tests/',
            'conftest.py', 'pytest', 'unittest'
        ]
        
        files = files_data['files']
        
        analysis = {
            'has_new_test_cases': False,
            'has_code_changes': False,
            'test_files_with_new_cases': [],
            'code_files': [],
            'new_test_files': [],
            'total_additions': files_data['total_additions'],
            'total_deletions': files_data['total_deletions'],
            'total_changes': files_data['total_changes'],
            'new_test_cases_count': 0,
            'test_file_changes': 0,
            'code_file_changes': 0,
            'test_additions_only': 0,
        }
        
        for file_info in files:
            filename = file_info.get('filename', '')
            status = file_info.get('status', '')
            file_changes = file_info.get('changes', 0)
            file_additions = file_info.get('additions', 0)
            file_deletions = file_info.get('deletions', 0)
            patch = file_info.get('patch', '')
            
            is_test_file = any(pattern in filename.lower() for pattern in test_file_patterns)
            
            if is_test_file:
                analysis['test_file_changes'] += file_changes
                analysis['test_additions_only'] += file_additions
                
                if status == 'added':
                    analysis['new_test_files'].append(filename)
                    analysis['has_new_test_cases'] = True
                    analysis['test_files_with_new_cases'].append({
                        'filename': filename,
                        'status': 'new_file',
                        'additions': file_additions,
                        'estimated_test_cases': self._estimate_test_cases_from_additions(file_additions)
                    })
                    analysis['new_test_cases_count'] += self._estimate_test_cases_from_additions(file_additions)
                
                elif status == 'modified' and file_additions > 0:
                    new_test_cases = self._count_new_test_cases_in_patch(patch)
                    if new_test_cases > 0:
                        analysis['has_new_test_cases'] = True
                        analysis['test_files_with_new_cases'].append({
                            'filename': filename,
                            'status': 'modified',
                            'additions': file_additions,
                            'deletions': file_deletions,
                            'estimated_test_cases': new_test_cases
                        })
                        analysis['new_test_cases_count'] += new_test_cases
            
            elif filename.endswith('.py'):
                analysis['has_code_changes'] = True
                analysis['code_files'].append(filename)
                analysis['code_file_changes'] += file_changes
        
        return analysis
    
    def _estimate_test_cases_from_additions(self, additions: int) -> int:
        """Estimate number of test cases from line additions in new test files"""
        if additions < 5:
            return 0
        return max(1, additions // 7)
    
    def _count_new_test_cases_in_patch(self, patch: str) -> int:
        """Count new test cases being added by analyzing the patch/diff"""
        if not patch:
            return 0
        
        new_test_cases = 0
        lines = patch.split('\n')
        
        test_function_patterns = [
            r'^\+\s*def test_',
            r'^\+\s*async def test_',
            r'^\+\s*def.*test.*\(',
            r'^\+\s*class Test',
            r'^\+\s*@pytest\.mark\.',
            r'^\+\s*@unittest\.'
        ]
        
        for line in lines:
            for pattern in test_function_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    if 'def test_' in line.lower() or 'async def test_' in line.lower():
                        new_test_cases += 1
                    elif 'class test' in line.lower():
                        new_test_cases += 3
                    elif '@pytest.mark' in line.lower() or '@unittest' in line.lower():
                        new_test_cases += 0.5
                    break
        
        return int(new_test_cases)
    
    def find_active_test_repos(self, min_stars: int = 50, days_back: int = 60, 
                              min_test_prs: int = 1, max_repos: int = 500, 
                              target_prs: int = 2000, skip_processed: bool = True,
                              max_size_mb: int = 100) -> List[Dict]:
        """Find repositories with active testing based on recent PRs"""
        print(f"🔍 Searching for Python repositories with {min_stars}+ stars and < {max_size_mb}MB...")
        repos = self.search_python_repos(min_stars, days_back, max_repos, max_size_mb)
        print(f"📊 Found {len(repos)} repositories to analyze")
        
        if skip_processed:
            original_count = len(repos)
            repos = [repo for repo in repos if not self.is_repo_processed(repo['full_name'])]
            skipped = original_count - len(repos)
            if skipped > 0:
                print(f"⏭️  Skipping {skipped} previously processed repositories")
                print(f"📋 {len(repos)} repositories remaining to analyze")
        
        all_test_prs = []
        processed_repos = 0
        
        for i, repo in enumerate(repos):
            repo_name = repo['full_name']
            repo_size_kb = repo.get('size', 0)
            print(f"🔍 Analyzing {i+1}/{len(repos)}: {repo_name} ({repo_size_kb/1024:.1f}MB) - Found {len(all_test_prs)} PRs so far")
            
            if repo_size_kb > max_size_mb * 1024:
                print(f"    ❌ Repository too large ({repo_size_kb/1024:.1f}MB)")
                self.mark_repo_processed(repo_name, 0, repo_size_kb)
                continue
            
            if not self.has_testing_suite(repo_name):
                print(f"    ❌ No testing suite found")
                self.mark_repo_processed(repo_name, 0, repo_size_kb)
                continue
            
            merged_prs = self.get_recent_merged_prs(repo_name, days_back, 200)
            if not merged_prs:
                print(f"    ❌ No recent merged PRs")
                self.mark_repo_processed(repo_name, 0, repo_size_kb)
                continue
            
            repo_test_prs = []
            
            for pr in merged_prs:
                files_data = self.get_pr_files_with_stats(repo_name, pr['number'])
                if not files_data['files']:
                    continue
                    
                analysis = self.analyze_pr_for_tests(files_data)
                
                if analysis['has_new_test_cases'] and analysis['has_code_changes'] and analysis['new_test_cases_count'] > 0:
                    pr_data = {
                        'repository': repo,
                        'pr': pr,
                        'analysis': analysis
                    }
                    repo_test_prs.append(pr_data)
                    all_test_prs.append(pr_data)
                    self._update_live_outputs(pr_data)
            
            self.mark_repo_processed(repo_name, len(repo_test_prs), repo_size_kb)
            
            if repo_test_prs:
                processed_repos += 1
                total_changes = sum(pr_data['analysis']['total_changes'] for pr_data in repo_test_prs)
                print(f"    ✅ Found {len(repo_test_prs)} PRs with test changes ({total_changes} total line changes)")
            else:
                print(f"    ❌ No PRs with test changes found")
            
            if (i + 1) % 10 == 0:
                self.save_cache()
            
            time.sleep(0.2)
            
            if (i + 1) % 50 == 0:
                self.check_rate_limit()
            
            if len(all_test_prs) >= target_prs:
                print(f"\n🎯 Target reached! Found {len(all_test_prs)} PRs from {processed_repos} repositories")
                print(f"⚠️ Continuing to process remaining repositories to find more PRs...")
        
        self.save_cache()
        
        return all_test_prs
    
    def export_to_csv(self, test_prs: List[Dict], filename: str):
        """Export results to CSV format with enhanced data"""
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'repo_name', 'repo_url', 'repo_stars', 'repo_size_mb', 'repo_description',
                'pr_number', 'pr_title', 'pr_url', 'pr_merged_at',
                'total_lines_changed', 'total_additions', 'total_deletions',
                'new_test_cases_count', 'test_files_with_new_cases', 'test_additions_only',
                'code_files_changed', 'new_test_files_added',
                'test_file_line_changes', 'code_file_line_changes',
                'test_files_list', 'code_files_list'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for pr_data in test_prs:
                repo = pr_data['repository']
                pr = pr_data['pr']
                analysis = pr_data['analysis']
                
                row = {
                    'repo_name': repo['full_name'],
                    'repo_url': repo['html_url'],
                    'repo_stars': repo['stargazers_count'],
                    'repo_size_mb': round(repo.get('size', 0) / 1024, 2),
                    'repo_description': (repo.get('description') or '').replace('\n', ' ').replace('\r', ' '),
                    'pr_number': pr['number'],
                    'pr_title': pr['title'].replace('\n', ' ').replace('\r', ' '),
                    'pr_url': pr['html_url'],
                    'pr_merged_at': pr['merged_at'],
                    'total_lines_changed': analysis['total_changes'],
                    'total_additions': analysis['total_additions'],
                    'total_deletions': analysis['total_deletions'],
                    'new_test_cases_count': analysis['new_test_cases_count'],
                    'test_files_with_new_cases': len(analysis['test_files_with_new_cases']),
                    'test_additions_only': analysis['test_additions_only'],
                    'code_files_changed': len(analysis['code_files']),
                    'new_test_files_added': len(analysis['new_test_files']),
                    'test_file_line_changes': analysis['test_file_changes'],
                    'code_file_line_changes': analysis['code_file_changes'],
                    'test_files_list': '; '.join([tf['filename'] for tf in analysis['test_files_with_new_cases']]),
                    'code_files_list': '; '.join(analysis['code_files'][:10])
                }
                
                writer.writerow(row)
        
        print(f"📊 Enhanced CSV report saved to {filename}")
    
    def export_to_txt(self, test_prs: List[Dict], filename: str):
        """Export results to TXT format with enhanced data"""
        with open(filename, 'w', encoding='utf-8') as txtfile:
            txtfile.write("GitHub Python Test Repository Analysis Results (Enhanced)\n")
            txtfile.write("=" * 60 + "\n")
            txtfile.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            txtfile.write(f"Total PRs found: {len(test_prs)}\n\n")
            
            current_repo = None
            repo_count = 0
            
            for pr_data in test_prs:
                repo = pr_data['repository']
                pr = pr_data['pr']
                analysis = pr_data['analysis']
                
                if current_repo != repo['full_name']:
                    current_repo = repo['full_name']
                    repo_count += 1
                    txtfile.write(f"\n{repo_count}. REPOSITORY: {repo['full_name']}\n")
                    txtfile.write(f"   URL: {repo['html_url']}\n")
                    txtfile.write(f"   Stars: {repo['stargazers_count']}\n")
                    txtfile.write(f"   Size: {repo.get('size', 0)/1024:.2f} MB\n")
                    txtfile.write(f"   Description: {repo.get('description', 'N/A')}\n")
                    txtfile.write("   " + "-" * 50 + "\n")
                
                txtfile.write(f"   PR #{pr['number']}: {pr['title']}\n")
                txtfile.write(f"   URL: {pr['html_url']}\n")
                txtfile.write(f"   Merged: {pr['merged_at']}\n")
                txtfile.write(f"   Total lines changed: {analysis['total_changes']} (+{analysis['total_additions']}/-{analysis['total_deletions']})\n")
                txtfile.write(f"   New test cases: {analysis['new_test_cases_count']}\n")
                txtfile.write(f"   Test files changed: {len(analysis['test_files_with_new_cases'])} ({analysis['test_file_changes']} lines)\n")
                txtfile.write(f"   Code files changed: {len(analysis['code_files'])} ({analysis['code_file_changes']} lines)\n")
                if analysis['new_test_files']:
                    txtfile.write(f"   New test files: {len(analysis['new_test_files'])}\n")
                txtfile.write("\n")
        
        print(f"📄 Enhanced TXT report saved to {filename}")
    
    def export_to_json(self, test_prs: List[Dict], filename: str):
        """Export results to JSON format"""
        export_data = {
            'generated_at': datetime.now().isoformat(),
            'total_prs': len(test_prs),
            'unique_repos': len(set(pr_data['repository']['full_name'] for pr_data in test_prs)),
            'data': []
        }
        
        for pr_data in test_prs:
            repo = pr_data['repository']
            pr = pr_data['pr']
            analysis = pr_data['analysis']
            
            export_data['data'].append({
                'repository': {
                    'name': repo['full_name'],
                    'url': repo['html_url'],
                    'stars': repo['stargazers_count'],
                    'size_mb': round(repo.get('size', 0) / 1024, 2),
                    'description': repo.get('description', '')
                },
                'pull_request': {
                    'number': pr['number'],
                    'title': pr['title'],
                    'url': pr['html_url'],
                    'merged_at': pr['merged_at']
                },
                'analysis': analysis
            })
        
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            json.dump(export_data, jsonfile, indent=2, ensure_ascii=False)
        
        print(f"📝 JSON report saved to {filename}")
    
    def generate_summary_report(self, test_prs: List[Dict]):
        """Generate enhanced summary statistics"""
        if not test_prs:
            print("No data to summarize")
            return
        
        unique_repos = set(pr_data['repository']['full_name'] for pr_data in test_prs)
        
        total_test_files = sum(len(pr_data['analysis']['test_files_with_new_cases']) for pr_data in test_prs)
        total_code_files = sum(len(pr_data['analysis']['code_files']) for pr_data in test_prs)
        total_new_test_files = sum(len(pr_data['analysis']['new_test_files']) for pr_data in test_prs)
        total_line_changes = sum(pr_data['analysis']['total_changes'] for pr_data in test_prs)
        total_additions = sum(pr_data['analysis']['total_additions'] for pr_data in test_prs)
        total_deletions = sum(pr_data['analysis']['total_deletions'] for pr_data in test_prs)
        
        repo_sizes = [pr_data['repository'].get('size', 0) / 1024 for pr_data in test_prs]
        avg_repo_size = sum(repo_sizes) / len(repo_sizes) if repo_sizes else 0
        
        repo_pr_count = {}
        for pr_data in test_prs:
            repo_name = pr_data['repository']['full_name']
            repo_pr_count[repo_name] = repo_pr_count.get(repo_name, 0) + 1
        
        top_repos = sorted(repo_pr_count.items(), key=lambda x: x[1], reverse=True)[:10]
        
        print(f"\n📈 ENHANCED SUMMARY STATISTICS")
        print("=" * 60)
        print(f"Total PRs with test changes: {len(test_prs)}")
        print(f"Unique repositories: {len(unique_repos)}")
        print(f"Average repository size: {avg_repo_size:.2f} MB")
        print(f"Total test files modified: {total_test_files}")
        print(f"Total code files modified: {total_code_files}")
        print(f"Total new test files added: {total_new_test_files}")
        print(f"Total line changes: {total_line_changes:,} (+{total_additions:,}/-{total_deletions:,})")
        print(f"Average lines per PR: {total_line_changes / len(test_prs):.1f}")
        print(f"Average PRs per repo: {len(test_prs) / len(unique_repos):.1f}")
        
        print(f"\n🏆 TOP 10 REPOSITORIES BY TEST PR COUNT:")
        for i, (repo_name, count) in enumerate(top_repos, 1):
            print(f"{i:2d}. {repo_name}: {count} PRs")
        
        return {
            'total_prs': len(test_prs),
            'unique_repos': len(unique_repos),
            'avg_repo_size_mb': avg_repo_size,
            'total_test_files': total_test_files,
            'total_code_files': total_code_files,
            'total_new_test_files': total_new_test_files,
            'total_line_changes': total_line_changes,
            'total_additions': total_additions,
            'total_deletions': total_deletions,
            'avg_lines_per_pr': total_line_changes / len(test_prs) if test_prs else 0,
            'top_repositories': top_repos
        }

def main():
    parser = argparse.ArgumentParser(description='Find Python repositories with active testing (Enhanced)')
    parser.add_argument('--token', help='GitHub personal access token (recommended)')
    parser.add_argument('--min-stars', type=int, default=50, help='Minimum stars (default: 50)')
    parser.add_argument('--days-back', type=int, default=60, help='Days to look back for PRs (default: 60)')
    parser.add_argument('--min-test-prs', type=int, default=1, help='Minimum test PRs per repo (default: 1)')
    parser.add_argument('--max-repos', type=int, default=500, help='Maximum repositories to analyze (default: 500)')
    parser.add_argument('--target-prs', type=int, default=2000, help='Target number of PRs to find (default: 2000)')
    parser.add_argument('--max-size-mb', type=int, default=100, help='Maximum repository size in MB (default: 100)')
    parser.add_argument('--output-format', choices=['csv', 'txt', 'json', 'all'], default='all', 
                       help='Output format (default: all)')
    parser.add_argument('--output-prefix', default='github_test_repos', help='Output file prefix (default: github_test_repos)')
    parser.add_argument('--cache-file', default='repo_cache.pkl', help='Cache file name (default: repo_cache.pkl)')
    parser.add_argument('--skip-processed', action='store_true', default=True, 
                       help='Skip previously processed repositories (default: True)')
    parser.add_argument('--no-skip-processed', action='store_false', dest='skip_processed',
                       help='Process all repositories, ignoring cache')
    parser.add_argument('--clear-cache', action='store_true', help='Clear the cache before starting')
    parser.add_argument('--summary-only', action='store_true', help='Only show summary statistics')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--live-output', action='store_true', default=True, 
                       help='Enable live updating of output files (default: True)')
    parser.add_argument('--no-live-output', action='store_false', dest='live_output',
                       help='Disable live output updates')
    
    args = parser.parse_args()
    
    print("🚀 GitHub Python Test Repository Finder (Enhanced)")
    print("=" * 60)
    print(f"Configuration:")
    print(f"  - Minimum stars: {args.min_stars}")
    print(f"  - Days back: {args.days_back}")
    print(f"  - Max repository size: {args.max_size_mb}MB")
    print(f"  - Target PRs: {args.target_prs}")
    print(f"  - Max repositories to analyze: {args.max_repos}")
    print(f"  - Output format: {args.output_format}")
    print(f"  - Skip processed repos: {args.skip_processed}")
    print(f"  - Live output updates: {args.live_output}")
    print(f"  - Cache file: {args.cache_file}")
    if args.token:
        print(f"  - Using GitHub token: {'*' * len(args.token[:4]) + args.token[:4]}")
    else:
        print("  - ⚠️  No GitHub token provided (rate limits will be lower)")
    print()
    
    try:
        finder = GitHubTestRepoFinder(token=args.token, cache_file=args.cache_file)
    except Exception as e:
        print(f"❌ Error initializing GitHub finder: {e}")
        return 1
    
    if args.clear_cache:
        finder.clear_cache()
        print("✅ Cache cleared\n")
    
    if args.live_output and not args.summary_only:
        output_formats = []
        if args.output_format == 'all':
            output_formats = ['csv', 'json', 'txt']
        else:
            output_formats = [args.output_format]
        
        finder.enable_live_output(args.output_prefix, output_formats)
        print()
    
    print("🔍 Checking GitHub API rate limit...")
    finder.check_rate_limit()
    print(f"📊 Rate limit remaining: {finder.rate_limit_remaining}")
    
    if finder.rate_limit_remaining < 100:
        print("⚠️  Warning: Low rate limit remaining. Consider using a GitHub token.")
        if not args.token:
            print("   You can create a token at: https://github.com/settings/tokens")
            response = input("Continue anyway? (y/N): ")
            if response.lower() != 'y':
                return 0
    print()
    
    try:
        start_time = time.time()
        print(f"🔍 Starting search for repositories with active testing...")
        
        test_prs = finder.find_active_test_repos(
            min_stars=args.min_stars,
            days_back=args.days_back,
            min_test_prs=args.min_test_prs,
            max_repos=args.max_repos,
            target_prs=args.target_prs,
            skip_processed=args.skip_processed,
            max_size_mb=args.max_size_mb
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"\n✅ Analysis completed in {duration/60:.1f} minutes")
        print(f"📊 Found {len(test_prs)} PRs with test changes")
        
        if not test_prs:
            print("❌ No repositories with test changes found. Try adjusting your criteria:")
            print("   - Lower --min-stars")
            print("   - Increase --days-back")
            print("   - Increase --max-size-mb")
            print("   - Increase --max-repos")
            return 0
        
        summary_stats = finder.generate_summary_report(test_prs)
        
        if not args.summary_only:
            if args.live_output:
                print(f"\n📁 Live output files were updated during analysis:")
                for format_type, filename in finder.output_files.items():
                    print(f"   {format_type.upper()}: {filename}")
            else:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                if args.output_format in ['csv', 'all']:
                    csv_filename = f"{args.output_prefix}_{timestamp}.csv"
                    finder.export_to_csv(test_prs, csv_filename)
                
                if args.output_format in ['txt', 'all']:
                    txt_filename = f"{args.output_prefix}_{timestamp}.txt"
                    finder.export_to_txt(test_prs, txt_filename)
                
                if args.output_format in ['json', 'all']:
                    json_filename = f"{args.output_prefix}_{timestamp}.json"
                    finder.export_to_json(test_prs, json_filename)
                
                print(f"\n📁 Results exported with timestamp: {timestamp}")
        
        finder.save_cache()
        
        print(f"\n🎉 Process completed successfully!")
        print(f"   - Found {len(test_prs)} PRs from {summary_stats['unique_repos']} repositories")
        print(f"   - Total line changes analyzed: {summary_stats['total_line_changes']:,}")
        print(f"   - Average repository size: {summary_stats['avg_repo_size_mb']:.2f}MB")
        
        return 0
        
    except KeyboardInterrupt:
        print(f"\n⚠️  Process interrupted by user")
        print("💾 Saving current progress to cache...")
        finder.save_cache()
        return 130
        
    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        
        try:
            finder.save_cache()
        except:
            pass
        
        return 1

if __name__ == '__main__':
    exit(main())
