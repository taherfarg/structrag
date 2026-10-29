FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TIKTOKEN_CACHE_DIR=/opt/tiktoken HOST=0.0.0.0 PORT=8000
COPY pyproject.toml ./
COPY app ./app
RUN pip install . && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" \
 && useradd --system --uid 10001 api
USER api
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "app"]
