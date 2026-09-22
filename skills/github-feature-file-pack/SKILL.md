---
name: github-feature-file-pack
version: 0.1.0
kind: flow-skill
interaction: stepwise
tags: [github, zip, feature]
summary: 从 GitHub 仓库按功能描述模糊匹配相关文件，打包为一个 zip。
---

# github-feature-file-pack

> 用户侧：`eh_collect_start(invite_code)` 提供 Shared 交互。
> 本文件只声明 **输入槽位 + 执行**；不要写会话状态机。

## 目标

给定一个 GitHub 仓库、分支和一段**功能描述**（不必与文件名完全一致），在该分支工作树中找出与该功能相关的文件，按仓库相对路径打成一个 zip。不修改远程仓库，不删除用户已有文件。

## 输入

| 参数 | 必填 | 默认 | 说明 | 校验 |
|------|------|------|------|------|
| `github_url` | 是 | | 仓库地址（HTTPS 或 `git@`） | 非空；勿把 token 写进 URL |
| `feature_query` | 是 | | 功能描述，可中英文、可模糊，不必与文件名完全一致 | 非空，1–200 字 |
| `ref` | 否 | 仓库默认分支 | 要打包的分支、tag 或 SHA | 存在于仓库 |
| `out_dir` | 否 | `$PWD/out` | zip 与临时 clone 的输出目录 | 非 `/`；可写 |

## 执行步骤

在含 `git`、`zip`、`python3` 的环境中执行。clone 只写入 `out_dir/.repos/`。**不** `push`、**不**改远程、**不**删除 `out_dir` 以外的文件。

匹配分三层，由宽到严合并去重：

1. **路径/文件名**：把功能描述拆成词，对相对路径做不区分大小写的子串匹配（支持中英文片段，不要求整文件名一致）。
2. **符号/文本**：在文本文件中搜索这些词（函数名、类型名、注释、字符串）；命中则纳入该文件。跳过二进制与常见依赖目录。
3. **不足时放宽**：若两层合计少于 1 个文件，再用更短的词片段（长度 ≥ 3）重扫路径；仍为 0 则失败并列出最接近的路径供人工收窄描述，**不**把整个仓库打进 zip。

```bash
set -euo pipefail

: "${github_url:?set github_url to an HTTPS or git@ GitHub URL}"
: "${feature_query:?set feature_query to a feature description (fuzzy ok)}"

out_dir="${out_dir:-$PWD/out}"
ref="${ref:-}"

case "$out_dir" in
  /|"") echo "invalid out_dir: $out_dir" >&2; exit 1 ;;
esac
case "$out_dir" in /*) ;; *) out_dir="$PWD/$out_dir" ;; esac
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd -P)"
[[ "$out_dir" != "/" ]] || { echo "refuse out_dir=/" >&2; exit 1; }

# reject credential-in-URL
case "$github_url" in
  *://*:*@*) echo "do not embed tokens in github_url" >&2; exit 1 ;;
esac

repo_name="$(basename -s .git "${github_url%/}")"
repo_name="$(printf '%s' "$repo_name" | sed 's/[^A-Za-z0-9._-]/_/g')"
[[ -n "$repo_name" ]] || { echo "cannot derive repo name from github_url" >&2; exit 1; }

mkdir -p "$out_dir/.repos"
repo_root="$out_dir/.repos/$repo_name"

if [[ -d "$repo_root/.git" ]]; then
  git -C "$repo_root" fetch --prune origin
else
  git clone --no-tags --single-branch "$github_url" "$repo_root"
fi

if [[ -z "$ref" ]]; then
  ref="$(git -C "$repo_root" symbolic-ref --quiet --short HEAD || true)"
  if [[ -z "$ref" ]]; then
    ref="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)"
  fi
fi

tip=""
for cand in "refs/remotes/origin/$ref" "refs/heads/$ref" "$ref"; do
  if git -C "$repo_root" rev-parse --verify --quiet "$cand" >/dev/null; then
    tip="$cand"
    break
  fi
done
[[ -n "$tip" ]] || { echo "ref not found: $ref" >&2; exit 1; }

git -C "$repo_root" checkout --detach "$tip"

stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
safe_repo="$(printf '%s' "$repo_name" | tr '[:upper:]' '[:lower:]')"
zip_path="$out_dir/${safe_repo}-feature-${stamp}.zip"
manifest="$out_dir/${safe_repo}-feature-${stamp}.manifest.txt"
list_file="$out_dir/.repos/${safe_repo}-${stamp}.files.txt"

FEATURE_QUERY="$feature_query" \
REPO_ROOT="$repo_root" \
LIST_FILE="$list_file" \
MANIFEST="$manifest" \
REF_NAME="$ref" \
TIP_SHA="$(git -C "$repo_root" rev-parse HEAD)" \
GITHUB_URL="$github_url" \
python3 - <<'PY'
import os, re, sys
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
query = os.environ["FEATURE_QUERY"].strip()
list_file = Path(os.environ["LIST_FILE"])
manifest = Path(os.environ["MANIFEST"])

skip_dirs = {
    ".git", "node_modules", "vendor", "dist", "build", "out",
    ".next", "target", "__pycache__", ".venv", "venv", "coverage",
}
text_ext = {
    ".go", ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".rs",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".m", ".mm", ".scala", ".sql", ".sh", ".bash", ".zsh", ".ps1",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".scss",
    ".md", ".txt", ".rst", ".vue", ".svelte", ".proto", ".graphql",
    ".gradle", ".mod", ".sum", ".env.example",
}
max_scan_bytes = 1_500_000

def tokens(q: str):
    parts = re.findall(r"[A-Za-z0-9_./-]{2,}|[\u4e00-\u9fff]{2,}", q)
    # also split camel/snake-ish latin runs already captured; drop dupes, keep order
    seen, out = set(), []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    if not out and q:
        out = [q]
    return out

def skip(rel: Path) -> bool:
    return any(part in skip_dirs or part.startswith(".") and part not in {".github"} for part in rel.parts)

words = tokens(query)
if not words:
    print("feature_query produced no searchable tokens", file=sys.stderr)
    sys.exit(1)

needles = [w.lower() for w in words]
short = []
for w in needles:
    if len(w) >= 6:
        short.append(w[: max(3, len(w)//2)])
    elif len(w) >= 3:
        short.append(w)

path_hits, text_hits, scored = [], [], []
for p in repo.rglob("*"):
    if not p.is_file():
        continue
    rel = p.relative_to(repo)
    if skip(rel):
        continue
    rel_s = rel.as_posix()
    rel_l = rel_s.lower()
    path_score = sum(1 for n in needles if n in rel_l)
    if path_score:
        path_hits.append(rel_s)
        scored.append((path_score + 2, rel_s))
        continue
    # text scan only for likely source
    if p.suffix.lower() not in text_ext and p.name not in {"Makefile", "Dockerfile", "LICENSE"}:
        continue
    try:
        if p.stat().st_size > max_scan_bytes:
            continue
        data = p.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        continue
    text_score = sum(data.count(n) for n in needles if n in data)
    if text_score:
        text_hits.append(rel_s)
        scored.append((1, rel_s))

selected = []
seen = set()
for s in path_hits + text_hits:
    if s not in seen:
        seen.add(s)
        selected.append(s)

loose = []
if not selected and short:
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo)
        if skip(rel):
            continue
        rel_l = rel.as_posix().lower()
        if any(n in rel_l for n in short):
            loose.append(rel.as_posix())
    for s in loose:
        if s not in seen:
            seen.add(s)
            selected.append(s)

if not selected:
    # nearest paths for the human to refine the query — do not zip the repo
    near = []
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo)
        if skip(rel):
            continue
        rel_s = rel.as_posix()
        rel_l = rel_s.lower()
        score = 0
        for n in needles:
            for i in range(0, max(1, len(n)-1), 2):
                frag = n[i:i+3]
                if len(frag) >= 2 and frag in rel_l:
                    score += 1
        if score:
            near.append((score, rel_s))
    near.sort(key=lambda x: (-x[0], x[1]))
    print("no files matched feature_query; refine the description. nearest paths:", file=sys.stderr)
    for _, s in near[:30]:
        print("  " + s, file=sys.stderr)
    sys.exit(2)

# cap to avoid accidentally packing huge trees on a very generic query
cap = 400
truncated = False
if len(selected) > cap:
    selected = selected[:cap]
    truncated = True

list_file.write_text("\n".join(selected) + "\n", encoding="utf-8")
lines = [
    f"github_url={os.environ.get('GITHUB_URL','')}",
    f"ref={os.environ.get('REF_NAME','')}",
    f"tip={os.environ.get('TIP_SHA','')}",
    f"feature_query={query}",
    f"tokens={' '.join(words)}",
    f"path_hits={len(path_hits)}",
    f"text_hits={len(text_hits)}",
    f"loose_hits={len(loose)}",
    f"selected={len(selected)}",
    f"truncated={int(truncated)}",
    "files:",
    *selected,
]
manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"selected {len(selected)} files (path={len(path_hits)} text={len(text_hits)} loose={len(loose)} truncated={int(truncated)})")
PY

file_count="$(grep -c . "$list_file" || true)"
[[ "${file_count:-0}" -ge 1 ]] || { echo "file list empty" >&2; exit 1; }

# zip with repo-relative paths; do not follow symlinks outside the repo
(
  cd "$repo_root"
  # -@ reads paths from stdin; refuse absolute paths
  while IFS= read -r rel || [[ -n "${rel:-}" ]]; do
    [[ -z "${rel:-}" ]] && continue
    case "$rel" in
      /*|*..*) echo "refuse path: $rel" >&2; exit 1 ;;
    esac
    [[ -f "$rel" ]] || { echo "missing file: $rel" >&2; exit 1; }
    printf '%s\n' "$rel"
  done < "$list_file" | zip -q -@ "$zip_path"
)

# manifest sits beside the zip, not inside, so the archive is source-only
rm -f "$list_file"

echo "zip=$zip_path"
echo "manifest=$manifest"
echo "files=$file_count"
echo "ref=$ref"
echo "repo=$repo_root"
```

## 成功标准

- [ ] `out_dir` 下生成一个 `.zip`，且 `zip -T` 可测通
- [ ] zip 内路径为仓库相对路径，且均与 `feature_query` 的路径或文本命中对应
- [ ] 旁路 `.manifest.txt` 记录仓库、ref、tip、查询词与文件列表
- [ ] 未匹配到文件时失败退出，不产出「整仓 zip」
- [ ] 未 `git push`，未删除用户原有文件

## 安全

- 不删用户源文件；clone 与 zip 只写 `out_dir`
- 不把 token 放进 `github_url`；不打印凭据
- 功能描述过泛导致命中超过 400 个文件时截断并在 manifest 标记 `truncated=1`，避免误打包整仓
- 跳过 `.git`、依赖目录与隐藏目录（保留 `.github`）
- 匹配失败只列出最多 30 条相近路径，不外传仓库内容

## 输出给用户的汇报

- zip 绝对路径、文件数、使用的 `ref` 与 tip SHA
- manifest 路径，以及路径命中 / 文本命中 / 放宽命中的数量
- 若 `truncated=1`，说明描述过宽，建议收窄 `feature_query` 后重跑
