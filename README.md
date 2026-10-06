# ytmp3 (self-hosted)

YouTube / Instagram 转音频 / 视频的私有转换服务，Docker 一键部署。
支持选项：音频固定 MP3 + 码率可选（128K~320K）、
视频固定 MP4 + 分辨率可选（360p~2160p）。
页面支持中英双语切换（右上角），首次打开跟随浏览器语言自动选择。

## 构建（多平台）

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t weleone/ytmp3:1.3.0 -t weleone/ytmp3:latest --push .
```

## 运行

```bash
docker compose up -d
# 浏览器打开 http://<host>:8090
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| PORT | 8080 | 监听端口 |
| WORK_DIR | /tmp/ytmp3 | 转换工作目录 |
| CLEANUP_AFTER | 3600 | 完成文件保留秒数，超时自动清理 |

## API

- `POST /api/convert` `{"url":"...","mode":"audio|video","codec":"mp3|m4a|opus|wav|flac|mp4|webm|mkv","bitrate":"128K|192K|256K|320K","resolution":"360|480|720|1080|1440|2160"}` → `{"job_id":"..."}`
  （url 支持 YouTube 和 Instagram 帖子/reel 链接；
  bitrate 仅音频有效，resolution 仅视频有效，缺省为 320K / 1080；
  兼容旧客户端：`{"url":"...","format":"mp3|mp4"}` 仍可用）
- `GET /api/status/<job_id>` → `{"status","progress","title","error"}`
- `GET /api/download/<job_id>` → 文件下载
- `GET /api/health` → `{"ok":true}`
- `GET /api/ytdlp/version` → `{"installed","latest","updateAvailable"}`
- `POST /api/ytdlp/update` → `{"success","oldVersion","newVersion","updated"}`

## 说明

- 音频用 yt-dlp 提取最佳音频转目标编码（mp3 为 320k）；视频合并最佳画质+音频后封装为目标容器
- 仅供个人学习使用
