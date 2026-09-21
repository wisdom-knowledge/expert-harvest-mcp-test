---
name: github-all-branches-commit-pack
version: 0.1.0
kind: flow-skill
tags: [github, git, commits, trace, branches]
summary: Clone or reuse a GitHub repository and produce an auditable commit-history pack for every branch.
---

# GitHub All Branches Commit Pack

## 目标

给定一个 GitHub 仓库 URL，采集仓库可见的本地和常见 origin 远程分支。
每个分支写入独立目录，包含提交历史、作者、首尾 SHA、diff 统计和可验证的 YAML manifest。
同时生成顶层 SUMMARY.md，便于按分支比较提交数量；可选地为每个分支生成 tar.gz。

## 输入

| 参数 | 必填 | 说明 |
|------|------|------|
| `github_url` | 是 | HTTPS 或 `git@` Git URL；使用 shell 环境变量传入 |
| `out_dir` | 否 | 输出及 clone 工作目录，默认当前目录下的 `out` |
| `repo_path` | 否 | 已有仓库路径；提供后复用，不再 clone |
| `MAKE_TARBALLS` | 否 | 设为 `1` 为每个分支生成 tar.gz，默认 `0` |

## 执行步骤（必须按序）

在包含 Git、awk、sed、find、date 和 tar 的环境中执行。命令会把 clone 限制在 `out_dir` 下，并拒绝危险路径。

```bash
set -euo pipefail

: "${github_url:?set github_url to an HTTPS or git@ GitHub URL}"
out_dir="${out_dir:-"$PWD/out"}"
MAKE_TARBALLS="${MAKE_TARBALLS:-0}"
case "$out_dir" in /*) ;; *) out_dir="$PWD/$out_dir";; esac
mkdir -p "$out_dir"
repo_name="$(basename -s .git "${github_url%/}")"
repo_name="$(printf '%s' "$repo_name" | sed 's/[^A-Za-z0-9._-]/_/g')"
repo_root="$out_dir/.repos/$repo_name"

if [[ -n "${repo_path:-}" ]]; then
  [[ -d "$repo_path/.git" ]] || { echo "repo_path is not a Git repository" >&2; exit 1; }
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
pack_root="$out_dir/$repo_name"
branches_root="$pack_root/branches"
mkdir -p "$branches_root"
branches=()
while IFS= read -r branch_name; do
  [[ -n "$branch_name" ]] && branches+=("$branch_name")
done < <(git -C "$repo_root" for-each-ref --format='%(refname:short)' refs/heads refs/remotes/origin | sed 's#^origin/##' | sed '/^HEAD$/d' | sort -u)
[[ "${#branches[@]}" -gt 0 ]] || { echo "No branches found" >&2; exit 1; }

summary_tmp="$pack_root/.summary.tmp"
printf '# GitHub All Branches Commit Pack\n\n| Branch | From | To | Commits | Directory |\n|---|---|---|---:|---|\n' > "$summary_tmp"
for branch in "${branches[@]}"; do
  ref="refs/remotes/origin/$branch"
  git show-ref --verify --quiet "$ref" || ref="refs/heads/$branch"
  to_sha="$(git -C "$repo_root" rev-parse "$ref")"
  from_sha="$(git -C "$repo_root" rev-list --max-parents=0 "$to_sha" | tail -n 1)"
  commit_count="$(git -C "$repo_root" rev-list --count "$to_sha")"
  safe_branch="$(printf '%s' "$branch" | sed 's#[^A-Za-z0-9._-]#_#g; s#^[.-]*$#branch#')"
  branch_dir="$branches_root/$safe_branch"
  mkdir -p "$branch_dir"
  git -C "$repo_root" log --oneline "$to_sha" > "$branch_dir/commits.oneline.txt"
  git -C "$repo_root" log --pretty=fuller "$to_sha" > "$branch_dir/commits.full.txt"
  git -C "$repo_root" shortlog -sn "$to_sha" > "$branch_dir/authors.txt"
  printf 'from=%s\nto=%s\n' "$from_sha" "$to_sha" > "$branch_dir/range.txt"
  if git -C "$repo_root" diff --stat "$from_sha" "$to_sha" > "$branch_dir/diff.stat.txt"; then :; else printf 'diff unavailable; retained commit logs and range only\n' > "$branch_dir/diff.stat.txt"; fi
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  {
    printf 'branch: %s\nfrom: %s\nto: %s\ncommit_count: %s\ngenerated_at: %s\nfiles:\n' "$branch" "$from_sha" "$to_sha" "$commit_count" "$generated_at"
    printf '  - commits.oneline.txt\n  - commits.full.txt\n  - diff.stat.txt\n  - authors.txt\n  - range.txt\n  - pack-manifest.yaml\n'
  } > "$branch_dir/pack-manifest.yaml"
  if [[ "$MAKE_TARBALLS" == 1 ]]; then
    tar -czf "$branches_root/$safe_branch.tar.gz" -C "$branches_root" "$safe_branch"
  fi
  printf '| `%s` | `%s` | `%s` | %s | `branches/%s` |\n' "$branch" "$from_sha" "$to_sha" "$commit_count" "$safe_branch" >> "$summary_tmp"
done
mv "$summary_tmp" "$pack_root/SUMMARY.md"
printf 'Wrote %s\n' "$pack_root"
```

## 成功标准

- [ ] `out/<repo-name>/SUMMARY.md` 存在且列出每个发现的分支及 commit_count。
- [ ] 每个 `out/<repo-name>/branches/<branch-safe-name>/` 独立存在，并含 `commits.oneline.txt`、`commits.full.txt`、`diff.stat.txt`、`authors.txt`、`range.txt` 和 `pack-manifest.yaml`。
- [ ] manifest 的 `from`、`to`、`commit_count` 与 Git 命令结果一致；tarball（若启用）可由 `tar -tzf` 读取。

## 安全

- 不打包 `.env`、密钥、证书私钥或其他凭据；本流程只写 Git 元数据和统计文本，不复制工作树文件。
- 不删除用户未确认的目录；已有 `repo_path` 仅读取并执行 fetch，不清理其内容。
- clone 仅允许写入 `out_dir/.repos/`；`out_dir` 和仓库路径须由调用者明确提供或使用默认工作目录下的 `out`。
- 分支名经过文件系统安全替换；不要把未经替换的分支名拼接为路径。
- 不要把访问令牌写入 URL、日志或产物；私有仓库认证应由 Git credential helper 或 SSH agent 提供。

## 输出给用户的汇报

- 报告 `SUMMARY.md`、分支目录和可选 tarball 的绝对路径。
- 报告分支总数及每个分支的 commit_count。
- 若 fetch、diff 或单个分支失败，保留已完成产物并说明失败命令及可执行的重试建议。
