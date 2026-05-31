# Instagram Downloader

Instagram 媒体下载工具，可下载公开或私有账号的图片、视频、个人主页头像、帖子说明、评论、地理位置、Stories、收藏内容等数据。

> 本项目与 Instagram、Meta 或其关联公司无官方关系。请自行承担使用风险，并遵守目标平台条款和当地法律法规。

## 功能特性

- 下载公开账号、私有账号、话题标签、Stories、Feed 和收藏内容。
- 支持下载帖子图片、视频、说明文字、评论、地理位置和 JSON 元数据。
- 支持登录后访问私有内容，并复用本地 session。
- 支持断点续传和 `--fast-update` 快速更新。
- 支持按条件过滤帖子，便于构建个人归档流程。
- 可作为命令行工具使用，也可作为 Python 模块集成。

## 环境要求

- Python 3.9 或更高版本
- pip 或 pipenv

## 安装依赖

使用 pip：

```bash
pip install -e .
```

或使用 pipenv 安装开发依赖：

```bash
python -m pip install pipenv==2025.0.4
pipenv --python 3.13 sync --dev
```

如果本机 Python 版本不同，请把 `3.13` 替换为你实际使用的 Python 3.9+ 版本。

## 基本使用

查看帮助：

```bash
python -m instaloader --help
```

下载公开账号：

```bash
python -m instaloader profile_name
```

更新已下载账号，遇到第一个已存在帖子后停止：

```bash
python -m instaloader --fast-update profile_name
```

登录后下载私有账号：

```bash
python -m instaloader --login your_username profile_name
```

下载话题标签：

```bash
python -m instaloader "#hashtag"
```

下载个人 Feed 或收藏内容：

```bash
python -m instaloader --login your_username :feed
python -m instaloader --login your_username :saved
```

## 常用选项

- `--comments`：下载评论。
- `--geotags`：下载地理位置，需要登录。
- `--stories`：下载 Stories，需要登录。
- `--highlights`：下载精选 Stories。
- `--tagged`：下载账号被标记的帖子。
- `--reels`：下载 Reels。
- `--igtv`：下载 IGTV 视频。
- `--fast-update`：快速更新已有归档。
- `--latest-stamps`：记录每个账号最后下载时间，只下载较新的媒体。
- `--no-metadata-json`：不保存 JSON 元数据。
- `--dirname-pattern`：自定义下载目录名称。
- `--filename-pattern`：自定义文件名前缀。

更多参数请运行：

```bash
python -m instaloader --help
```

## 作为 Python 模块使用

```python
import instaloader

loader = instaloader.Instaloader()
profile = instaloader.Profile.from_username(loader.context, "profile_name")

for post in profile.get_posts():
    loader.download_post(post, target=profile.username)
```

## 开发与检查

运行 lint 和类型检查：

```bash
pipenv run pylint instaloader
pipenv run mypy -m instaloader
```

运行测试：

```bash
pipenv run python -m unittest test.instaloader_unittests
```

注意：测试会访问 Instagram，结果可能受到网络、平台接口变化、登录状态和频率限制影响。

构建文档：

```bash
pipenv run make -C docs html SPHINXOPTS="-W -n"
```

## 项目结构

```text
instaloader/      核心 Python 包
test/             单元测试和集成测试
docs/             Sphinx 文档
deploy/           打包与发布脚本
instaloader.py    命令行入口代理脚本
setup.py          包安装配置
```

## 许可证

本项目使用 MIT License，详情见 `LICENSE`。
