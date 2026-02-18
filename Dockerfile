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
# HF Spaces はデフォルトで 7860 を公開（READMEの app_port と揃える）
EXPOSE 7860

# Streamlit を 0.0.0.0:7860 で起動
# ※HF Spaces は iframe/cookie制限があるので、必要なら XSRF をOFF（後述）
CMD ["sh", "-c", "streamlit run Home.py --server.address=0.0.0.0 --server.port=7860 --server.headless=true --server.enableXsrfProtection=false"]
