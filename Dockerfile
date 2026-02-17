FROM python:3.12-slim

# ------------------------------------------------------------
# 基本設定（運用向け）
# ------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo

WORKDIR /app

# ------------------------------------------------------------
# 日本語フォント + タイムゾーン（JST）設定
#  - fonts-noto-cjk: matplotlib日本語表示
#  - tzdata: timezone を正しく反映
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    tzdata \
 && ln -sf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
 && echo "Asia/Tokyo" > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# 依存関係（キャッシュを効かせる）
# ------------------------------------------------------------
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ------------------------------------------------------------
# アプリ本体
# ------------------------------------------------------------
COPY . /app

# 出力先を確実に用意（念のため）
RUN mkdir -p /app/output

# ------------------------------------------------------------
# 実行（あなたの構成に合わせて）
# ------------------------------------------------------------
CMD ["python", "sourcecode/main.py"]
