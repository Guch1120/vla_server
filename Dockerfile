FROM python:3.10-slim
WORKDIR /workspace
COPY pyproject.toml requirements-tested.txt ./
COPY server ./server
RUN pip install --no-cache-dir -c requirements-tested.txt -e '.[dev,bridge]'
COPY . .
CMD ["python", "-m", "pytest", "-q"]
