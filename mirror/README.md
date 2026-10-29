# 镜像：让 iMorph 包在墙内直连下载（不用任何代理软件）

## 原理

GitHub 的服务器在境外，拉 mega.nz 不受墙影响；而 GitHub 的 Release 附件在国内**直连可达**
（实测 `objects.githubusercontent.com` 返回 200）。所以让 GitHub 定时把包搬过来，
你在国内直接下 Release 附件即可。万一哪天 GitHub 也慢，还有公开加速站垫着
（实测可达：`gh-proxy.com`、`ghfast.top`）。

```
imorph.dev ──(GitHub Actions, 境外)──> Mega ──> 你的仓库 Release
                                                  ↑
                          国内浏览器/本程序 ────────┘  （直连或走加速站）
```

## 一次性配置（约 3 分钟）

1. 在 GitHub 上建一个仓库，比如 `imorph-mirror`（Public 就行）。
2. 把本目录上级的这些东西传上去（网页版「Add file → Upload files」即可，不用装 git）：
   - `mirror/mirror_mega.py`
   - `mirror/manifest.json`（可以不放，第一次跑会自动生成）
   - `.github/workflows/mirror.yml`
   - `imorph_get.py`（脚本会 import 它）
3. 打开仓库的 **Actions** 标签 → 允许 workflows → 点 `mirror imorph` → **Run workflow**。
4. 等 2-5 分钟，仓库 **Releases** 里会出现 `latest`，里面是全部 33 个 zip + `manifest.json`。

之后每 6 小时自动更新一次，你什么都不用管。

## 下载（不需要代理）

浏览器直接开（把 `USER/REPO` 换成你的）：

```
https://github.com/USER/REPO/releases/tag/latest
```

慢的话在地址前加加速站：

```
https://gh-proxy.com/https://github.com/USER/REPO/releases/download/latest/<文件名>
https://ghfast.top/https://github.com/USER/REPO/releases/download/latest/<文件名>
```

## 让本程序走镜像（完全不用代理）

```
imorph-cli.exe mirror era --tab china --manifest https://gh-proxy.com/https://github.com/USER/REPO/releases/download/latest/manifest.json
imorph-cli.exe mirror --all --manifest <同上>
```

GUI 里也有「无代理模式：从镜像站下载」一行：把 manifest 地址粘进去，点按钮，剩下的它自己做
（逐个文件校验 size 和 sha256）。

## 实测数据（2026-10-29，本机直连、不走代理）

| 目标 | 结果 |
|---|---|
| objects.githubusercontent.com（Release 附件） | 200 |
| github.com / api.github.com | 200 |
| gh-proxy.com / ghfast.top | 200 |
| raw.githubusercontent.com | 连不上 |
| ghproxy.com / kkgithub.com / bgithub.xyz | 连不上 |
| workers.dev / vercel.app / 在线网页代理站（croxyproxy、proxysite…） | 连不上 |
| mega.nz / g.api.mega.co.nz / gfs*.userstorage.mega.co.nz | 连不上（5 秒超时） |
