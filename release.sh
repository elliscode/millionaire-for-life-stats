#!/usr/bin/env bash
# Build the Lambda zip (Docker, linux/arm64) and push it to the function.
#
#   sh release.sh               build + deploy
#   BUILD_ONLY=1 sh release.sh  build the zip only (no AWS calls)
#
# After deploying code that changes templates/CSS/JS, republish the site:
#   aws lambda invoke --function-name m4l-tracker \
#     --cli-binary-format raw-in-base64-out --payload '{"force_publish": true}' /dev/stdout
set -euo pipefail
cd "$(dirname "$0")"

IMAGE=m4l-tracker
CONTAINER=${IMAGE}-instance
FUNCTION_NAME=m4l-tracker

TIMESTAMP=$(date +%s)
ZIP=dist/m4l-tracker-lambda-release-${TIMESTAMP}.zip

rm -rf dimg
mkdir -p dist

# --platform pinned to match the Lambda's configured arm64 architecture.
docker build --platform linux/arm64 -t "${IMAGE}" .

docker rm -f "${CONTAINER}" 2>/dev/null || true
docker create --name "${CONTAINER}" "${IMAGE}" >/dev/null
docker cp "${CONTAINER}:/opt/python" dimg
docker cp "${CONTAINER}:/var/task/m4l" dimg/m4l
docker rm -f "${CONTAINER}" >/dev/null

find dimg -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd dimg && zip -qr "../${ZIP}" .)
rm -rf dimg
echo "Built ${ZIP} ($(du -h "${ZIP}" | cut -f1))"

if [ "${BUILD_ONLY:-}" = "1" ]; then
  exit 0
fi

aws lambda update-function-code \
  --function-name "${FUNCTION_NAME}" \
  --zip-file "fileb://${ZIP}" \
  --no-cli-pager
