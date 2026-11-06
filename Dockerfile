FROM public.ecr.aws/lambda/python:3.14

# Install runtime dependencies into /opt/python (extracted by release.sh)
COPY pyproject.toml .
RUN pip install . -t /opt/python && rm -rf /opt/python/m4l*

# Copy code (package incl. templates/ and static/) into the runtime directory
COPY src/m4l ${LAMBDA_TASK_ROOT}/m4l

CMD ["m4l.handler.lambda_handler"]
