---
name: troubleshooting
kind: sub-skill
summary: 功能文件打包失败或 0 命中时的排查。
---

# Troubleshooting

- `no keywords extracted`：描述里没有可用词。换成含英文标识符的描述（如 rag），或填写 `extra_keywords`。
- `input_dir must not be inside output_dir` 或反向报错：把输出目录改到源目录之外，例如源目录旁的 `./out`。
- 命中为 0：看汇报里的 `keywords=`。中文描述不会自动扩展同义词，需要在 `extra_keywords` 补代码里真实出现的词，如 `retriever,embedding`。
- 漏了 `node_modules` 里的文件：这是故意跳过。不要把依赖目录当作功能实现来源。
- install 报权限：`chmod +x scripts/install.sh scripts/run.sh`。Windows 用 `powershell -File scripts/install.ps1`。
- `python is required`：本机需要 `python3`（Windows 上为 `python`）。脚本不安装第三方依赖。
