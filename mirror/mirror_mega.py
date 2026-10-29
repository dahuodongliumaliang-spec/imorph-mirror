"""把 imorph.dev 上的 iMorph 版本包搬到自己能访问的地方（GitHub Release / 任意静态站）。

两个用途：
  1. 在 GitHub Actions 里跑（境外网络，Mega 直连可达）→ 生成 manifest.json + 把包传进 Release
  2. 本地跑：给自己做一个离线镜像目录

用法：
  python mirror_mega.py build  --out mirror            # 下载全部 33 个包 + 写 manifest.json
  python mirror_mega.py build  --out mirror --tab china
  python mirror_mega.py manifest --out mirror --release-base https://github.com/USER/REPO/releases/download/latest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import imorph_get as core          # noqa: E402


def build(out: Path, tab: str, only: list[str] | None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    html = core.fetch_page(None)
    entries = core.parse(html)
    core.apply_proxy_env(core.resolve_proxy(None, False)[0])

    versions = []
    for e in entries:
        if tab != "auto" and e.tab != tab:
            continue
        if only and e.title.lower() not in only:
            continue
        files = {}
        print(f"== {e.tab} / {e.title} / {e.version}")
        got = core.mega_download(e.links, out)
        # mega_download 的返回顺序与 links 一致，按 base/net/menu 对回去
        for (kind, _url), p in zip(e.links.items(), got):
            data = p.read_bytes()
            files[kind] = {
                "name": p.name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        versions.append({"tab": e.tab, "title": e.title, "version": e.version, "files": files})
        print("   ->", ", ".join(f"{k}:{v['name']}" for k, v in files.items()))

    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": core.PAGE,
        "release_base": "",
        "versions": versions,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["build", "manifest"])
    ap.add_argument("--out", default="mirror")
    ap.add_argument("--tab", default="auto", choices=["auto", "global", "china"])
    ap.add_argument("--only", default="", help="只搬这些版本，逗号分隔，例如 'classic era,anniversary'")
    ap.add_argument("--release-base", default="")
    a = ap.parse_args()

    out = Path(a.out)
    if a.action == "build":
        only = [s.strip().lower() for s in a.only.split(",") if s.strip()] or None
        m = build(out, a.tab, only)
    else:
        m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if a.release_base:
        m["release_base"] = a.release_base
        (out / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest: {out / 'manifest.json'}  版本 {len(m['versions'])} 个")


if __name__ == "__main__":
    main()
