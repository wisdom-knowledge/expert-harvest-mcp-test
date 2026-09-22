---
name: github-feature-fuzzy-commit-trace-zip
version: 0.1.0
kind: flow-skill
interaction: stepwise
tags: [github, git, commits, fuzzy, trace, zip]
summary: 用功能关键词模糊匹配 GitHub 仓库相关提交，导出从首次到末次的 trace 并打成 ZIP。
---

# GitHub 功能模糊匹配提交 Trace ZIP

> 用户侧通过邀请码调用 **eh_collect_start** 进入交互；本文件只声明槽位与执行，不重复会话状态机。

## 目标

给定 GitHub 仓库与一个功能关键词（可模糊匹配），在指定分支上找出所有相关提交，导出从**第一次**到**最后一次**的 log 与每条 patch/trace，打成一个可审计的 zip。

匹配范围（不区分大小写）：

1. 提交说明（subject / body）；
2. 变更路径（文件名或目录片段）；
3. diff 文本（可用 `match_diff=0` 关掉，避免大仓库过慢）。

不复制无关工作树大文件；trace 以 git 文本产物为主。

## 输入

| 参数 | 必填 | 默认 | 说明 | 校验 |
|------|------|------|------|------|
| `github_url` | 是 | | GitHub 仓库地址（HTTPS 或 `git@`） | 非空；不要把 token 写进 URL |
| `feature_query` | 是 | | 功能关键词，模糊匹配提交说明、路径或 diff（如 `invite batch`、`支付回调`） | 非空；长度 1–200；不要含换行 |
| `ref` | 否 | 仓库默认分支 | 要分析的分支、tag 或 SHA（如 `main`） | 存在于仓库 |
| `output_dir` | 否 | `./out` | zip 与 clone 工作区根目录 | 非 `/`；可写 |
| `repo_path` | 否 | | 已有本地仓库；提供则复用，不再 clone | 须含 `.git` |
| `zip_name` | 否 | `feature-commit-trace.zip` | zip 文件名（不含目录） | 不含 `/` `\` `..` |
| `match_diff` | 否 | `1` | `1` 同时在 diff 文本里模糊匹配；`0` 只匹配说明与路径 | `0`\|`1` |
| `include_full_patches` | 否 | `1` | `1` 导出每条完整 patch；`0` 只导出 stat/summary | `0`\|`1` |

## 执行步骤

在含 `git`、`zip`、`grep`、`awk`、`sed`、`date`、`sort` 的环境中执行。clone 只写入 `output_dir/.repos/`；不修改用户已有 `repo_path` 的工作树（可 fetch）。

```bash
set -euo pipefail

: "${github_url:?set github_url to an HTTPS or git@ GitHub URL}"
: "${feature_query:?set feature_query to a feature keyword}"

output_dir="${output_dir:-./out}"
zip_name="${zip_name:-feature-commit-trace.zip}"
match_diff="${match_diff:-1}"
include_full_patches="${include_full_patches:-1}"
ref="${ref:-}"

case "$output_dir" in /*) ;; *) output_dir="$PWD/$output_dir";; esac
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd -P)"
[[ "$output_dir" != "/" ]] || { echo "refuse output_dir=/" >&2; exit 1; }

case "$zip_name" in
  *..*|*/*|*\\*|'') echo "invalid zip_name: $zip_name" >&2; exit 1 ;;
esac
case "$match_diff" in 0|1) ;; *) echo "match_diff must be 0 or 1" >&2; exit 1 ;; esac
case "$include_full_patches" in 0|1) ;; *) echo "include_full_patches must be 0 or 1" >&2; exit 1 ;; esac

# strip CR; reject empty / multiline / overly long query
feature_query="$(printf '%s' "$feature_query" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
[[ -n "$feature_query" ]] || { echo "feature_query empty" >&2; exit 1; }
[[ "${#feature_query}" -le 200 ]] || { echo "feature_query longer than 200" >&2; exit 1; }
case "$feature_query" in
  *$'\n'*) echo "feature_query must be a single line" >&2; exit 1 ;;
esac

repo_name="$(basename -s .git "${github_url%/}")"
repo_name="$(printf '%s' "$repo_name" | sed 's/[^A-Za-z0-9._-]/_/g')"
repo_root="$output_dir/.repos/$repo_name"

if [[ -n "${repo_path:-}" ]]; then
  [[ -d "$repo_path/.git" ]] || { echo "repo_path is not a Git repository: $repo_path" >&2; exit 1; }
  repo_root="$(cd "$repo_path" && pwd -P)"
else
  mkdir -p "$output_dir/.repos"
  if [[ -d "$repo_root/.git" ]]; then
    git -C "$repo_root" fetch --all --prune
  else
    git clone --no-single-branch "$github_url" "$repo_root"
  fi
fi

git -C "$repo_root" fetch origin '+refs/heads/*:refs/remotes/origin/*' --prune 2>/dev/null || true

if [[ -z "$ref" ]]; then
  if git -C "$repo_root" show-ref --verify --quiet refs/remotes/origin/HEAD; then
    ref="$(git -C "$repo_root" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    ref="${ref#origin/}"
  fi
  if [[ -z "$ref" ]]; then
    ref="$(git -C "$repo_root" remote show origin 2>/dev/null | sed -n '/HEAD branch/s/.*: //p' || true)"
  fi
  if [[ -z "$ref" ]]; then
    ref="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)"
  fi
fi

tip_ref=""
for cand in "refs/remotes/origin/$ref" "refs/heads/$ref" "$ref"; do
  if git -C "$repo_root" rev-parse --verify --quiet "$cand" >/dev/null; then
    tip_ref="$cand"
    break
  fi
done
[[ -n "$tip_ref" ]] || { echo "ref not found: $ref" >&2; exit 1; }
tip_sha="$(git -C "$repo_root" rev-parse "$tip_ref")"

stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
work_root="$output_dir/feature-fuzzy-trace-$stamp"
pack_root="$work_root/pack"
meta_root="$pack_root/meta"
commits_root="$pack_root/commits"
patches_root="$pack_root/patches"
mkdir -p "$meta_root" "$commits_root" "$patches_root"

# fixed-string, case-insensitive; escape for git pickaxe (-S / -G treat pattern as regex)
query_fixed="$feature_query"
query_regex="$(printf '%s' "$feature_query" | sed -e 's/[.[\*^$()+?{|\\]/\\&/g')"

all_shas="$meta_root/all-shas.txt"
git -C "$repo_root" rev-list --reverse "$tip_sha" > "$all_shas"

msg_hits="$meta_root/hits-message.txt"
path_hits="$meta_root/hits-path.txt"
diff_hits="$meta_root/hits-diff.txt"
: > "$msg_hits"
: > "$path_hits"
: > "$diff_hits"

# 1) commit message (subject + body), case-insensitive fixed string
git -C "$repo_root" log --reverse --pretty=format:'%H' --regexp-ignore-case --fixed-strings \
  --grep="$query_fixed" "$tip_sha" > "$msg_hits" || true

# 2) changed path contains query (case-insensitive)
while IFS= read -r sha || [[ -n "${sha:-}" ]]; do
  [[ -z "${sha:-}" ]] && continue
  if git -C "$repo_root" diff-tree --no-commit-id --name-only -r "$sha" \
      | grep -F -i -q -- "$query_fixed"; then
    printf '%s\n' "$sha" >> "$path_hits"
  fi
done < "$all_shas"

# 3) optional diff text match (git pickaxe -G, case-insensitive regex of escaped query)
if [[ "$match_diff" == "1" ]]; then
  git -C "$repo_root" log --reverse --pretty=format:'%H' -i -G "$query_regex" "$tip_sha" > "$diff_hits" || true
fi

commits_file="$meta_root/commit-shas.txt"
cat "$msg_hits" "$path_hits" "$diff_hits" \
  | grep -E '^[0-9a-f]{7,40}$' \
  | awk '!seen[$0]++' > "$meta_root/commit-shas.unsorted" || true

# restore ancestry order (oldest → newest) using rev-list
: > "$commits_file"
if [[ -s "$meta_root/commit-shas.unsorted" ]]; then
  awk 'NR==FNR { want[$1]=1; next } ($1 in want) { print }' \
    "$meta_root/commit-shas.unsorted" "$all_shas" > "$commits_file"
fi

commit_count="$(wc -l < "$commits_file" | tr -d ' ')"
if [[ "$commit_count" -eq 0 ]]; then
  {
    echo "No commits matched feature_query under ref=$ref (tip=$tip_sha)"
    echo "query: $feature_query"
    echo "Try a shorter keyword, another ref, or match_diff=1"
  } >&2
  exit 1
fi

first_sha="$(head -n 1 "$commits_file")"
last_sha="$(tail -n 1 "$commits_file")"

# hit source per sha
{
  printf 'sha\tmessage\tpath\tdiff\n'
  while IFS= read -r sha || [[ -n "${sha:-}" ]]; do
    [[ -z "${sha:-}" ]] && continue
    m=0; p=0; d=0
    grep -qx "$sha" "$msg_hits" && m=1 || true
    grep -qx "$sha" "$path_hits" && p=1 || true
    grep -qx "$sha" "$diff_hits" && d=1 || true
    printf '%s\t%s\t%s\t%s\n' "$sha" "$m" "$p" "$d"
  done < "$commits_file"
} > "$meta_root/match-sources.tsv"

# logs constrained to matched SHAs (oldest → newest)
: > "$commits_root/commits.oneline.txt"
: > "$commits_root/commits.full.txt"
: > "$commits_root/name-status.txt"
while IFS= read -r sha || [[ -n "${sha:-}" ]]; do
  [[ -z "${sha:-}" ]] && continue
  git -C "$repo_root" log -1 --oneline "$sha" >> "$commits_root/commits.oneline.txt"
  {
    git -C "$repo_root" log -1 --pretty=fuller "$sha"
    echo
    git -C "$repo_root" show --stat --format= "$sha"
    echo
    printf '----- %s -----\n' "$sha"
  } >> "$commits_root/commits.full.txt"
  {
    printf '=== %s ' "$sha"
    git -C "$repo_root" log -1 --pretty=format:'%s' "$sha"
    echo
    git -C "$repo_root" diff-tree --no-commit-id --name-status -r "$sha"
    echo
  } >> "$commits_root/name-status.txt"
done < "$commits_file"

# authors among matched commits only
git -C "$repo_root" log --pretty=format:'%an' --no-walk=sorted $(cat "$commits_file") \
  | sort | uniq -c | sort -nr > "$commits_root/authors.txt"

# range stat between first and last matched commit (whole trees; informational)
if git -C "$repo_root" diff --stat "$first_sha"^ "$last_sha" > "$commits_root/diff.range.stat.txt" 2>/dev/null; then
  :
elif git -C "$repo_root" diff --stat "$first_sha" "$last_sha" > "$commits_root/diff.range.stat.txt" 2>/dev/null; then
  :
else
  printf 'diff range stat unavailable\n' > "$commits_root/diff.range.stat.txt"
fi

idx=0
printf 'idx\tsha\tsubject\tpatch_file\n' > "$meta_root/commit-index.tsv"
while IFS= read -r sha || [[ -n "${sha:-}" ]]; do
  [[ -z "${sha:-}" ]] && continue
  idx=$((idx + 1))
  printf -v idx_pad '%04d' "$idx"
  subject="$(git -C "$repo_root" log -1 --pretty=format:'%s' "$sha" | tr '\t' ' ' | tr -d '\r')"
  safe_subj="$(printf '%s' "$subject" | sed 's/[^A-Za-z0-9._-]\+/_/g' | cut -c1-60)"
  patch_name="${idx_pad}-${sha:0:12}-${safe_subj}.patch"
  meta_one="$commits_root/${idx_pad}-${sha:0:12}.txt"
  {
    git -C "$repo_root" log -1 --pretty=fuller "$sha"
    echo
    git -C "$repo_root" show --stat --format= "$sha"
  } > "$meta_one"
  if [[ "$include_full_patches" == "1" ]]; then
    git -C "$repo_root" show --find-renames --format=fuller "$sha" \
      > "$patches_root/$patch_name" \
      || printf 'patch unavailable for %s\n' "$sha" > "$patches_root/$patch_name"
  else
    git -C "$repo_root" show --stat --format=fuller "$sha" \
      > "$patches_root/$patch_name" || true
  fi
  printf '%s\t%s\t%s\t%s\n' "$idx_pad" "$sha" "$subject" "$patch_name" >> "$meta_root/commit-index.tsv"
done < "$commits_file"

{
  printf 'from=%s\n' "$first_sha"
  printf 'to=%s\n' "$last_sha"
  printf 'tip_ref=%s\n' "$tip_ref"
  printf 'tip_sha=%s\n' "$tip_sha"
  printf 'commit_count=%s\n' "$commit_count"
  printf 'feature_query=%s\n' "$feature_query"
} > "$meta_root/range.txt"

generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
{
  printf 'kind: github-feature-fuzzy-commit-trace-zip\n'
  printf 'github_url: %s\n' "$github_url"
  printf 'repo_root: %s\n' "$repo_root"
  printf 'ref: %s\n' "$ref"
  printf 'tip_ref: %s\n' "$tip_ref"
  printf 'tip_sha: %s\n' "$tip_sha"
  printf 'feature_query: %s\n' "$feature_query"
  printf 'match_diff: %s\n' "$match_diff"
  printf 'include_full_patches: %s\n' "$include_full_patches"
  printf 'first_sha: %s\n' "$first_sha"
  printf 'last_sha: %s\n' "$last_sha"
  printf 'commit_count: %s\n' "$commit_count"
  printf 'generated_at: %s\n' "$generated_at"
  printf 'files:\n'
  printf '  - SUMMARY.md\n'
  printf '  - commits/commits.oneline.txt\n'
  printf '  - commits/commits.full.txt\n'
  printf '  - commits/authors.txt\n'
  printf '  - commits/diff.range.stat.txt\n'
  printf '  - commits/name-status.txt\n'
  printf '  - patches/*.patch\n'
  printf '  - meta/commit-shas.txt\n'
  printf '  - meta/commit-index.tsv\n'
  printf '  - meta/match-sources.tsv\n'
  printf '  - meta/range.txt\n'
  printf '  - meta/pack-manifest.yaml\n'
} > "$meta_root/pack-manifest.yaml"

{
  printf '# GitHub Feature Fuzzy Commit Trace\n\n'
  printf -- '- github_url: `%s`\n' "$github_url"
  printf -- '- ref: `%s` (tip `%s`)\n' "$ref" "$tip_sha"
  printf -- '- feature_query: `%s`\n' "$feature_query"
  printf -- '- match_diff: %s\n' "$match_diff"
  printf -- '- include_full_patches: %s\n' "$include_full_patches"
  printf -- '- first_commit: `%s`\n' "$first_sha"
  printf -- '- last_commit: `%s`\n' "$last_sha"
  printf -- '- commits: %s\n' "$commit_count"
  printf -- '- work_root: `%s`\n' "$work_root"
  printf '\n## Commits (oldest → newest)\n\n```\n'
  cat "$commits_root/commits.oneline.txt"
  printf '```\n'
} > "$pack_root/SUMMARY.md"

cp "$pack_root/SUMMARY.md" "$output_dir/feature-fuzzy-trace-SUMMARY.md"

zip_path="$output_dir/$zip_name"
rm -f "$zip_path"
(
  cd "$work_root"
  zip -r -y "$zip_path" pack -x "*.DS_Store" -x "**/.git/**"
)

{
  printf 'Wrote zip: %s\n' "$zip_path"
  printf 'Query: %s\n' "$feature_query"
  printf 'Commits: %s (%s..%s)\n' "$commit_count" "$first_sha" "$last_sha"
  printf 'Summary: %s\n' "$pack_root/SUMMARY.md"
  printf 'Work root: %s\n' "$work_root"
}
unzip -t "$zip_path" >/dev/null
unzip -l "$zip_path" | tail -n 20
```

## 成功标准

- [ ] `output_dir/<zip_name>` 存在，且 `unzip -t` 通过。
- [ ] zip 内含 `pack/SUMMARY.md`、`pack/meta/pack-manifest.yaml`、`pack/meta/range.txt`、`pack/meta/commit-shas.txt`、`pack/meta/commit-index.tsv`、`pack/meta/match-sources.tsv`。
- [ ] `first_sha` 是匹配集中最老的提交，`last_sha` 是最新的；`commit_count` 等于 `commit-shas.txt` 行数。
- [ ] `pack/patches/` 中每条匹配提交都有对应 trace（完整 patch 或 stat，取决于 `include_full_patches`）。
- [ ] 源仓库工作树未被 reset/clean；clone 只出现在 `output_dir/.repos/`。

## 安全

- 不删源文件；不执行 `git push`、`git reset --hard` 或强制清理工作树。
- 不要把 token/密码写入 `github_url`、manifest 或 SUMMARY；私有仓用 credential helper 或 SSH agent。
- clone 与 zip 只写用户同意的 `output_dir`；拒绝 `output_dir=/`。
- `zip_name` 禁止路径分隔符与 `..`。
- 不主动打包 `.env`、密钥、证书；但历史 patch 可能含敏感内容，交付前需人工审阅。
- `match_diff=1` 会扫描 diff，大仓库可能较慢；可改为 `0`。

## 输出给用户的汇报

- zip 与 SUMMARY 的绝对路径。
- `ref`、`feature_query`、`first_sha`→`last_sha`、匹配提交数。
- 若无匹配：提示缩短关键词、换分支，或确认 `match_diff`。
- 若 clone/fetch 失败：说明是网络或凭据问题，不删除已有目录。
