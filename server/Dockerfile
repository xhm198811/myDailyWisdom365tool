# =============================================================================
# 每日问候小程序 · FastAPI 后端
#
# 微信云托管要求：容器必须监听 80 端口，且「服务版本配置」里的容器端口要填 80，
# 两者不一致会导致请求无法路由到容器内应用（表现为部署成功但访问 404/超时）。
#
# 本地验证（装了 Docker 的话）：
#   docker build -t daily-greeting .
#   docker run --rm -p 8123:80 --env-file .env daily-greeting
# =============================================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PORT=80

WORKDIR /app

# 依赖单独一层：日常改代码不会触发重新安装依赖，构建更快
# 走腾讯云内网 PyPI 镜像，云托管构建机上比官方源快很多
COPY requirements.txt .
RUN pip install --no-cache-dir \
        -i https://mirrors.cloud.tencent.com/pypi/simple \
        --trusted-host mirrors.cloud.tencent.com \
        -r requirements.txt

# 只拷应用代码。.env 不进镜像，配置一律走云托管控制台的环境变量
COPY app ./app

EXPOSE 80

# 单 worker 即可：业务全异步，且天气的内存缓存依赖进程内共享（多 worker 会各存一份）
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-80} --workers 1"]
