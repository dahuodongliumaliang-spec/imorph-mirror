#!/usr/bin/env python
"""imorph_get.py — 从 imorph.dev 取 iMorph 版本包（自动穿透 Mega）。

imorph.dev 本身走 Cloudflare，一般能直连；真正卡住的是它所有下载链接都在
mega.nz（国内 DNS 污染 + 封端口）。本脚本只做三件事：

  1. 抓 https://www.imorph.dev/download 并解析出每个版本的 Base / Net / Menu 链接
  2. 把 mega.nz/file/<id>#<key> 解析成真实下载地址（Mega 公开链接 API）
  3. 流式下载到本地，带 size 校验（文件都很小，130KB 级别）

用法：
  python imorph_get.py list                      # 只列出，不下载
  python imorph_get.py get era                   # 下载 Classic Era 的 Base+Net+Menu
  python imorph_get.py get era --set base        # 只下 Base
  python imorph_get.py get anniversary -o D:/iMorph
  python imorph_get.py list --tab china          # 看 China 镜像那栏

代理：默认自动探测（环境变量 → 127.0.0.1:7890 → 7891 → 10809 → 1080），
      --proxy http://127.0.0.1:7890 可指定，--no-proxy 关闭。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PAGE = "https://www.imorph.dev/download"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
PROXY_CANDIDATES = ["http://127.0.0.1:7890", "http://127.0.0.1:7897",
                    "http://127.0.0.1:7891", "http://127.0.0.1:7899",
                    "http://127.0.0.1:10809", "http://127.0.0.1:1080"]

# 镜像模式下用来加速 GitHub 的公开加速站（实测国内直连可达）
ACCELERATORS = ["", "https://gh-proxy.com/", "https://ghfast.top/"]

ALIASES = {
    "era": "classic era", "classicera": "classic era", "史": "classic era",
    "anniv": "anniversary", "anniversary": "anniversary", "周年": "anniversary",
    "retail": "retail", "正式": "retail",
    "classic": "classic", "经典": "classic",
    "titan": "classic titan", "forever": "forever", "永久": "forever",
}

FORCE_DIRECT = False          # --no-proxy：连 Windows 注册表里的系统代理也不认


def _http_client(timeout: float):
    """mega_client 默认 trust_env=True，会吃 Windows 系统代理；--no-proxy 时要关掉。"""
    import httpx
    return httpx.Client(timeout=timeout, trust_env=not FORCE_DIRECT)


@dataclass
class Entry:
    tab: str
    title: str
    version: str
    links: dict = field(default_factory=dict)   # {"base": url, ...}

    @property
    def label(self):
        return f"{self.title} [{self.version}]" if self.version else self.title


# ---------------------------------------------------------------- 解析页面
CARD_RE = re.compile(r'<div class="card mb-3">(.*?)</div>\s*</div>\s*</div>', re.S)
TITLE_RE = re.compile(r'<h5 class="card-title[^"]*">(.*?)</h5>', re.S)
VER_RE = re.compile(r'<small class="text-muted">(.*?)</small>', re.S)
LINK_RE = re.compile(r'<a href="(https?://[^"]+)"[^>]*>(Base|Net|Menu)</a>', re.I)


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def parse(html: str) -> list[Entry]:
    out: list[Entry] = []
    for tab in ("global", "china"):
        m = re.search(rf'id="{tab}".*?(?=<div class="tab-pane|$)', html, re.S)
        if not m:
            continue
        pane = m.group(0)
        for card in CARD_RE.findall(pane):
            t = TITLE_RE.search(card)
            if not t:
                continue
            title = _clean(t.group(1))
            v = VER_RE.search(card)
            version = _clean(v.group(1)) if v else ""
            links = {name.lower(): url for url, name in LINK_RE.findall(card)}
            if links:
                out.append(Entry(tab, title, version, links))
    return out


def fetch_page(proxy: str | None) -> str:
    handlers = []
    req = urllib.request.Request(PAGE, headers={"User-Agent": UA})
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))   # 忽略环境变量，强制直连
    opener = urllib.request.build_opener(*handlers)
    with opener.open(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- 代理探测
def _port_open(proxy: str) -> bool:
    try:
        hp = proxy.split("//")[-1].split("/")[0]
        host, _, port = hp.rpartition(":")
        with socket.socket() as s:
            s.settimeout(0.4)
            return s.connect_ex((host or "127.0.0.1", int(port))) == 0
    except Exception:                                 # noqa: BLE001
        return False


def system_proxy() -> str | None:
    """Windows 注册表里的系统代理（Clash「系统代理」开关打开时就是它）。"""
    try:
        p = urllib.request.getproxies()
    except Exception:                                 # noqa: BLE001
        return None
    return p.get("https") or p.get("http")


def resolve_proxy(explicit: str | None, no_proxy: bool) -> tuple[str | None, str]:
    """返回 (代理地址, 给人看的说明)。说明里会点名「端口不通」。"""
    if no_proxy:
        return None, "关闭（--no-proxy，强制直连）"
    if explicit:
        return explicit, f"{explicit}（手动指定{'，端口通' if _port_open(explicit) else '，端口不通！'}）"
    for k in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        if os.environ.get(k):
            return os.environ[k], f"{os.environ[k]}（环境变量）"
    sp = system_proxy()
    if sp:
        if _port_open(sp):
            return sp, f"{sp}（系统代理，端口通）"
        return sp, f"{sp}（系统代理，但端口不通 —— 代理软件是不是没开？）"
    for cand in PROXY_CANDIDATES:
        if _port_open(cand):
            return cand, f"{cand}（自动探测，端口通）"
    return None, "无（直连，Mega 大概率连不上）"


def detect_proxy(explicit: str | None, no_proxy: bool) -> str | None:
    return resolve_proxy(explicit, no_proxy)[0]


def apply_proxy_env(proxy: str | None):
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    if proxy:
        os.environ["http_proxy"] = os.environ["https_proxy"] = proxy
        os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = proxy


# ---------------------------------------------------------------- Mega
def mega_info(urls: dict[str, str]) -> dict[str, tuple[str, int]]:
    """{setname: (filename, size)}"""
    from mega_client import MegaClient
    res = {}
    with MegaClient(timeout=60.0, http_client=_http_client(60.0)) as c:
        for name, url in urls.items():
            try:
                fi = c.get_file_info(url)
                res[name] = (fi.name, fi.size)
            except Exception as e:                      # noqa: BLE001
                res[name] = (f"<解析失败: {type(e).__name__}: {e}>", -1)
    return res


def mega_download(urls: dict[str, str], outdir: Path, progress_cb=None) -> list[Path]:
    from mega_client import MegaClient
    outdir.mkdir(parents=True, exist_ok=True)
    got = []
    with MegaClient(timeout=120.0, http_client=_http_client(120.0)) as c:
        for name, url in urls.items():
            last = [0.0]

            def cb(done, total, _n=name, _last=last):
                pct = (done / total * 100) if total else 0
                if progress_cb:
                    progress_cb(_n, done, total)
                if pct - _last[0] >= 20 or done == total:
                    _last[0] = pct
                    print(f"    {_n:5s} {done/1024:8.1f}/{total/1024:.1f} KB  {pct:5.1f}%")

            r = c.download_file(url, outdir, progress=cb)
            p = Path(r.path)
            print(f"  [OK] {name}: {p.name}  ({p.stat().st_size:,} bytes)")
            got.append(p)
    return got


# ---------------------------------------------------------------- CLI
# ---------------------------------------------------------------- 镜像模式（不需要代理）
def _direct_open(url: str, timeout: float = 180):
    """镜像模式全程直连，故意忽略系统代理——这条路本来就是给没代理的人用的。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return opener.open(req, timeout=timeout)


def fetch_bytes(url: str) -> bytes:
    last: Exception | None = None
    for pre in ACCELERATORS:
        try:
            with _direct_open(pre + url) as r:
                return r.read()
        except Exception as e:                        # noqa: BLE001
            last = e
    raise RuntimeError(f"{url} 取不到（试过直连和加速站）：{last}")


def load_manifest(url: str) -> dict:
    return json.loads(fetch_bytes(url).decode("utf-8"))


def cmd_mirror(manifest_url: str, outdir: Path, edition: str | None = None,
               tab: str | None = None, want=("base", "net", "menu"), progress_cb=None) -> list[Path]:
    m = load_manifest(manifest_url)
    base = (m.get("release_base") or "").rstrip("/")
    want_title = ALIASES.get(edition.lower().replace("_", " ").strip(), edition.lower().strip()) if edition else None
    picks = [v for v in m.get("versions", [])
             if (not tab or v.get("tab") == tab)
             and (not want_title or v.get("title", "").lower().strip() == want_title)]
    if not picks:
        have = sorted({f"{v.get('tab')}/{v.get('title')}" for v in m.get("versions", [])})
        raise SystemExit(f"镜像里没有这个版本；可选：{', '.join(have)}")

    outdir.mkdir(parents=True, exist_ok=True)
    got: list[Path] = []
    for v in picks:
        print(f"→ {v.get('title')} [{v.get('tab')}] {v.get('version','')}")
        for kind, meta in (v.get("files") or {}).items():
            if kind not in want:
                continue
            url = meta.get("url") or f"{base}/{urllib.parse.quote(meta['name'])}"
            data = fetch_bytes(url)
            if meta.get("size") and len(data) != meta["size"]:
                raise RuntimeError(f"{meta['name']} 大小不对：{len(data)} != {meta['size']}")
            if meta.get("sha256") and hashlib.sha256(data).hexdigest() != meta["sha256"]:
                raise RuntimeError(f"{meta['name']} sha256 校验失败")
            p = outdir / meta["name"]
            p.write_bytes(data)
            print(f"  [OK] {p.name}  ({len(data):,} 字节)")
            got.append(p)
            if progress_cb:
                progress_cb(len(got))
    return got


def pick(entries: list[Entry], want: str, tab: str) -> Entry | None:
    want = ALIASES.get(want.lower().replace("_", " ").strip(), want.lower().strip())
    cands = [e for e in entries if e.title.lower().strip() == want]
    if not cands:
        return None
    if tab == "auto":                 # 同一版本两栏各有一份时，取版本号/时间更新的一栏
        order = {"global": 0, "china": 1}
        cands.sort(key=lambda e: order.get(e.tab, 9))
        return cands[0]
    for e in cands:
        if e.tab == tab:
            return e
    return None


def cmd_list(entries, tab, do_info, proxy):
    for e in (x for x in entries if tab == "auto" or x.tab == tab):
        print(f"[{e.tab:6s}] {e.title:16s} {e.version}")
        info = {}
        if do_info:
            info = mega_info(e.links)
        for k, url in e.links.items():
            extra = ""
            if k in info:
                fn, sz = info[k]
                extra = f"  →  {fn}  ({sz/1024:.1f} KB)" if sz >= 0 else f"  →  {fn}"
            print(f"          {k:5s} {url.split('#')[0]}{extra}")
    print("\n提示：get <版本> 下载，例如 `get era`、`get anniversary`、`get retail`")


def exe_dir() -> Path:
    """打包成 exe 后，默认输出到 exe 同级的 dist\\；源码运行时是脚本目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _ask(prompt: str, default: str = "") -> str:
    try:
        s = input(prompt).strip()
    except EOFError:
        return default
    return s or default


def pause(msg: str = "\n按回车键关闭窗口…") -> None:
    """双击运行时别一闪而过；管道/脚本调用时直接跳过。"""
    try:
        if sys.stdin and sys.stdin.isatty():
            input(msg)
    except Exception:                                 # noqa: BLE001
        pass


def force_utf8_console() -> None:
    """cmd.exe 默认 936 代码页会把中文写花；统一成 UTF-8。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:                                 # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                             # noqa: BLE001
            pass


def cmd_menu(entries, proxy) -> None:
    """双击打开时的交互界面：选版本序号 → 选包 → 输出目录。"""
    print("=" * 78)
    print(" iMorph 下载器   来源: imorph.dev/download   代理:", proxy or "直连")
    print("=" * 78)
    for i, e in enumerate(entries, 1):
        print(f"  {i:2d}. [{e.tab:6s}] {e.title:24s} {e.version}")
    sel = _ask("\n输入版本序号（空格分隔可多选，q 退出）: ", "")
    if not sel or sel.lower() in ("q", "quit", "exit"):
        return
    picks = []
    for tok in sel.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(entries):
            picks.append(entries[int(tok) - 1])
        else:
            print(f"  ! 忽略无效序号 {tok!r}")
    if not picks:
        return

    setsel = _ask("下载哪些包 [base net menu]（回车=全部）: ", "base,net,menu")
    want = [s.strip().lower() for s in setsel.replace("+", ",").split(",") if s.strip()]
    want = [s for s in want if s in ("base", "net", "menu")] or ["base", "net", "menu"]
    outdir = Path(_ask(f"输出目录（回车={exe_dir() / 'dist'}）: ", str(exe_dir() / "dist")))

    ok = fail = 0
    for e in picks:
        urls = {k: v for k, v in e.links.items() if k in want}
        print(f"\n→ {e.title} [{e.tab}] {e.version}  ({'/'.join(urls)})")
        try:
            got = mega_download(urls, outdir)
            ok += len(got)
        except Exception as ex:                    # noqa: BLE001
            fail += 1
            detail = str(ex) or repr(ex) or "无详细信息"
            print(f"  [FAIL] 失败: {type(ex).__name__}: {detail}")
            if "Connect" in type(ex).__name__ or "Timeout" in type(ex).__name__:
                print("     ↳ 网络层不通：检查代理是否开着、节点是否可用（Clash 里换个节点试试）")
    print(f"\n完成 {ok} 个文件" + (f"，{fail} 个版本失败" if fail else "") + f" → {outdir}")


def cmd_selftest() -> None:
    """自检：确认打包进去的依赖、AES-CTR 解密、页面解析都正常。"""
    import hashlib
    import platform

    print(f"python      : {platform.python_version()}  {'(frozen exe)' if getattr(sys, 'frozen', False) else '(源码)'}")
    try:
        import mega_client
        print(f"mega_client : {mega_client.__name__} OK")
    except Exception as e:                            # noqa: BLE001
        print(f"mega_client : FAIL {type(e).__name__}: {e}")
        return
    try:
        import httpx
        print(f"httpx       : {httpx.__version__}")
    except Exception as e:                            # noqa: BLE001
        print(f"httpx       : FAIL {e}")
    from Crypto.Cipher import AES
    key, iv, data = b"k" * 16, b"i" * 16, bytes(range(256)) * 40
    ct = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=int.from_bytes(iv, "big")).encrypt(data)
    pt = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=int.from_bytes(iv, "big")).decrypt(ct)
    print(f"aes-ctr     : {'OK' if pt == data else 'FAIL'}  sha256={hashlib.sha256(pt).hexdigest()[:16]}")
    try:
        entries = parse(fetch_page(None))
        print(f"页面解析    : {len(entries)} 个版本 / {sum(len(e.links) for e in entries)} 个链接")
    except Exception as e:                            # noqa: BLE001
        print(f"页面解析    : FAIL {type(e).__name__}: {e}")
    proxy, note = resolve_proxy(None, False)
    print(f"代理        : {note}")


def main(argv=None):
    force_utf8_console()
    ap = argparse.ArgumentParser(description="从 imorph.dev 下载 iMorph 版本包（自动走 Mega）")
    ap.add_argument("action", nargs="?", default="menu", choices=["menu", "list", "get", "selftest", "mirror"])
    ap.add_argument("edition", nargs="?", help="era / anniversary / retail / classic / titan / forever")
    ap.add_argument("--set", default="base,net,menu", help="要下载的包，逗号分隔（默认 base,net,menu）")
    ap.add_argument("-o", "--out", default=None, help="输出目录（默认 exe 同级的 dist）")
    ap.add_argument("--tab", default="auto", choices=["auto", "global", "china"])
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--info", action="store_true", help="list 时顺便解析 Mega 文件名/大小")
    ap.add_argument("--manifest", default="", help="mirror 模式：镜像的 manifest.json 地址")
    ap.add_argument("--all", action="store_true", help="mirror 模式：镜像里所有版本都下")
    a = ap.parse_args(argv)

    if a.action == "selftest":
        cmd_selftest()
        pause()
        return

    if a.action == "mirror":
        if not a.manifest:
            pause()
            sys.exit("mirror 需要 --manifest <manifest.json 地址>")
        want = [s.strip().lower() for s in a.set.split(",") if s.strip()]
        try:
            got = cmd_mirror(a.manifest, Path(a.out) if a.out else exe_dir() / "dist",
                             edition=None if a.all else a.edition,
                             tab=None if a.tab == "auto" else a.tab,
                             want=want)
        except SystemExit:
            raise
        except Exception as ex:                       # noqa: BLE001
            pause()
            sys.exit(f"镜像下载失败：{type(ex).__name__}: {ex}")
        print(f"\n完成 {len(got)} 个文件（镜像模式，全程没用代理）")
        pause()
        return

    global FORCE_DIRECT
    FORCE_DIRECT = a.no_proxy
    proxy, pnote = resolve_proxy(a.proxy, a.no_proxy)
    print(f"代理: {pnote}", file=sys.stderr)
    try:
        html = fetch_page(None)                       # imorph.dev 走 Cloudflare，通常直连即可
    except Exception as e:                            # noqa: BLE001
        print(f"# imorph.dev 直连失败（{type(e).__name__}），改走代理重试", file=sys.stderr)
        html = fetch_page(proxy)
    entries = parse(html)
    if not entries:
        pause()
        sys.exit("解析失败：页面结构可能变了，请把 HTML 存下来再看")

    apply_proxy_env(proxy)

    if a.action == "list":
        cmd_list(entries, a.tab, a.info, proxy)
        pause()
        return
    if a.action == "menu":
        cmd_menu(entries, pnote)
        pause()
        return

    if not a.edition:
        pause()
        sys.exit("get 需要版本名，例如 `get era`")
    e = pick(entries, a.edition, a.tab)
    if not e:
        have = sorted({x.title for x in entries})
        pause()
        sys.exit(f"没找到版本 {a.edition!r}；可选: {', '.join(have)}")
    want = [s.strip().lower() for s in a.set.split(",") if s.strip()]
    urls = {k: v for k, v in e.links.items() if k in want}
    if not urls:
        pause()
        sys.exit(f"{e.label} 没有这些包: {want}；它有 {list(e.links)}")

    print(f"→ {e.label}  [{e.tab}]")
    outdir = Path(a.out) if a.out else exe_dir() / "dist"
    try:
        got = mega_download(urls, outdir)
    except Exception as ex:                        # noqa: BLE001
        pause()
        sys.exit(
            f"下载失败 —— {type(ex).__name__}: {str(ex) or repr(ex) or '无详细信息'}\n"
            f"代理状态: {pnote}\n"
            "Mega（mega.nz / g.api.mega.co.nz）在国内被 DNS 污染 + 连接超时，没代理就下不动。\n"
            "对策：把 Clash / V2Ray 打开并启用「系统代理」，或用 --proxy 指定端口（常见 7890）。"
        )
    print(f"\n完成 {len(got)} 个文件 → {outdir.resolve()}")
    pause()


if __name__ == "__main__":
    main()