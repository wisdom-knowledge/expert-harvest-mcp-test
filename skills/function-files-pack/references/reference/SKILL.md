---
name: reference
kind: sub-skill
summary: 功能模糊匹配的关键词、跳过规则和清单格式。
---

# Reference

## 匹配

- 从 `feature_query` 抽取连续英文标识符（如 `rag`、`vector_store`）和长度不少于 2 的中文词块。
- `extra_keywords` 按逗号、顿号或空白拆开后并入，不再做词干或同义词扩展。
- 停用词不参与匹配：实现、功能、相关、代码、文件、目录、的、和、与。
- 路径（文件名 + 父目录名）和文件正文都做大小写不敏感子串匹配。
- 只打包命中文件，不把未命中的兄弟文件打进去。zip 保留相对源目录的路径。

## 跳过

- 目录：`.git`、`node_modules`、`vendor`、`dist`、`build`、`target`、`__pycache__`、`.next`，以及点开头目录。
- 二进制和压缩包后缀不读、不打包。
- `.env`、私钥、`.pem`、`.key` 不打包。
- 大于 2MiB 的文本文件只做路径匹配，不读正文。
- 不跟随符号链接。

## 清单

`manifest.csv` 列：`relative_path,match_reason,keywords`。

- `path`：只在相对路径命中
- `content`：只在正文命中
- `path+content`：两边都命中
