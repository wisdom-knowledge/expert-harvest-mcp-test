#!/usr/bin/env python3
"""Pack files related to a described feature. Writes only under output_dir."""
import csv
import os
import re
import sys
import zipfile
from pathlib import Path

STOP = {
    "实现", "功能", "相关", "代码", "文件", "目录", "所有", "一个",
    "的", "和", "与", "及", "在", "中", "把", "将", "进行", "有关",
}
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target",
    "__pycache__", ".next", "out", "coverage", ".idea", ".vscode",
}
BIN_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
    ".gz", ".tgz", ".bz2", ".7z", ".rar", ".woff", ".woff2", ".ttf",
    ".eot", ".mp4", ".mp3", ".wav", ".bin", ".exe", ".dll", ".so",
    ".dylib", ".class", ".jar", ".pyc", ".o", ".a",
}
SECRET_NAMES = {".env", ".env.local", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
SECRET_EXT = {".pem", ".key", ".p12", ".pfx"}
MAX_BYTES = 2 * 1024 * 1024


def keywords(query, extra):
    found = []
    found.extend(re.findall(r"[A-Za-z][A-Za-z0-9_+\-]{1,}", query))
    for tok in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        if tok not in STOP:
            found.append(tok)
    for tok in re.split(r"[\s,，、;；]+", extra.strip()):
        if tok:
            found.append(tok)
    seen, outk = set(), []
    for key in found:
        low = key.lower()
        if low in seen or key in STOP or len(key) < 2:
            continue
        seen.add(low)
        outk.append(key)
    return outk


def skip_file(path):
    name = path.name
    if name in SECRET_NAMES or name.startswith(".env"):
        return True
    ext = path.suffix.lower()
    return ext in BIN_EXT or ext in SECRET_EXT


def main():
    if len(sys.argv) != 5:
        sys.exit("usage: pack_feature.py input_dir feature_query output_dir extra_keywords")
    input_dir, feature_query, output_dir, extra_keywords = sys.argv[1:5]
    src = Path(input_dir).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()

    if not src.is_dir():
        sys.exit(f"input_dir is not a directory: {src}")
    if src == Path(src.anchor):
        sys.exit("refusing to scan filesystem root")
    try:
        src.relative_to(out)
        sys.exit("input_dir must not be inside output_dir")
    except ValueError:
        pass
    try:
        out.relative_to(src)
        sys.exit("output_dir must not be inside input_dir")
    except ValueError:
        pass

    keys = keywords(feature_query, extra_keywords)
    if not keys:
        sys.exit("no keywords extracted; set a clearer feature_query or extra_keywords")
    needles = [key.lower() for key in keys]

    hits = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        base = Path(dirpath)
        if base.is_symlink():
            continue
        for name in filenames:
            fp = base / name
            if fp.is_symlink() or not fp.is_file() or skip_file(fp):
                continue
            rel = fp.relative_to(src).as_posix()
            path_hit = [k for k, n in zip(keys, needles) if n in rel.lower()]
            content_hit = []
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if size <= MAX_BYTES:
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore").lower()
                except OSError:
                    text = ""
                content_hit = [k for k, n in zip(keys, needles) if n in text]
            if not path_hit and not content_hit:
                continue
            if path_hit and content_hit:
                reason = "path+content"
            elif path_hit:
                reason = "path"
            else:
                reason = "content"
            matched = [k for k in keys if k in path_hit or k in content_hit]
            hits.append((rel, reason, " ".join(matched), fp))

    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / "function-files-pack.zip"
    manifest = out / "manifest.csv"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, _reason, _matched, fp in hits:
            zf.write(fp, rel)
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["relative_path", "match_reason", "keywords"])
        for rel, reason, matched, _fp in hits:
            writer.writerow([rel, reason, matched])

    print(f"zip={zip_path}")
    print(f"manifest={manifest}")
    print(f"hits={len(hits)}")
    print("keywords=" + ",".join(keys))


if __name__ == "__main__":
    main()
