---
name: flatten-directory-zip
version: 0.3.0
kind: flow-skill
interaction: stepwise
tags: [files, directory, flatten, zip, archive]
summary: 将目录内文件扁平化并打包为 ZIP（槽位由 Shared 交互收集）。
---

# Flatten Directory and Create ZIP

> 交互节奏由用户侧 **Shared** 协议统一处理（邀请码 → 一次一问 → 确认 → 执行）。  
> 本 Skill **只声明槽位与执行**，不描述会话状态机。

## 目标

把本机某目录下（含子目录）文件复制到同一层输出目录并打成 ZIP；不修改输入目录。同名默认失败，可选 rename。

## 输入

| 参数 | 必填 | 默认 | 说明 | 校验 |
|------|------|------|------|------|
| `input_dir` | 是 | | 要采集的源目录 | 已存在目录；非 `/` 与 `.ssh` 等 |
| `output_dir` | 否 | `$PWD/flattened-output` | 扁平文件与 ZIP 输出目录 | 不等于且不位于 input_dir 内 |
| `zip_name` | 否 | `flattened-files.zip` | ZIP 文件名 | 不含 `/` 或 `..` |
| `collision_mode` | 否 | `error` | 同名：`error` 失败；`rename` 加 `__2`… | 仅 error\|rename；用户也可回 1/2 |

## 执行步骤

```bash
set -euo pipefail

: "${input_dir:?set input_dir to the directory to collect}"
output_dir="${output_dir:-$PWD/flattened-output}"
zip_name="${zip_name:-flattened-files.zip}"
collision_mode="${collision_mode:-error}"

[[ -d "$input_dir" ]] || { printf 'input_dir is not a directory: %s\n' "$input_dir" >&2; exit 1; }
case "$collision_mode" in error|rename) ;; *) printf 'collision_mode must be error or rename\n' >&2; exit 1 ;; esac
case "$zip_name" in ''|.|..|*/*|*..*) printf 'zip_name must be a plain filename without slash or ..: %s\n' "$zip_name" >&2; exit 1 ;; esac

input_dir="$(cd "$input_dir" && pwd -P)"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd -P)"
[[ "$input_dir" != "$output_dir" && "$output_dir" != "$input_dir"/* ]] || {
  printf 'output_dir must not be input_dir or inside input_dir\n' >&2
  exit 1
}
archive="$output_dir/$zip_name"
stage_dir="$output_dir/.flattened-files.tmp.$$"
manifest="$output_dir/flatten-manifest.tsv"
cleanup() { rm -rf "$stage_dir" "$manifest.tmp"; }
trap cleanup EXIT
mkdir "$stage_dir"

# Read relative paths from find without allowing an old output archive to be re-collected.
count=0
while IFS= read -r -d '' relative_path; do
  source_path="$relative_path"
  relative_path="${source_path#"$input_dir"/}"
  base_name="${relative_path##*/}"
  target_name="$base_name"
  if [[ -e "$stage_dir/$target_name" ]]; then
    if [[ "$collision_mode" == error ]]; then
      printf 'duplicate filename after flattening: %s\n' "$base_name" >&2
      exit 1
    fi
    stem="$base_name"
    suffix=""
    if [[ "$stem" == .* && "$stem" != ..* ]]; then
      stem="${stem%.*}"
      suffix=".${base_name##*.}"
    elif [[ "$stem" == *.* ]]; then
      stem="${stem%.*}"
      suffix=".${base_name##*.}"
    fi
    index=2
    while [[ -e "$stage_dir/${stem}__${index}${suffix}" ]]; do
      index=$((index + 1))
    done
    target_name="${stem}__${index}${suffix}"
  fi
  cp -p -- "$source_path" "$stage_dir/$target_name"
  printf '%s\t%s\n' "$target_name" "$relative_path" >> "$manifest.tmp"
  count=$((count + 1))
done < <(find "$input_dir" -type f ! -path "$input_dir/.git/*" -print0)

if [[ "$count" -eq 0 ]]; then
  printf 'input_dir contains no files: %s\n' "$input_dir" >&2
  exit 1
fi

mv "$manifest.tmp" "$manifest"
rm -f -- "$archive"
(
  cd "$stage_dir"
  zip -q -X -r "$archive" .
)
unzip -tq "$archive" >/dev/null
printf 'files=%s\noutput_dir=%s\narchive=%s\nmanifest=%s\n' "$count" "$output_dir" "$archive" "$manifest"
```

## 成功标准

- [ ] 输出 ZIP 通过 `unzip -tq`，条目均在根层
- [ ] 存在 `flatten-manifest.tsv`（输出名→输入相对路径）
- [ ] collision_mode 行为符合上表

## 安全

- 不删不移输入文件；不跟符号链接；跳过 `.git`
- 拒绝 output 落在 input 内；ZIP 名防路径穿越
- manifest 不含文件内容/密钥

## 输出给用户的汇报

- `archive`、`manifest` 绝对路径与文件数、collision_mode
- 失败：短因 + 可改哪个槽位重试
