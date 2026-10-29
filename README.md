# iMorph 镜像（国内直连下载）

把 [imorph.dev](https://www.imorph.dev/download) 上的 iMorph 版本包自动镜像到本仓库的 Release。
GitHub 的服务器在境外，拉 mega.nz 不受墙影响；而 Release 附件在国内可以直连下载，
所以**不用任何代理软件**就能拿到文件。

## 下载

最新版本在 **[Releases → latest](../../releases/tag/latest)**。

单个文件直链（`USER/REPO` 换成实际仓库）：

```
https://github.com/USER/REPO/releases/download/latest/<文件名>
```

GitHub 慢的时候在前面加公开加速站（实测国内可达）：

```
https://gh-proxy.com/https://github.com/USER/REPO/releases/download/latest/<文件名>
https://ghfast.top/https://github.com/USER/REPO/releases/download/latest/<文件名>
```

## 自动更新

`.github/workflows/mirror.yml` 每 6 小时跑一次：抓 imorph.dev 的下载页 → 从 Mega 拉全部
33 个包 → 发布到 Release `latest` → 更新 `mirror/manifest.json`（含每个文件的 size 和 sha256）。

也可以在 Actions 页手动点 **Run workflow**。

## 配套下载器

本仓库的 `imorph_get.py` 支持镜像模式，可逐文件校验 sha256：

```
imorph-cli.exe mirror --all --manifest https://gh-proxy.com/https://github.com/USER/REPO/releases/download/latest/manifest.json
```

GUI 版（iMorph下载器.exe）底部有「无代理模式：从镜像站下载」，把 manifest 地址粘进去即可。

## 说明

- 本仓库只是搬运，不修改任何文件；版权归 iMorph 作者。
- `global` 与 `china` 两栏都会镜像：`china` 是国服客户端专用构建。
- 若上游删除或改名，旧的 Release 附件会保留到下一次成功运行。
