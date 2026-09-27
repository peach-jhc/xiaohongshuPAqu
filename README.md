
# 小红书视频自动化工具

一个用于下载小红书视频并进行批量切割处理的 Python 脚本项目。

## 文件说明

### `download_xhs_videos.py`

用于：

- 获取指定小红书账号的作品
- 下载无水印原视频
- 第一次运行时扫码登录
- 保存浏览器登录状态
- 后续运行时自动复用登录状态

### `cut_xhs_videos.py`

用于：

- 批量读取已经下载的视频
- 按配置参数筛选、切割视频
- 输出处理后的视频文件

### `config.md`

项目配置文件。

主要可以配置：

- 小红书账号
- 账号主页地址
- 下载数量
- 是否重新扫描作品
- 是否显示浏览器
- 是否等待登录确认
- 视频保存目录
- 是否跳过已有视频
- 视频切割参数
- 输出目录

一般情况下，主要修改这个文件即可，不需要直接修改 Python 代码。

## 环境准备

需要安装：

- Python 3
- FFmpeg
- Git（如果通过 GitHub 拉取代码）

检查 Python：

```bash
python --version
```

检查 FFmpeg：

```bash
ffmpeg -version
```

## 下载项目

```bash
git clone https://github.com/peach-jhc/xiaohongshuPAqu.git
```

进入项目目录：

```bash
cd xiaohongshuPAqu
```

## 安装 Python 依赖

如果项目中有 `requirements.txt`：

```bash
pip install -r requirements.txt
```

## 使用方法

### 第一次运行

先修改：

```text
config.md
```

然后运行：

```bash
python download_xhs_videos.py
```

第一次运行时会打开浏览器，需要扫码登录小红书。

登录成功后，浏览器登录数据会保存到本地。

### 后续运行

以后直接执行：

```bash
python download_xhs_videos.py
```

一般不需要再次扫码。

如果登录状态失效，再重新扫码即可。

### 切割视频

视频下载完成后运行：

```bash
python cut_xhs_videos.py
```

程序会按照 `config.md` 中的配置处理视频。

## 注意

浏览器登录数据、下载的视频、切割后的视频建议只保存在本地，不要上传到 GitHub。
