#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
    printf '%s\n' \
        'Build and push the sandbox-agent image using Azure Container Registry.' \
        'Usage: bash sandbox-agent/build.sh' \
        'Environment overrides: SUBSCRIPTION_ID, RESOURCE_GROUP, ACR_NAME' \
        'Missing settings are read with azd env get-value.' \
        'Optional environment: IMAGE_TAG (default: latest)' \
        'Saves SANDBOX_AGENT_IMAGE when an azd environment is selected.' \
        'Requires Azure CLI authentication. Prints the image reference to stdout.'
    exit 0
fi
if [[ $# -ne 0 ]]; then
    echo 'Unexpected arguments. Use --help for usage.' >&2
    exit 2
fi

IMAGE_TAG="${IMAGE_TAG:-latest}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${SUBSCRIPTION_ID:-}" || -z "${RESOURCE_GROUP:-}" || -z "${ACR_NAME:-}" ]]; then
    if ! command -v azd >/dev/null; then
        echo 'Set SUBSCRIPTION_ID, RESOURCE_GROUP, and ACR_NAME, or install azd to read deployment settings.' >&2
        exit 1
    fi
    SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-$(azd env get-value AZURE_SUBSCRIPTION_ID)}"
    RESOURCE_GROUP="${RESOURCE_GROUP:-$(azd env get-value AZURE_RESOURCE_GROUP)}"
    ACR_NAME="${ACR_NAME:-$(azd env get-value acrName)}"
fi

: "${SUBSCRIPTION_ID:?Set SUBSCRIPTION_ID or run azd up first}"
: "${RESOURCE_GROUP:?Set RESOURCE_GROUP or run azd up first}"
: "${ACR_NAME:?Set ACR_NAME or run azd up first}"

ACR_ENDPOINT=$(az acr show \
    --subscription "$SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACR_NAME" \
    --query loginServer --output tsv)
if [[ -z "$ACR_ENDPOINT" ]]; then
    echo 'The registry did not return a login server.' >&2
    exit 1
fi

az acr build \
    --subscription "$SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --registry "$ACR_NAME" \
    --image "sandbox-agent:$IMAGE_TAG" \
    --platform linux/amd64 \
    "$SCRIPT_DIR" >&2

SANDBOX_AGENT_IMAGE="$ACR_ENDPOINT/sandbox-agent:$IMAGE_TAG"
if command -v azd >/dev/null && azd env get-value AZURE_ENV_NAME >/dev/null 2>&1; then
    azd env set SANDBOX_AGENT_IMAGE "$SANDBOX_AGENT_IMAGE" >&2
else
    echo 'No selected azd environment; use the printed image reference with --image.' >&2
fi

printf '%s\n' "$SANDBOX_AGENT_IMAGE"