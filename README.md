# Find_Prs

---

## ✅ **Basic Setup**

Save the script as a Python file, for example:

```bash
github_finder.py
```

Ensure you have **Python 3** and **`requests`** installed:

```bash
pip install requests
```

---

## 🔑 **GitHub Token Requirement**

For larger scans, you need a GitHub Personal Access Token (PAT) to **avoid hitting rate limits**.

Generate one at:
👉 [https://github.com/settings/tokens](https://github.com/settings/tokens)
(Enable scopes like `repo` and `read:org` if needed.)

---

## 🚀 **Basic Usage**

```bash
python github_finder.py --token YOUR_GITHUB_TOKEN
```

* Finds Python repos with at least 50 stars.
* Looks at merged PRs from the last 60 days.
* Stops after finding 2000 PRs with test + code changes.
* Saves:

  * CSV: `github_test_prs.csv`
  * TXT: `github_test_prs.txt`

---

## 🛠️ **Custom Usage Examples**

### 🔍 Custom Search Filters

```bash
python github_finder.py --token YOUR_TOKEN \
  --min-stars 100 \
  --days-back 90 \
  --max-repos 300 \
  --target-prs 1000
```

* Finds more mature repos (100+ stars)
* Analyzes activity in the last 90 days
* Scans up to 300 repos
* Stops after 1000 test-including PRs

---

### 📁 Custom Output File Names

```bash
python github_finder.py --token YOUR_TOKEN \
  --output-csv python_tests.csv \
  --output-txt summary.txt \
  --output-json data_dump.json
```

* Saves results in:

  * `python_tests.csv`
  * `summary.txt`
  * `data_dump.json`

---

## 🧪 Parameters Reference

| Argument        | Description                                            |
| --------------- | ------------------------------------------------------ |
| `--token`       | GitHub PAT (required for most use cases)               |
| `--min-stars`   | Minimum stars for repos (default: 50)                  |
| `--days-back`   | Look back period in days (default: 60)                 |
| `--max-repos`   | Max number of repos to analyze (default: 500)          |
| `--target-prs`  | Stop when this many test PRs are found (default: 2000) |
| `--output-csv`  | Output CSV path (default: `github_test_prs.csv`)       |
| `--output-txt`  | Output TXT summary (default: `github_test_prs.txt`)    |
| `--output-json` | Output full data dump (optional)                       |

---

## 🧠 Summary of What It Does

1. **Finds active Python repos** (based on stars and recent commits).
2. **Checks for recent merged PRs**.
3. **Analyzes if PRs changed both test and code files**.
4. **Generates structured reports** in `.csv`, `.txt`, and optionally `.json`.

---
## **Advanced usage**

### **1. Persistence System**
- **Cache Management**: Added `repo_cache.pkl` file to store previously processed repositories
- **Smart Skipping**: Automatically skips repositories processed within the last 7 days (configurable)
- **Metadata Tracking**: Stores when each repo was processed and how many PRs were found

### **2. Better Error Handling**
- **Rate Limit Detection**: Properly handles 403 status codes (rate limits) with automatic retry
- **404 Handling**: Gracefully handles repositories that are deleted or made private
- **Data Validation**: Ensures API responses are in expected format before processing

### **3. Improved Rate Limiting**
- **Conservative Timing**: Increased sleep intervals to avoid hitting rate limits
- **Dynamic Waiting**: Waits 60 seconds when rate limits are detected
- **Periodic Saves**: Saves cache every 10 repositories to prevent data loss

### **4. Enhanced CLI Options**
- `--cache-file`: Specify custom cache file location
- `--clear-cache`: Clear existing cache before running
- `--no-skip-processed`: Force reprocessing of all repositories

### **5. Robustness Improvements**
- **Safe String Operations**: Fixed potential `None` value issues in descriptions
- **Better PR Filtering**: More efficient date-based filtering of merged PRs  
- **Type Safety**: Added proper type checking for API responses

