# syntax=docker/dockerfile:1
# Container image for the Comments Lambda.
# Built and deployed by SAM (PackageType: Image) — see template.yaml.
FROM public.ecr.aws/lambda/python:3.13

# Bring in uv (the project's package manager) for reproducible, locked installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install runtime dependencies (no dev group) from the lockfile, straight into
# the Lambda task root. Copy only the manifests first so this layer is cached
# until pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && uv pip install --no-installer-metadata --target "${LAMBDA_TASK_ROOT}" -r requirements.txt

# Application code.
COPY src/comments "${LAMBDA_TASK_ROOT}/comments"

# Powertools entrypoint — <module>.<function>. The base image's runtime
# interpreter (RIC) resolves this from LAMBDA_TASK_ROOT.
CMD ["comments.app.lambda_handler"]
