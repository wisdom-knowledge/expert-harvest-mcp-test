---
name: github-all-branches-commit-pack
version: 0.2.0
kind: flow-skill
tags: [github, git, commits, branches, archive]
summary: 输入 GitHub 仓库地址，按分支导出全部可达提交历史和可恢复 Git bundle，并生成 ZIP。
---

# GitHub All Branches Commit Pack

## 目标

采集 GitHub 仓库当前可见的全部 refs/heads 分支。每个分支独立目录，包含完整可达提交历史（包括 merge 的所有父链）、作者统计和自包含 Git bundle；生成总 ZIP、清单和 SHA-256 校验文件。共同祖先在各分支中分别保留。不包含已删除或无权限访问的分支、PR 隐藏引用。bundle 包含被跟踪文件的历史内容；不下载 Git LFS 外部对象及子模块仓库。

## 输入

- github_url：必填。https://github.com/OWNER/REPO[.git] 或 git@github.com:OWNER/REPO[.git]。未提供时向用户询问。
- out_dir：可选，默认当前工作目录的 out。
- 依赖：Git 与 Python 3。私有仓库使用现有 Git credential helper 或 SSH agent。

## 执行步骤

1. 确认用户授权采集目标仓库，确认可用磁盘空间。默认采集全部当前可见分支，不限制提交数。
2. 将下方 Python 代码保存为工作目录中的 collect.py，以参数数组调用 python3 collect.py github_url [out_dir]。不要将用户输入拼接进 shell。
3. 脚本创建全新临时 bare 仓库，只抓取 refs/heads/*，以抓取成功后的引用为本次快照。失败立即报错，不把部分结果当作成功。
4. 输出到新的随机命名目录；绝不覆盖或删除已有产物。分支目录使用稳定序号，原名在 manifest 和 SUMMARY 中保留，避免斜杠、大小写或字符替换造成冲突。
5. 成功后返回 ZIP、校验文件、SUMMARY 的绝对路径，以及分支数和各分支提交数。失败只报告阶段及退出码，不转发可能带认证信息的 Git stderr；必要时由用户本地检查凭据。

```python
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from zipfile import ZipFile, ZIP_DEFLATED

def parse_url(value):
    patterns = (
        r"https://github[.]com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/?",
        r"git@github[.]com:([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)",
    )
    match = next((m for p in patterns if (m := re.fullmatch(p, value))), None)
    if not match:
        raise ValueError("Expected credential-free GitHub repository URL")
    owner, repo = match.groups()
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo in ("", ".", ".."):
        raise ValueError("Invalid repository name")
    canonical = "https://github.com/" + owner + "/" + repo
    transport = canonical + ".git"
    if value.startswith("git@"):
        transport = "git@github.com:" + owner + "/" + repo + ".git"
    return canonical, transport, repo

def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n",
                    encoding="utf-8")

def run_git(repo, *args, output=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    command = ["git", "-c", "core.hooksPath=/dev/null"]
    if repo is not None:
        command += ["-C", str(repo)]
    result = subprocess.run(
        command + list(args), env=env,
        stdout=output if output is not None else subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RuntimeError("Git stage " + args[0] + " failed (exit "
                           + str(result.returncode) + "); no complete archive")
    return result.stdout if output is None else b""

def collect(url, out):
    canonical, transport, repo_name = parse_url(url)
    out = Path(out).expanduser()
    if ".." in out.parts:
        raise ValueError("Output path must not contain ..")
    out.mkdir(parents=True, exist_ok=True)
    out = out.resolve()
    with tempfile.TemporaryDirectory(prefix="github-history-") as temp:
        bare = Path(temp) / "repo.git"
        run_git(None, "init", "--bare", str(bare))
        run_git(bare, "fetch", "--no-tags", transport,
                "+refs/heads/*:refs/heads/*")
        refs = run_git(bare, "for-each-ref", "--sort=refname",
                       "--format=%(refname)", "refs/heads/").decode("utf-8").splitlines()
        if not refs:
            raise ValueError("Repository has no visible branches")
        if run_git(bare, "rev-parse", "--is-shallow-repository").strip() != b"false":
            raise RuntimeError("Incomplete shallow history")
        # A fresh directory makes retries non-destructive.
        run_dir = Path(tempfile.mkdtemp(prefix=repo_name + "-", dir=out))
        pack = run_dir / "history"
        branches = pack / "branches"
        branches.mkdir(parents=True)
        records = []
        for index, ref in enumerate(refs, 1):
            name = ref[len("refs/heads/"):]
            folder = "branch-" + str(index).zfill(6)
            dest = branches / folder
            dest.mkdir()
            tip = run_git(bare, "rev-parse", "--verify", ref).decode().strip()
            count = int(run_git(bare, "rev-list", "--count", tip))
            roots = run_git(bare, "rev-list", "--max-parents=0", tip).decode().splitlines()
            exports = {
                "commits.full.txt": ["log", "--no-decorate", "--format=fuller",
                                     "--date=iso-strict", tip],
                "commits.oneline.txt": ["log", "--no-decorate", "--format=%H %s", tip],
                "commits.sha.txt": ["rev-list", tip],
                "authors.txt": ["shortlog", "-sn", tip],
                "changes.stat.txt": ["log", "--no-decorate", "--format=fuller",
                                     "--stat", "--root", tip],
            }
            for filename, args in exports.items():
                with (dest / filename).open("wb") as stream:
                    run_git(bare, *args, output=stream)
            bundle = dest / "history.bundle"
            run_git(bare, "bundle", "create", str(bundle), ref)
            run_git(bare, "bundle", "verify", str(bundle))
            with (dest / "commits.sha.txt").open("rb") as stream:
                if sum(1 for _ in stream) != count:
                    raise RuntimeError("Commit count mismatch")
            record = dict(branch=name, ref=ref, tip=tip, roots=roots,
                          commit_count=count, directory="branches/" + folder)
            write_json(dest / "manifest.json", record)
            records.append(record)
        manifest = dict(repository=canonical,
                        generated_at=datetime.now(timezone.utc).isoformat(),
                        branch_count=len(records), branches=records,
                        scope="All ancestors of visible branch tips; no LFS or submodule objects")
        write_json(pack / "manifest.json", manifest)
        lines = ["# GitHub Branch History", "", canonical, "",
                 "Branches: " + str(len(records)), ""]
        for record in records:
            # JSON quoting preserves exact names without table escaping ambiguities.
            lines.append("- " + json.dumps(record["branch"], ensure_ascii=True)
                         + ": " + str(record["commit_count"]) + " commits; "
                         + record["directory"])
        (pack / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        checksums = {}
        for path in sorted(pack.rglob("*")):
            if path.is_file():
                checksums[path.relative_to(pack).as_posix()] = digest(path)
        write_json(pack / "SHA256SUMS.json", checksums)
        archive = run_dir / "history.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED, allowZip64=True) as zipped:
            for path in sorted(pack.rglob("*")):
                if path.is_file():
                    zipped.write(path, path.relative_to(run_dir).as_posix())
        with ZipFile(archive) as zipped:
            if zipped.testzip() is not None:
                raise RuntimeError("ZIP integrity check failed")
            for relative, expected in checksums.items():
                actual = hashlib.sha256()
                with zipped.open("history/" + relative) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        actual.update(block)
                if actual.hexdigest() != expected:
                    raise RuntimeError("Archive checksum mismatch")
        checksum = run_dir / "history.zip.sha256"
        checksum.write_text(digest(archive) + "  history.zip\n", encoding="ascii")
        write_json(run_dir / "SUCCESS.json", dict(archive=str(archive), **manifest))
        print(json.dumps(dict(archive=str(archive), checksum=str(checksum),
                              summary=str(pack / "SUMMARY.md"),
                              branch_count=len(records)), indent=2))
        return run_dir

if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: python3 collect.py GITHUB_URL [OUT_DIR]")
    collect(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "out")
```

## 成功标准

- SUCCESS.json 只在所有分支、bundle 校验、ZIP 完整性和逐文件 SHA-256 校验通过后生成。
- 顶层 manifest 保留采集时间、仓库规范地址、全部分支与目录的映射。
- 每个分支 manifest 包含分支名、tip、全部根提交、commit_count。
- 每个分支完整 SHA 列表行数等于 Git rev-list --count；history.bundle 可用于恢复对应分支的 Git 历史。
- 最终 ZIP 按 branches/branch-000001 等目录分隔分支，有 SUMMARY 和校验清单。
- 任意 Git 或压缩校验失败都不是成功；保留本次未完成目录供诊断，重试生成新目录。

## 安全

- 只使用用户有权访问的仓库，不绕过认证。不执行仓库代码、hooks、构建或子模块命令。
- Git bundle 包含历史提交中的全部被跟踪内容，可能包括曾经提交的凭据或个人信息。不能声称其天然脱敏；交付给仓库授权用户，未经明确授权不得对外上传。
- URL 禁止凭据、query、fragment 或非 GitHub 主机。不得要求用户在聊天中提供令牌。
- 临时 bare 仓库通过 TemporaryDirectory 自动清理，只清理本流程创建的临时目录；不接触用户已有仓库。
- 输出路径拒绝 ..，每次新目录，不覆盖旧产物。分支名只写入数据，不作为路径或 shell 代码。
- 保持普通 Git 服务约束，不绕过限流；网络、权限或磁盘失败按失败报告。
