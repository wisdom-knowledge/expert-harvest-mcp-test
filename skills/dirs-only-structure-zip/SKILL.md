---
name: dirs-only-structure-zip
version: 0.1.0
kind: flow-skill
tags: [filesystem, directories, zip, structure, skeleton]
summary: Keep only the directory tree under a root (drop all files), then package the empty structure as a ZIP.
---

# Dirs-Only Structure ZIP

## 目标

给定一个根目录（默认当前工作目录），递归保留其下**全部子目录结构**，去掉目录内的**所有普通文件**（以及默认跳过的敏感/无关项），在隔离输出区重建「仅目录骨架」，并打包成一个可校验的 `.zip`。

典型用途：交付目录布局模板、脱敏后的树形结构、或只关心路径层级的审计包。

## 输入

| 参数 | 必填 | 说明 |
|------|------|------|
| `src_dir` | 否 | 源根目录，默认 `$PWD`（当前目录） |
| `out_dir` | 否 | 产物与工作区根，默认 `$PWD/out` |
| `zip_name` | 否 | zip 文件名（不含路径），默认 `dirs-only-structure.zip` |
| `include_hidden_dirs` | 否 | `1` 保留隐藏目录名（如 `.github`）；默认 `0` 跳过名称以 `.` 开头的目录 |
| `follow_symlinks` | 否 | `1` 跟随目录符号链接（有环风险，默认关闭）；默认 `0` |

## 执行步骤（必须按序）

在含 `find`、`mkdir`、`zip`、`sort`、`date`、`unzip` 的环境中执行。所有写入限制在 `out_dir` 下；**不修改、不删除** `src_dir` 内任何内容。

```bash
set -euo pipefail

src_dir="${src_dir:-$PWD}"
out_dir="${out_dir:-$PWD/out}"
zip_name="${zip_name:-dirs-only-structure.zip}"
include_hidden_dirs="${include_hidden_dirs:-0}"
follow_symlinks="${follow_symlinks:-0}"

case "$src_dir" in /*) ;; *) src_dir="$PWD/$src_dir";; esac
case "$out_dir" in /*) ;; *) out_dir="$PWD/$out_dir";; esac
src_dir="$(cd "$src_dir" && pwd -P)"
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd -P)"

case "$zip_name" in
  *..*|*/*|*\\*|'') echo "invalid zip_name: $zip_name" >&2; exit 1 ;;
esac

stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
work_root="$out_dir/dirs-only-structure-$stamp"
skeleton_root="$work_root/skeleton"
meta_root="$work_root/meta"
mkdir -p "$skeleton_root" "$meta_root"

if [[ "$follow_symlinks" == "1" ]]; then
  find_base=( find -L "$src_dir" )
else
  find_base=( find "$src_dir" )
fi

dirs_list="$meta_root/dirs.txt"
: > "$dirs_list"

"${find_base[@]}" -type d -print0 2>/dev/null \
  | while IFS= read -r -d '' d; do
      rel="${d#"$src_dir"}"
      rel="${rel#/}"
      [[ -z "$rel" ]] && continue

      skip=0
      old_ifs="$IFS"
      IFS='/'
      # shellcheck disable=SC2086
      set -- $rel
      IFS="$old_ifs"
      for seg in "$@"; do
        [[ -z "$seg" ]] && continue
        case "$seg" in
          .git|.svn|.hg|node_modules|__pycache__) skip=1; break ;;
          ..) skip=1; break ;;
        esac
        if [[ "$include_hidden_dirs" != "1" && "$seg" == .* ]]; then
          skip=1
          break
        fi
      done
      [[ "$skip" -eq 1 ]] && continue
      printf '%s\n' "$rel"
    done \
  | sort -u > "$dirs_list"

dir_count="$(wc -l < "$dirs_list" | tr -d ' ')"

while IFS= read -r rel || [[ -n "${rel:-}" ]]; do
  [[ -z "${rel:-}" ]] && continue
  mkdir -p "$skeleton_root/$rel"
done < "$dirs_list"

mkdir -p "$skeleton_root"

{
  printf 'kind: dirs-only-structure\n'
  printf 'source: %s\n' "$src_dir"
  printf 'generated_at: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf 'directory_count: %s\n' "$dir_count"
  printf 'include_hidden_dirs: %s\n' "$include_hidden_dirs"
  printf 'follow_symlinks: %s\n' "$follow_symlinks"
  printf 'note: skeleton contains directories only; no original file contents were copied\n'
} > "$meta_root/pack-manifest.yaml"

file_leak="$(find "$skeleton_root" -type f 2>/dev/null | head -n 5 || true)"
if [[ -n "$file_leak" ]]; then
  echo "skeleton unexpectedly contains files:" >&2
  printf '%s\n' "$file_leak" >&2
  exit 1
fi

zip_path="$out_dir/$zip_name"
rm -f "$zip_path"
(
  cd "$work_root"
  zip -r -y "$zip_path" skeleton meta/pack-manifest.yaml -x "*.DS_Store"
)

zip_list="$meta_root/zip-list.txt"
unzip -l "$zip_path" > "$zip_list"

{
  printf '# Dirs-Only Structure ZIP\n\n'
  printf -- '- source: `%s`\n' "$src_dir"
  printf -- '- directories packed: %s\n' "$dir_count"
  printf -- '- zip: `%s`\n' "$zip_path"
  printf -- '- work_root: `%s`\n' "$work_root"
  printf -- '- include_hidden_dirs: %s\n' "$include_hidden_dirs"
  printf '\n## Directories (relative)\n\n'
  if [[ "$dir_count" -eq 0 ]]; then
    printf '(none — empty skeleton root only)\n'
  else
    while IFS= read -r rel; do
      printf -- '- `%s`\n' "$rel"
    done < "$dirs_list"
  fi
} > "$work_root/SUMMARY.md"

cp "$work_root/SUMMARY.md" "$out_dir/dirs-only-structure-SUMMARY.md"

printf 'Wrote zip: %s\n' "$zip_path"
printf 'Directories: %s\n' "$dir_count"
printf 'Summary: %s\n' "$work_root/SUMMARY.md"
```

## 成功标准

- [ ] `out_dir/<zip_name>` 存在，且 `unzip -t` / `unzip -l` 可读。
- [ ] zip 内 `skeleton/` 下**仅有目录**（无源文件内容）；`meta/pack-manifest.yaml` 记录 `directory_count` 与源路径。
- [ ] `SUMMARY.md` 列出相对目录数，与 `meta/dirs.txt` 行数一致。
- [ ] 源目录 `src_dir` 未被删除或改写（本流程只读源、只写 `out_dir`）。

## 安全

- **只读** `src_dir`：不删除、不移动、不清空用户原目录里的文件。
- **不复制** 任何文件内容到 skeleton；避免把 `.env`、密钥、证书、源码打进包。
- 默认跳过 `.git` / `.svn` / `.hg` / `node_modules` / `__pycache__` 以及（默认）隐藏目录段。
- `zip_name` 禁止含 `/`、`\`、`..`；产物只写在 `out_dir`。
- 默认不跟随符号链接，降低逃逸与环状目录风险。
- 不要把访问令牌写入 manifest 或 SUMMARY。

## 输出给用户的汇报

- 报告 zip 与 SUMMARY 的**绝对路径**。
- 报告打包的目录数量；若为 0，说明源下无（过滤后）子目录。
- 若 `zip`/`find` 失败，保留已生成的 `work_root` 并给出可重试命令（检查 `zip` 是否安装、`src_dir` 是否可读）。
