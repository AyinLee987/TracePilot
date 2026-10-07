FROM python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir numpy==2.1.3 pandas==2.2.3 scipy==1.14.1 scikit-learn==1.5.2 xgboost==2.1.4 lightgbm==4.6.0 statsmodels==0.14.4 bayesian-optimization==2.0.3 timm==1.0.15 torch-geometric==2.6.1
ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONUNBUFFERED=1
WORKDIR /work
