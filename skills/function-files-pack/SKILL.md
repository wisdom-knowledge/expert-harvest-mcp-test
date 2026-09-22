---
name: function-files-pack
version: 0.1.0
kind: flow-skill
interaction: stepwise
tags: [files, zip, fuzzy-match]
summary: 按自然语言功能描述，在本地目录中模糊找出相关目录和文件，打包为保留相对路径的 zip，并生成 manifest.csv。
---

# 功能相关文件打包

> 用户侧通过邀请码调用 **eh_collect_start**。本目录是技能包，不是单文件。
> 先安装再执行：macOS/Linux `bash scripts/install.sh`，Windows `powershell -File scripts/install.ps1`。
> 匹配规则细节见 `references/reference/SKILL.md`。

## 目标

在用户指定的本地目录中，根据自然语言功能描述（例如「实现 rag 的功能」）做模糊匹配，找出与该功能实现相关的目录和源码文件，打包为一个保留相对路径的 zip，并在输出目录生成一份 `manifest.csv`。

## 输入

| 参数 | 必填 | 默认 | 说明 | 校验 |
|------|------|------|------|------|
| `input_dir` | 是 | | 要扫描的本地源目录 | 必须是已存在的本地目录，且不是 `/` |
| `feature_query` | 是 | | 用自然语言描述要找的功能，例如「实现 rag 的功能」 | 非空，1–500 字 |
| `output_dir` | 否 | `./out` | 只在此目录写入 zip 和清单 | 非 `/`；不得等于或位于源目录之内，源目录也不得位于其内 |
| `extra_keywords` | 否 | | 额外关键词，逗号或空格分隔，用于补充描述里抽不到的词 | 可空；单项不含路径分隔符 |

## 安装

用户 Agent 从 `eh_collect_start` 拿到 `package_files` 后，先按相对路径落盘，再执行：

- macOS/Linux：`bash scripts/install.sh`
- Windows：`powershell -ExecutionPolicy Bypass -File scripts/install.ps1`

## 执行步骤

安装完成后，用已确认的槽位环境变量执行对应脚本：

- macOS/Linux：`input_dir=… feature_query=… output_dir=… extra_keywords=… bash scripts/run.sh`
- Windows：在设置同名环境变量后执行 `powershell -ExecutionPolicy Bypass -File scripts/run.ps1`

脚本只做这些事：

1. 校验源目录存在，且输出目录与源目录不互相包含。
2. 从 `feature_query` 抽出英文标识符和中文词块，再并入 `extra_keywords`。停用词（实现、功能、相关、代码、文件、目录、的、和、与）不参与匹配。
3. 跳过 `.git`、`node_modules`、`vendor`、`dist`、`build`、`target`、`__pycache__`、`.next` 等目录，以及常见二进制/压缩包后缀。
4. 对剩余文本文件做大小写不敏感匹配：文件名、目录名、文件内容。单个文件超过 2MiB 只匹配路径，不读内容。
5. 命中文件打入 zip，路径保持相对源目录，不扁平化。zip 与 `manifest.csv` 只写到输出目录。
6. 清单列：`relative_path,match_reason,keywords`。`match_reason` 为 `path`、`content` 或 `path+content`。

## 成功标准

- [ ] 输出目录内生成一个 zip，且 zip 内路径相对源目录、未扁平化
- [ ] 同目录生成 `manifest.csv`，每个打入 zip 的文件有一行，含命中原因和关键词
- [ ] 源目录没有任何文件被修改或删除
- [ ] 无命中时仍生成空清单（仅表头）和空 zip，并向用户说明 0 个命中，而不是失败退出

## 安全

- 不改、不删源文件；产物只写用户指定的输出目录
- 不跟随源目录之外的符号链接
- 跳过 `.env`、私钥、证书类文件名，不把它们打进包
- 路径拒绝 `..` 穿越；源目录与输出目录不得互相包含

## 输出给用户的汇报

- zip 路径、清单路径
- 命中文件数、实际使用的关键词
- 若为 0 命中，列出关键词，便于用户改描述或补 `extra_keywords` 后重试
