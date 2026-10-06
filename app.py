import os
import re
import time
import uuid
import shutil
import threading
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, send_file

app = Flask(__name__, static_folder='static', static_url_path='')
WORK_DIR = Path(os.environ.get('WORK_DIR', '/tmp/ytmp3'))
WORK_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get('PORT', '8080'))
CLEANUP_AFTER = int(os.environ.get('CLEANUP_AFTER', '3600'))  # seconds

jobs = {}
jobs_lock = threading.Lock()

SUPPORTED_RE = re.compile(
    r'(?:youtu\.be/|youtube\.com/(?:embed/|live/|shorts/|watch\?[^#]*v=|v/))[a-zA-Z0-9_-]{11}'
    r'|instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+'
)

def is_supported_url(url):
    return bool(SUPPORTED_RE.search(url or ''))

def sanitize(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or 'video').strip()[:80] or 'video'

# 支持的编码白名单
AUDIO_CODECS = ('mp3', 'm4a', 'opus', 'wav', 'flac')
VIDEO_CODECS = ('mp4', 'webm', 'mkv')
BITRATES = ('128K', '192K', '256K', '320K')
RESOLUTIONS = ('2160', '1440', '1080', '720', '480', '360')

def build_cmd(mode, codec, bitrate, resolution, out_tpl, url):
    """根据模式/编码/码率/分辨率构建 yt-dlp 命令；返回 (cmd, is_converting)。"""
    if mode == 'audio':
        cmd = ['yt-dlp', '-x', '--audio-format', codec, '--audio-quality', bitrate,
               '--no-playlist', '--no-warnings', '-o', out_tpl, url]
        return cmd, True
    h = '[height<=%s]' % resolution
    if codec == 'webm':
        f = 'bv*%s[ext=webm]+ba/b%s[ext=webm]/b' % (h, h)
    elif codec == 'mkv':
        f = 'bv*%s+ba/b%s' % (h, h)
    else:
        f = 'bv*%s[ext=mp4]+ba[ext=m4a]/b%s[ext=mp4]/b' % (h, h)
    cmd = ['yt-dlp', '-f', f, '--merge-output-format', codec,
           '--no-playlist', '--no-warnings', '-o', out_tpl, url]
    return cmd, False

def run_convert(job_id, url, mode, codec, bitrate, resolution):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
    try:
        job['status'] = 'fetching'
        job['progress'] = 5

        job_dir = WORK_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # 1. 取标题
        r = subprocess.run(
            ['yt-dlp', '--print', '%(title)s', '--no-playlist', '--no-warnings', url],
            capture_output=True, text=True, timeout=60
        )
        title = sanitize(r.stdout.strip().splitlines()[0] if r.stdout.strip() else 'video')
        job['title'] = title

        # 2. 下载 + 转换
        job['status'] = 'downloading'
        job['progress'] = 15
        out_tpl = str(job_dir / 'output.%(ext)s')

        cmd, is_converting = build_cmd(mode, codec, bitrate, resolution, out_tpl, url)
        if is_converting:
            job['status'] = 'converting'
            job['progress'] = 60

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            err = (proc.stderr or '').strip().splitlines()
            raise RuntimeError(err[-1][:200] if err else 'yt-dlp failed')

        # 3. 找输出文件
        files = [f for f in job_dir.iterdir() if f.is_file()]
        if not files:
            raise RuntimeError('no output file produced')
        out_file = max(files, key=lambda f: f.stat().st_size)

        job['file'] = str(out_file)
        job['filename'] = f"{title}.{out_file.suffix.lstrip('.')}"
        job['status'] = 'done'
        job['progress'] = 100
        job['finished_at'] = time.time()
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)[:300]
        job['finished_at'] = time.time()

def cleanup_loop():
    while True:
        time.sleep(300)
        now = time.time()
        with jobs_lock:
            expired = [jid for jid, j in jobs.items()
                       if j.get('finished_at') and now - j['finished_at'] > CLEANUP_AFTER]
            for jid in expired:
                shutil.rmtree(WORK_DIR / jid, ignore_errors=True)
                jobs.pop(jid, None)

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/convert', methods=['POST'])
def api_convert():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get('url') or '').strip()
    mode = (data.get('mode') or '').lower()
    codec = (data.get('codec') or '').lower()
    bitrate = (data.get('bitrate') or '320K').upper()
    resolution = str(data.get('resolution') or '1080')
    if bitrate not in BITRATES:
        bitrate = '320K'
    if resolution not in RESOLUTIONS:
        resolution = '1080'
    if (mode == 'audio' and codec in AUDIO_CODECS) or \
       (mode == 'video' and codec in VIDEO_CODECS):
        pass
    else:
        # 兼容旧客户端：format=mp3/mp4
        fmt = (data.get('format') or 'mp3').lower()
        if fmt == 'mp4':
            mode, codec = 'video', 'mp4'
        elif fmt == 'mp3':
            mode, codec = 'audio', 'mp3'
        else:
            return jsonify({'error': '不支持的编码：%s（音频：%s；视频：%s）'
                            % (codec or fmt, '/'.join(AUDIO_CODECS), '/'.join(VIDEO_CODECS))}), 400
    if not is_supported_url(url):
        return jsonify({'error': '仅支持 YouTube / Instagram 链接'}), 400

    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {'status': 'pending', 'progress': 0, 'title': '',
                        'mode': mode, 'format': codec,
                        'bitrate': bitrate, 'resolution': resolution}
    threading.Thread(target=run_convert,
                     args=(job_id, url, mode, codec, bitrate, resolution),
                     daemon=True).start()
    return jsonify({'job_id': job_id})

@app.route('/api/status/<job_id>')
def api_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': '任务不存在或已清理'}), 404
    return jsonify({k: job.get(k, '') for k in ('status', 'progress', 'title', 'error', 'format')})

@app.route('/api/download/<job_id>')
def api_download(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or job.get('status') != 'done' or not job.get('file'):
        return jsonify({'error': '文件尚未就绪'}), 404
    return send_file(job['file'], as_attachment=True,
                     download_name=job.get('filename', 'download'))

@app.route('/api/health')
def api_health():
    return jsonify({'ok': True})

def _ytdlp_version():
    r = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True, timeout=15)
    return r.stdout.strip()

def _ytdlp_latest():
    r = subprocess.run(['python3', '-c',
        "import json, urllib.request;"
        "d = json.load(urllib.request.urlopen('https://pypi.org/pypi/yt-dlp/json', timeout=10));"
        "print(d['info']['version'])"],
        capture_output=True, text=True, timeout=20)
    return r.stdout.strip()

@app.route('/api/ytdlp/version')
def api_ytdlp_version():
    try:
        installed = _ytdlp_version()
    except Exception:
        return jsonify({'error': '获取版本失败'}), 500
    latest, update_available = None, False
    try:
        latest = _ytdlp_latest()
        # 归一化比对: "2026.08.19" 与 "2026.8.19" 视为相同
        norm = lambda v: '.'.join(str(int(x)) for x in v.split('.') if x.isdigit())
        update_available = bool(latest) and norm(installed) != norm(latest)
    except Exception:
        pass
    return jsonify({'installed': installed, 'latest': latest,
                    'updateAvailable': update_available})

@app.route('/api/ytdlp/update', methods=['POST'])
def api_ytdlp_update():
    try:
        old_v = _ytdlp_version()
        subprocess.run(['pip', 'install', '--upgrade', '--no-cache-dir', 'yt-dlp'],
                       capture_output=True, text=True, timeout=300, check=True)
        new_v = _ytdlp_version()
        norm = lambda v: '.'.join(str(int(x)) for x in v.split('.') if x.isdigit())
        return jsonify({'success': True, 'oldVersion': old_v,
                        'newVersion': new_v, 'updated': norm(old_v) != norm(new_v)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:300]}), 500

if __name__ == '__main__':
    threading.Thread(target=cleanup_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT, threaded=True)
