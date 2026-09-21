---
name: flatten-directory-zip
version: 0.1.0
kind: flow-skill
tags: [files, directory, flatten, zip, archive]
summary: Flatten every file under a directory into one output directory and package the result as a ZIP archive.
---

# Flatten Directory and Create ZIP

## 目标

给定一个输入目录，递归读取它和所有子目录中的文件，把文件复制到同一个输出目录，再将这个扁平目录打包成 ZIP。输入目录本身不会被修改。

默认保留输入目录直属文件的文件名，并把子目录中的文件也放到同一层。为避免静默覆盖，同名文件默认使流程失败；如业务允许，可以使用 `collision_mode=rename` 为冲突文件追加稳定的 `__2`、`__3` 后缀。

## 输入

| 参数 | 必填 | 说明 |
|------|------|------|
| `input_dir` | 是 | 要采集的目录；必须是目录，不能是输出目录的父子重叠路径 |
| `output_dir` | 否 | 扁平文件和 ZIP 的输出目录，默认 `$PWD/flattened-output` |
| `zip_name` | 否 | ZIP 文件名，默认 `flattened-files.zip`；必须是普通文件名，不能包含 `/` 或 `..` |
| `collision_mode` | 否 | `error`（默认）或 `rename` |

## 执行步骤（必须按序）

在包含 Bash、`find`、`cp`、`mkdir`、`mv`、`rm` 和 `zip` 的环境中执行。脚本不依赖 Bash 4 的关联数组，并使用 NUL 分隔的文件列表，因此文件名中的空格、换行和引号不会改变遍历边界。

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

- [ ] 输出目录包含一个扁平文件目录对应的 ZIP，且 ZIP 通过 `unzip -tq` 校验。
- [ ] ZIP 中每个条目都位于根层，不含输入目录前缀或子目录路径。
- [ ] `flatten-manifest.tsv` 记录每个输出文件名及其输入相对路径，便于追溯。
- [ ] `collision_mode=error` 时任何扁平化后的同名文件都会使流程失败，不会覆盖已有文件。
- [ ] `collision_mode=rename` 时冲突文件保留，重命名结果使用从 `__2` 开始的稳定编号。

## 安全

- 不删除或移动输入目录中的文件；只执行带 `--` 的复制和归档操作。
- 拒绝把输出目录放在输入目录中，避免输出文件被下一次递归扫描。
- ZIP 文件名只允许普通文件名，拒绝 `/`、`..` 和空值，防止路径穿越。
- 不跟随符号链接收集文件；不会把 `.git` 目录中的文件写入归档。
- 不把文件内容、凭据或环境变量写入日志；manifest 只包含文件名和输入相对路径。
- 输出 ZIP 已存在时会覆盖该 ZIP，但不会覆盖扁平目录中的输入文件；需要保留旧归档时请先改用不同的 `zip_name`。

## 输出给用户的汇报

- 报告 `archive` 和 `manifest` 的绝对路径。
- 报告收集的文件数量及使用的 `collision_mode`。
- 若发现同名文件、输入目录为空、路径重叠或 ZIP 校验失败，报告失败原因和修复参数；不要把部分结果当作成功交付。
