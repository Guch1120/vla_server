# 既存CUDAランタイムを隔離して利用する。ホストへの依存追加は行わない。
FROM vlm-finetune:dev
COPY docker/pi05/requirements-tested.txt /opt/vla-pi05-requirements-tested.txt
# 基底イメージの依存は削除せず、必要な版だけ仮想環境に上書きする。
RUN python -m venv --system-site-packages /opt/pi05
ENV PATH=/opt/pi05/bin:$PATH
RUN python -m pip install --no-cache-dir -c /opt/vla-pi05-requirements-tested.txt "lerobot[pi,dataset] @ https://github.com/huggingface/lerobot/archive/8975047fbb76e7fef3f482988ceccc17e2102a90.zip#sha256=5c8074ecb36cb833343d8a8677441b85532890a3515da560e8ea3562c523643c"
WORKDIR /workspace
ENV HF_HOME=/cache/huggingface
CMD ["python", "scripts/pi05_base_smoke.py", "--help"]
