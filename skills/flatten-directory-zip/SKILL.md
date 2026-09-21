---
name: flatten-directory-zip
version: 0.2.0
kind: flow-skill
interaction: stepwise
tags: [files, directory, flatten, zip, archive, interactive]
summary: 用户只凭邀请码进入会话；逐步询问源目录等参数后，将目录内文件扁平化并打成 ZIP。
---

# Flatten Directory and Create ZIP

## 目标

把某个本机目录下（含所有子目录）的文件，复制到同一层输出目录，再打成 ZIP。  
**不修改**用户的输入目录。同名冲突默认失败；可选 rename。

## 用户怎么进入

```text
邀请码 <本流程的 invite>
```

Agent 加载本 Skill 后进入交互：一次只问一个问题，确认后再执行。不要把全文或整段 bash 甩给用户。

## 交互步骤（槽位 · 必须按序）

### 步骤 1 · 源目录

| 项 | 内容 |
|----|------|
| 问法 | 「请给我要处理的源目录路径（本机绝对路径或可解析路径）：」 |
| 槽位 | `input_dir` |
| 必填 | 是 |
| 默认 | 无 |
| 校验 | 必须是已存在的目录；不能是 `/`、不能是 `.ssh` 等敏感目录；不能与即将使用的 output_dir 重叠 |
| 示例回答 | `/Users/me/Desktop/my-folder` |

### 步骤 2 · 输出目录

| 项 | 内容 |
|----|------|
| 问法 | 「输出目录用哪里？直接回复「默认」则用当前目录下的 `flattened-output`」 |
| 槽位 | `output_dir` |
| 必填 | 否 |
| 默认 | `$PWD/flattened-output` |
| 校验 | 不得等于 input_dir，不得位于 input_dir 之内；不可写则重问 |
| 示例回答 | `默认` 或 `~/Desktop/flat-out` |

### 步骤 3 · ZIP 文件名

| 项 | 内容 |
|----|------|
| 问法 | 「ZIP 叫什么名字？回复「默认」则用 `flattened-files.zip`」 |
| 槽位 | `zip_name` |
| 必填 | 否 |
| 默认 | `flattened-files.zip` |
| 校验 | 普通文件名，不能含 `/` 或 `..` |
| 示例回答 | `默认` 或 `my-pack.zip` |

### 步骤 4 · 重名策略

| 项 | 内容 |
|----|------|
| 问法 | 「遇到同名文件时：1) 报错停止  2) 自动改名保留。请回复 1 或 2（默认 1）」 |
| 槽位 | `collision_mode` |
| 必填 | 否 |
| 默认 | `error`（用户回 1 或「默认」） |
| 校验 | `1`/`报错` → error；`2`/`改名` → rename |
| 示例回答 | `1` |

## 确认词

槽位齐后复述：

```text
即将扁平化并打包：
- input_dir: …
- output_dir: …
- zip_name: …
- collision_mode: error|rename
确认开始？回复「确认」或指出要改的项。
```

确认词：`确认` / `开始` / `OK`。说「改源目录」等则回到对应步骤。

## 执行步骤（确认后 · 本机）

在包含 Bash、`find`、`cp`、`mkdir`、`mv`、`rm` 和 `zip` 的环境中执行。

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

- [ ] 用户主要通过邀请码 + 逐步短答完成（或首句已带齐路径）
- [ ] 输出目录含通过 `unzip -tq` 的 ZIP，条目均在根层
- [ ] 存在 `flatten-manifest.tsv` 追溯输出名→输入相对路径
- [ ] `collision_mode=error` 时同名即失败；`rename` 时用 `__2` 起稳定后缀

## 安全

- 不删除或移动输入目录中的文件；只复制和归档
- 拒绝 output 落在 input 内，避免扫描到输出
- ZIP 名禁止路径穿越；不跟符号链接收集；跳过 `.git`
- 不把文件内容/密钥写入日志；manifest 仅文件名与相对路径
- 交互中拒绝系统根、`.ssh` 等危险源路径

## 输出给用户的汇报

- `archive` 与 `manifest` 的绝对路径
- 文件数量与 `collision_mode`
- 失败时说明是哪一交互步或执行步，并给出可重试短提示（不甩长 log）
