---
name: github-feature-path-commit-zip
version: 0.1.0
kind: flow-skill
interaction: stepwise
tags: [github, git, commits, path, feature, trace, zip]
summary: 按功能相关路径，采集 GitHub 仓库从首次到末次触及该路径的全部提交与 trace，并打成 ZIP。
---

# GitHub Feature Path Commit ZIP

> 交互节奏由用户侧 **Shared** 协议统一处理（邀请码 → 一次一问 → 确认 → 执行）。  
> 本 Skill **只声明槽位与执行**，不描述会话状态机。

## 目标

给定一个 GitHub 仓库与一组「功能相关」路径（目录或文件），在指定分支/引用上：

1. 找出**第一次**与**最后一次**触及这些路径的提交；
2. 导出该区间内所有相关提交的 log、patch/trace、作者统计与可校验 manifest；
3. 打包为一个可审计的 `.zip`（**不**复制无关工作树大文件；trace 以 git 文本产物为主）。

典型用途：功能演进审计、code review 包、路径级变更溯源。

## 输入

| 参数 | 必填 | 默认 | 说明 | 校验 |
|------|------|------|------|------|
| `github_url` | 是 | | HTTPS 或 `git@` Git URL | 非空；勿把 token 写进 URL |
| `path_specs` | 是 | | 功能相关路径，多个用空格或英文逗号分隔（相对仓库根，如 `src/foo pkg/bar`） | 非空；禁止 `..` 与绝对路径 |
| `ref` | 否 | 仓库默认分支 | 分析用的分支/tag/SHA（如 `main`、`origin/develop`） | 存在于仓库 |
| `out_dir` | 否 | `$PWD/out` | 产物与 clone 工作区根 | 非 `/`；可写 |
| `repo_path` | 否 | | 已有本地仓库路径；提供则复用，不再 clone | 须含 `.git` |
| `zip_name` | 否 | `feature-path-commits.zip` | zip 文件名（不含目录） | 不含 `/` `\` `..` |
| `include_full_patches` | 否 | `1` | `1` 导出每提交完整 patch；`0` 仅 stat/summary（大仓库可关） | `0`\|`1` |
| `follow_renames` | 否 | `1` | `1` 对 path 使用 `git log --follow`（单路径时更有用） | `0`\|`1` |

## 执行步骤

在含 `git`、`zip`、`date`、`sort`、`awk`、`sed` 的环境中执行。clone 仅写入 `out_dir/.repos/`；**不修改**用户原有 `repo_path` 的工作树内容（可 fetch）。

```bash
set -euo pipefail

: "${github_url:?set github_url to an HTTPS or git@ GitHub URL}"
: "${path_specs:?set path_specs to one or more repo-relative paths}"

out_dir="${out_dir:-$PWD/out}"
zip_name="${zip_name:-feature-path-commits.zip}"
include_full_patches="${include_full_patches:-1}"
follow_renames="${follow_renames:-1}"
ref="${ref:-}"

case "$out_dir" in /*) ;; *) out_dir="$PWD/$out_dir";; esac
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd -P)"

case "$zip_name" in
  *..*|*/*|*\\*|'') echo "invalid zip_name: $zip_name" >&2; exit 1 ;;
esac

# --- normalize path_specs (space or comma) ---
paths=()
path_specs_normalized="$(printf '%s' "$path_specs" | tr ',\n' '  ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')"
[[ -n "$path_specs_normalized" ]] || { echo "path_specs empty after normalize" >&2; exit 1; }
# shellcheck disable=SC2206
paths=( $path_specs_normalized )
for p in "${paths[@]}"; do
  case "$p" in
    ''|/*|*..*|'~'*) echo "invalid path_spec (no absolute/~/..): $p" >&2; exit 1 ;;
  esac
done

repo_name="$(basename -s .git "${github_url%/}")"
repo_name="$(printf '%s' "$repo_name" | sed 's/[^A-Za-z0-9._-]/_/g')"
repo_root="$out_dir/.repos/$repo_name"

if [[ -n "${repo_path:-}" ]]; then
  [[ -d "$repo_path/.git" ]] || { echo "repo_path is not a Git repository: $repo_path" >&2; exit 1; }
  repo_root="$(cd "$repo_path" && pwd -P)"
else
  mkdir -p "$out_dir/.repos"
  if [[ -d "$repo_root/.git" ]]; then
    git -C "$repo_root" fetch --all --prune
  else
    git clone --no-single-branch "$github_url" "$repo_root"
  fi
fi

git -C "$repo_root" fetch origin '+refs/heads/*:refs/remotes/origin/*' --prune 2>/dev/null || true

# resolve ref → tip
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
work_root="$out_dir/feature-path-commits-$stamp"
pack_root="$work_root/pack"
meta_root="$pack_root/meta"
commits_root="$pack_root/commits"
patches_root="$pack_root/patches"
mkdir -p "$meta_root" "$commits_root" "$patches_root"

# --- collect commits touching paths (ancestry order: oldest first) ---
log_args=( --reverse --date-order --pretty=format:'%H' "$tip_sha" -- )
# --follow only valid with a single path
use_follow=0
if [[ "$follow_renames" == "1" && "${#paths[@]}" -eq 1 ]]; then
  use_follow=1
  log_args=( --follow --reverse --date-order --pretty=format:'%H' "$tip_sha" -- "${paths[0]}" )
else
  log_args=( --reverse --date-order --pretty=format:'%H' "$tip_sha" -- "${paths[@]}" )
fi

commits_file="$meta_root/commit-shas.txt"
: > "$commits_file"
git -C "$repo_root" log "${log_args[@]}" > "$commits_file" || true

# drop empty lines
grep -E '^[0-9a-f]{7,40}$' "$commits_file" > "$commits_file.filtered" || true
mv "$commits_file.filtered" "$commits_file"

commit_count="$(wc -l < "$commits_file" | tr -d ' ')"
if [[ "$commit_count" -eq 0 ]]; then
  echo "No commits touch path_specs under ref=$ref (tip=$tip_sha)" >&2
  echo "paths: $path_specs_normalized" >&2
  exit 1
fi

first_sha="$(head -n 1 "$commits_file")"
last_sha="$(tail -n 1 "$commits_file")"

# detailed logs
git -C "$repo_root" log --reverse --pretty=fuller --stat --find-renames \
  "$first_sha^..$last_sha" -- "${paths[@]}" \
  > "$commits_root/commits.full.txt" 2>/dev/null \
  || git -C "$repo_root" log --reverse --pretty=fuller --stat --find-renames \
       "$last_sha" -- "${paths[@]}" > "$commits_root/commits.full.txt"

# oneline list constrained to our SHA list
: > "$commits_root/commits.oneline.txt"
while IFS= read -r sha || [[ -n "${sha:-}" ]]; do
  [[ -z "${sha:-}" ]] && continue
  git -C "$repo_root" log -1 --oneline "$sha" >> "$commits_root/commits.oneline.txt"
done < "$commits_file"

# authors (path-scoped)
git -C "$repo_root" shortlog -sn "$first_sha^..$last_sha" -- "${paths[@]}" \
  > "$commits_root/authors.txt" 2>/dev/null \
  || git -C "$repo_root" shortlog -sn "$last_sha" -- "${paths[@]}" > "$commits_root/authors.txt"

# cumulative diff stat first→last on paths
if git -C "$repo_root" diff --stat "$first_sha"^ "$last_sha" -- "${paths[@]}" \
     > "$commits_root/diff.range.stat.txt" 2>/dev/null; then
  :
elif git -C "$repo_root" diff --stat "$first_sha" "$last_sha" -- "${paths[@]}" \
     > "$commits_root/diff.range.stat.txt" 2>/dev/null; then
  :
else
  printf 'diff range stat unavailable\n' > "$commits_root/diff.range.stat.txt"
fi

# name-status across range
git -C "$repo_root" log --reverse --name-status --pretty=format:'=== %H %s' \
  "$first_sha^..$last_sha" -- "${paths[@]}" \
  > "$commits_root/name-status.txt" 2>/dev/null \
  || git -C "$repo_root" log --reverse --name-status --pretty=format:'=== %H %s' \
       "$last_sha" -- "${paths[@]}" > "$commits_root/name-status.txt"

# per-commit patches / traces
idx=0
: > "$meta_root/commit-index.tsv"
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
    git -C "$repo_root" show --stat --format= "$sha" -- "${paths[@]}"
  } > "$meta_one"

  if [[ "$include_full_patches" == "1" ]]; then
    git -C "$repo_root" show --binary --find-renames --format=fuller "$sha" -- "${paths[@]}" \
      > "$patches_root/$patch_name" || printf 'patch unavailable for %s\n' "$sha" > "$patches_root/$patch_name"
  else
    git -C "$repo_root" show --stat --format=fuller "$sha" -- "${paths[@]}" \
      > "$patches_root/$patch_name" || true
  fi
  printf '%s\t%s\t%s\t%s\n' "$idx_pad" "$sha" "$subject" "$patch_name" >> "$meta_root/commit-index.tsv"
done < "$commits_file"

# range + manifest
{
  printf 'from=%s\n' "$first_sha"
  printf 'to=%s\n' "$last_sha"
  printf 'tip_ref=%s\n' "$tip_ref"
  printf 'tip_sha=%s\n' "$tip_sha"
  printf 'commit_count=%s\n' "$commit_count"
} > "$meta_root/range.txt"

generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
{
  printf 'kind: github-feature-path-commit-zip\n'
  printf 'github_url: %s\n' "$github_url"
  printf 'repo_root: %s\n' "$repo_root"
  printf 'ref: %s\n' "$ref"
  printf 'tip_ref: %s\n' "$tip_ref"
  printf 'tip_sha: %s\n' "$tip_sha"
  printf 'first_sha: %s\n' "$first_sha"
  printf 'last_sha: %s\n' "$last_sha"
  printf 'commit_count: %s\n' "$commit_count"
  printf 'follow_renames: %s\n' "$use_follow"
  printf 'include_full_patches: %s\n' "$include_full_patches"
  printf 'generated_at: %s\n' "$generated_at"
  printf 'path_specs:\n'
  for p in "${paths[@]}"; do printf '  - %s\n' "$p"; done
  printf 'files:\n'
  printf '  - commits/commits.oneline.txt\n'
  printf '  - commits/commits.full.txt\n'
  printf '  - commits/authors.txt\n'
  printf '  - commits/diff.range.stat.txt\n'
  printf '  - commits/name-status.txt\n'
  printf '  - commits/*-<sha>.txt\n'
  printf '  - patches/*.patch\n'
  printf '  - meta/commit-shas.txt\n'
  printf '  - meta/commit-index.tsv\n'
  printf '  - meta/range.txt\n'
  printf '  - meta/pack-manifest.yaml\n'
  printf '  - SUMMARY.md\n'
} > "$meta_root/pack-manifest.yaml"

# SUMMARY
{
  printf '# GitHub Feature Path Commit ZIP\n\n'
  printf -- '- github_url: `%s`\n' "$github_url"
  printf -- '- ref: `%s` (tip `%s`)\n' "$ref" "$tip_sha"
  printf -- '- paths:\n'
  for p in "${paths[@]}"; do printf -- '  - `%s`\n' "$p"; done
  printf -- '- first_commit: `%s`\n' "$first_sha"
  printf -- '- last_commit: `%s`\n' "$last_sha"
  printf -- '- commits: %s\n' "$commit_count"
  printf -- '- include_full_patches: %s\n' "$include_full_patches"
  printf -- '- follow_renames_applied: %s\n' "$use_follow"
  printf -- '- work_root: `%s`\n' "$work_root"
  printf '\n## Commits (oldest → newest)\n\n'
  printf '```\n'
  cat "$commits_root/commits.oneline.txt"
  printf '```\n'
} > "$pack_root/SUMMARY.md"

cp "$pack_root/SUMMARY.md" "$out_dir/feature-path-commits-SUMMARY.md"

zip_path="$out_dir/$zip_name"
rm -f "$zip_path"
(
  cd "$work_root"
  zip -r -y "$zip_path" pack -x "*.DS_Store" -x "**/.git/**"
)

{
  printf 'Wrote zip: %s\n' "$zip_path"
  printf 'Commits: %s (%s..%s)\n' "$commit_count" "$first_sha" "$last_sha"
  printf 'Summary: %s\n' "$pack_root/SUMMARY.md"
  printf 'Work root: %s\n' "$work_root"
}
unzip -t "$zip_path" >/dev/null
unzip -l "$zip_path" | tail -n 20
```

## 成功标准

- [ ] `out_dir/<zip_name>` 存在，`unzip -t` 通过。
- [ ] zip 内含 `pack/SUMMARY.md`、`pack/meta/pack-manifest.yaml`、`pack/meta/range.txt`、`pack/meta/commit-shas.txt`、`pack/meta/commit-index.tsv`。
- [ ] `first_sha` / `last_sha` 与 path 相关提交时间序一致；`commit_count` 等于 `commit-shas.txt` 行数。
- [ ] `pack/patches/` 下每条提交有对应 trace（full patch 或 stat，取决于 `include_full_patches`）。
- [ ] 源仓库工作树未被重置/清理；仅可能 `fetch`/`clone` 到 `out_dir/.repos/`。

## 安全

- **不要**把 token/密码写入 `github_url`、manifest 或 SUMMARY；私有仓用 credential helper / SSH agent。
- 不打包 `.env`、密钥、证书；产物以 git log/show 文本为主（`--binary` patch 仍可能含历史敏感内容，交付前需人工审）。
- `path_specs` 禁止 `..` 与绝对路径；`zip_name` 禁止路径分隔符。
- clone 仅限 `out_dir/.repos/`；不删除用户未确认的目录。
- 不执行 `git push` / `git reset --hard` / 强制清理工作树。

## 输出给用户的汇报

- zip 与 SUMMARY 的**绝对路径**。
- `ref`、路径列表、`first_sha`→`last_sha`、提交数。
- 若无触及提交：说明路径/分支是否写错，并给出 `git log <ref> -- <paths>` 自检命令。
- 若 clone/fetch 失败：保留已有 `work_root`（若有），提示检查网络与 git 凭据。
