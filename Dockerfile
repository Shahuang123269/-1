FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml ./
COPY issue_agent ./issue_agent
RUN pip install setuptools==84.0.0 wheel==0.48.0 && pip install --no-deps --no-build-isolation . && useradd --create-home agent && mkdir -p /app/data && chown agent:agent /app/data
USER agent
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "issue_agent.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
