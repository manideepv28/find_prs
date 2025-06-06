#!/usr/bin/env python3
"""
GitHub Python Repository Finder with Active Testing
Searches for Python repositories with recent merged PRs containing test changes
Enhanced with persistence to avoid rechecking repositories
"""

import requests
import json
import csv
import time
import os
import pickle
from datetime import datetime, timedelta
from typing import List, Dict, Any, Set
import argparse
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
        
        # Cache management
        self.cache_file = cache_file
        self.processed_repos: Set[str] = set()
        self.repo_metadata: Dict[str, Dict] = {}
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
    
    def is_repo_processed(self, repo_name: str, max_age_days: int = 7) -> bool:
        """Check if repository was recently processed"""
        if repo_name not in self.processed_repos:
            return False
        
        # Check if we have metadata and if it's recent enough
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
    
    def mark_repo_processed(self, repo_name: str, found_prs: int = 0):
        """Mark repository as processed"""
        self.processed_repos.add(repo_name)
        self.repo_metadata[repo_name] = {
            'last_processed': datetime.now().isoformat(),
            'prs_found': found_prs
        }
    
    def search_python_repos(self, min_stars: int = 100, days_back: int = 30, max_repos: int = 1000) -> List[Dict]:
        """Search for popular Python repositories with pagination"""
        since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        query = f'language:python stars:>={min_stars} pushed:>={since_date}'
        
        url = f'{self.base_url}/search/repositories'
        all_repos = []
        page = 1
        
        while len(all_repos) < max_repos:
            params = {
                'q': query,
                'sort': 'updated',
                'order': 'desc',
                'per_page': 100,
                'page': page
            }
            
            try:
                response = self.session.get(url, params=params)
                if response.status_code == 403:
                    print("⚠️  Rate limit exceeded. Waiting 60 seconds...")
                    time.sleep(60)
                    continue
                
                response.raise_for_status()
                data = response.json()
                items = data.get('items', [])
                
                if not items:
                    break
                    
                all_repos.extend(items)
                page += 1
                
                # GitHub search API has 1000 result limit
                if len(items) < 100 or page > 10:
                    break
                    
                time.sleep(0.5)  # More conservative rate limiting
                
            except requests.exceptions.RequestException as e:
                print(f"Error searching repositories: {e}")
                break
        
        return all_repos[:max_repos]
    
    def get_recent_merged_prs(self, repo_full_name: str, days_back: int = 30, max_prs: int = 100) -> List[Dict]:
        """Get recently merged pull requests for a repository with pagination"""
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
            
            try:
                response = self.session.get(url, params=params)
                if response.status_code == 403:
                    print(f"⚠️  Rate limit exceeded for {repo_full_name}. Waiting...")
                    time.sleep(60)
                    continue
                elif response.status_code == 404:
                    print(f"⚠️  Repository {repo_full_name} not found or not accessible")
                    break
                
                response.raise_for_status()
                prs = response.json()
                
                if not prs:
                    break
                
                # Filter for merged PRs within the time window
                merged_prs = []
                for pr in prs:
                    merged_at = pr.get('merged_at')
                    if merged_at and merged_at >= since_date:
                        merged_prs.append(pr)
                    elif merged_at and merged_at < since_date:
                        # PRs are sorted by update time, so we can stop if we hit old PRs
                        break
                
                all_prs.extend(merged_prs)
                page += 1
                
                # If we got fewer results than requested, we've reached the end
                if len(prs) < 100:
                    break
                    
                time.sleep(0.2)  # Rate limiting
                
            except requests.exceptions.RequestException as e:
                print(f"Error getting PRs for {repo_full_name}: {e}")
                break
        
        return all_prs[:max_prs]
    
    def get_pr_files(self, repo_full_name: str, pr_number: int) -> List[Dict]:
        """Get files changed in a pull request"""
        url = f'{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/files'
        
        try:
            response = self.session.get(url)
            if response.status_code == 403:
                print(f"⚠️  Rate limit exceeded for PR files. Waiting...")
                time.sleep(60)
                response = self.session.get(url)
            elif response.status_code == 404:
                return []
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error getting PR files for {repo_full_name}#{pr_number}: {e}")
            return []
    
    def has_testing_suite(self, repo_full_name: str) -> bool:
        """Check if repository has testing suite"""
        test_indicators = [
            'tests/', 'test/', 'testing/',
            'pytest.ini', 'tox.ini', 'setup.cfg',
            '.github/workflows/', 'conftest.py'
        ]
        
        url = f'{self.base_url}/repos/{repo_full_name}/contents'
        
        try:
            response = self.session.get(url)
            if response.status_code == 403:
                print(f"⚠️  Rate limit exceeded checking test suite. Waiting...")
                time.sleep(60)
                response = self.session.get(url)
            elif response.status_code == 404:
                return False
            
            response.raise_for_status()
            contents = response.json()
            
            # Ensure contents is a list
            if not isinstance(contents, list):
                return False
            
            # Check root directory for test indicators
            root_files = [item.get('name', '') for item in contents if isinstance(item, dict)]
            
            for indicator in test_indicators:
                if any(indicator in file_name for file_name in root_files):
                    return True
            
            # Also check for common test file patterns
            for item in contents:
                if isinstance(item, dict) and item.get('name', '').startswith('test_'):
                    return True
                    
            return False
            
        except requests.exceptions.RequestException:
            # If we can't access contents, assume it might have tests
            return True
    
    def analyze_pr_for_tests(self, files: List[Dict]) -> Dict[str, Any]:
        """Analyze PR files to determine if they contain test changes"""
        test_file_patterns = [
            'test_', '_test.py', '/test/', '/tests/',
            'conftest.py', 'pytest', 'unittest'
        ]
        
        analysis = {
            'has_test_changes': False,
            'has_code_changes': False,
            'test_files': [],
            'code_files': [],
            'new_test_files': []
        }
        
        for file_info in files:
            filename = file_info.get('filename', '')
            status = file_info.get('status', '')
            
            # Check for test files
            is_test_file = any(pattern in filename.lower() for pattern in test_file_patterns)
            if is_test_file:
                analysis['has_test_changes'] = True
                analysis['test_files'].append(filename)
                if status == 'added':
                    analysis['new_test_files'].append(filename)
            
            # Check for code files (non-test Python files)
            elif filename.endswith('.py'):
                analysis['has_code_changes'] = True
                analysis['code_files'].append(filename)
        
        return analysis
    
    def find_active_test_repos(self, min_stars: int = 50, days_back: int = 60, 
                              min_test_prs: int = 1, max_repos: int = 500, 
                              target_prs: int = 2000, skip_processed: bool = True) -> List[Dict]:
        """Find repositories with active testing based on recent PRs"""
        print(f"🔍 Searching for Python repositories with {min_stars}+ stars...")
        repos = self.search_python_repos(min_stars, days_back, max_repos)
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
            print(f"🔍 Analyzing {i+1}/{len(repos)}: {repo_name} (Found {len(all_test_prs)} PRs so far)")
            
            # Check if repo has testing suite
            if not self.has_testing_suite(repo_name):
                print(f"    ❌ No testing suite found")
                self.mark_repo_processed(repo_name, 0)
                continue
            
            # Get recent merged PRs
            merged_prs = self.get_recent_merged_prs(repo_name, days_back, 50)
            if not merged_prs:
                print(f"    ❌ No recent merged PRs")
                self.mark_repo_processed(repo_name, 0)
                continue
            
            repo_test_prs = []
            
            # Analyze each PR for test changes
            for pr in merged_prs:
                if len(all_test_prs) >= target_prs:
                    break
                    
                pr_files = self.get_pr_files(repo_name, pr['number'])
                if not pr_files:
                    continue
                    
                analysis = self.analyze_pr_for_tests(pr_files)
                
                if analysis['has_test_changes'] and analysis['has_code_changes']:
                    pr_data = {
                        'repository': repo,
                        'pr': pr,
                        'analysis': analysis
                    }
                    repo_test_prs.append(pr_data)
                    all_test_prs.append(pr_data)
            
            # Mark repository as processed
            self.mark_repo_processed(repo_name, len(repo_test_prs))
            
            if repo_test_prs:
                processed_repos += 1
                print(f"    ✅ Found {len(repo_test_prs)} PRs with test changes")
            else:
                print(f"    ❌ No PRs with test changes found")
            
            # Save cache periodically
            if (i + 1) % 10 == 0:
                self.save_cache()
            
            # Rate limiting
            time.sleep(0.2)
            
            # Stop if we've reached our target
            if len(all_test_prs) >= target_prs:
                print(f"\n🎯 Target reached! Found {len(all_test_prs)} PRs from {processed_repos} repositories")
                break
        
        # Save final cache
        self.save_cache()
        
        return all_test_prs
    
    def export_to_csv(self, test_prs: List[Dict], filename: str):
        """Export results to CSV format"""
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'repo_name', 'repo_url', 'repo_stars', 'repo_description',
                'pr_number', 'pr_title', 'pr_url', 'pr_merged_at',
                'test_files_changed', 'code_files_changed', 'new_test_files_added',
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
                    'repo_description': (repo.get('description') or '').replace('\n', ' ').replace('\r', ' '),
                    'pr_number': pr['number'],
                    'pr_title': pr['title'].replace('\n', ' ').replace('\r', ' '),
                    'pr_url': pr['html_url'],
                    'pr_merged_at': pr['merged_at'],
                    'test_files_changed': len(analysis['test_files']),
                    'code_files_changed': len(analysis['code_files']),
                    'new_test_files_added': len(analysis['new_test_files']),
                    'test_files_list': '; '.join(analysis['test_files']),
                    'code_files_list': '; '.join(analysis['code_files'][:10])  # Limit to avoid very long strings
                }
                
                writer.writerow(row)
        
        print(f"📊 CSV report saved to {filename}")
    
    def export_to_txt(self, test_prs: List[Dict], filename: str):
        """Export results to TXT format"""
        with open(filename, 'w', encoding='utf-8') as txtfile:
            txtfile.write("GitHub Python Test Repository Analysis Results\n")
            txtfile.write("=" * 50 + "\n")
            txtfile.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            txtfile.write(f"Total PRs found: {len(test_prs)}\n\n")
            
            current_repo = None
            repo_count = 0
            
            for pr_data in test_prs:
                repo = pr_data['repository']
                pr = pr_data['pr']
                analysis = pr_data['analysis']
                
                # New repository section
                if current_repo != repo['full_name']:
                    current_repo = repo['full_name']
                    repo_count += 1
                    txtfile.write(f"\n{repo_count}. REPOSITORY: {repo['full_name']}\n")
                    txtfile.write(f"   URL: {repo['html_url']}\n")
                    txtfile.write(f"   Stars: {repo['stargazers_count']}\n")
                    txtfile.write(f"   Description: {repo.get('description', 'N/A')}\n")
                    txtfile.write("   " + "-" * 40 + "\n")
                
                # PR details
                txtfile.write(f"   PR #{pr['number']}: {pr['title']}\n")
                txtfile.write(f"   URL: {pr['html_url']}\n")
                txtfile.write(f"   Merged: {pr['merged_at']}\n")
                txtfile.write(f"   Test files changed: {len(analysis['test_files'])}\n")
                txtfile.write(f"   Code files changed: {len(analysis['code_files'])}\n")
                if analysis['new_test_files']:
                    txtfile.write(f"   New test files: {len(analysis['new_test_files'])}\n")
                txtfile.write("\n")
        
        print(f"📄 TXT report saved to {filename}")
    
    def generate_summary_report(self, test_prs: List[Dict]):
        """Generate summary statistics"""
        if not test_prs:
            print("No data to summarize")
            return
        
        # Count unique repositories
        unique_repos = set(pr_data['repository']['full_name'] for pr_data in test_prs)
        
        # Calculate statistics
        total_test_files = sum(len(pr_data['analysis']['test_files']) for pr_data in test_prs)
        total_code_files = sum(len(pr_data['analysis']['code_files']) for pr_data in test_prs)
        total_new_test_files = sum(len(pr_data['analysis']['new_test_files']) for pr_data in test_prs)
        
        # Top repositories by PR count
        repo_pr_count = {}
        for pr_data in test_prs:
            repo_name = pr_data['repository']['full_name']
            repo_pr_count[repo_name] = repo_pr_count.get(repo_name, 0) + 1
        
        top_repos = sorted(repo_pr_count.items(), key=lambda x: x[1], reverse=True)[:10]
        
        print(f"\n📈 SUMMARY STATISTICS")
        print("=" * 50)
        print(f"Total PRs with test changes: {len(test_prs)}")
        print(f"Unique repositories: {len(unique_repos)}")
        print(f"Total test files modified: {total_test_files}")
        print(f"Total code files modified: {total_code_files}")
        print(f"Total new test files added: {total_new_test_files}")
        print(f"Average PRs per repo: {len(test_prs) / len(unique_repos):.1f}")
        
        print(f"\n🏆 TOP 10 REPOSITORIES BY TEST PR COUNT:")
        for i, (repo_name, count) in enumerate(top_repos, 1):
            print(f"{i:2d}. {repo_name}: {count} PRs")
        
        return {
            'total_prs': len(test_prs),
            'unique_repos': len(unique_repos),
            'total_test_files': total_test_files,
            'total_code_files': total_code_files,
            'total_new_test_files': total_new_test_files,
            'top_repositories': top_repos
        }
    
    def clear_cache(self):
        """Clear the repository cache"""
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
            print(f"🗑️  Cache file {self.cache_file} deleted")
        self.processed_repos = set()
        self.repo_metadata = {}

def main():
    parser = argparse.ArgumentParser(description='Find Python repositories with active testing')
    parser.add_argument('--token', help='GitHub personal access token')
    parser.add_argument('--min-stars', type=int, default=50, help='Minimum stars (default: 50)')
    parser.add_argument('--days-back', type=int, default=60, help='Days to look back (default: 60)')
    parser.add_argument('--target-prs', type=int, default=2000, help='Target number of PRs to find (default: 2000)')
    parser.add_argument('--max-repos', type=int, default=500, help='Maximum repositories to analyze (default: 500)')
    parser.add_argument('--output-csv', default='github_test_prs.csv', help='Output CSV file path')
    parser.add_argument('--output-txt', default='github_test_prs.txt', help='Output TXT file path')
    parser.add_argument('--output-json', help='Output JSON file path (optional)')
    parser.add_argument('--cache-file', default='repo_cache.pkl', help='Cache file path (default: repo_cache.pkl)')
    parser.add_argument('--clear-cache', action='store_true', help='Clear the repository cache before running')
    parser.add_argument('--no-skip-processed', action='store_true', help='Don\'t skip previously processed repositories')
    
    args = parser.parse_args()
    
    if not args.token:
        print("⚠️  Warning: No GitHub token provided. You may hit rate limits quickly.")
        print("   Generate a token at: https://github.com/settings/tokens")
        print("   Use: python script.py --token YOUR_TOKEN")
        response = input("Continue without token? (y/N): ")
        if response.lower() != 'y':
            return
    
    finder = GitHubTestRepoFinder(args.token, args.cache_file)
    
    if args.clear_cache:
        finder.clear_cache()
    
    print("🔍 GitHub Python Test Repository Finder")
    print(f"📊 Searching for repos with {args.min_stars}+ stars")
    print(f"📅 Looking back {args.days_back} days")
    print(f"🎯 Target: {args.target_prs} PRs with test changes")
    print(f"🏢 Max repositories to analyze: {args.max_repos}")
    print(f"💾 Cache file: {args.cache_file}")
    print(f"⏭️  Skip processed repos: {not args.no_skip_processed}\n")
    
    start_time = time.time()
    
    test_prs = finder.find_active_test_repos(
        min_stars=args.min_stars,
        days_back=args.days_back,
        min_test_prs=1,
        max_repos=args.max_repos,
        target_prs=args.target_prs,
        skip_processed=not args.no_skip_processed
    )
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"\n⏱️  Analysis completed in {duration:.1f} seconds")
    
    if test_prs:
        # Generate summary
        summary = finder.generate_summary_report(test_prs)
        
        # Export to different formats
        finder.export_to_csv(test_prs, args.output_csv)
        finder.export_to_txt(test_prs, args.output_txt)
        
        if args.output_json:
            with open(args.output_json, 'w') as f:
                json.dump({
                    'summary': summary,
                    'prs': [{
                        'repository': pr_data['repository'],
                        'pr': pr_data['pr'],
                        'analysis': pr_data['analysis']
                    } for pr_data in test_prs]
                }, f, indent=2)
            print(f"📋 JSON report saved to {args.output_json}")
    else:
        print("❌ No PRs with test changes found!")
    
    print(f"\n✅ Analysis complete! Found {len(test_prs)} PRs with test changes")

if __name__ == "__main__":
    main()
