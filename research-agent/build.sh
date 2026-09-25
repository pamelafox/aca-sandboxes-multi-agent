#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACR_NAME=$(azd env get-values | sed -n 's/^acrName="\(.*\)"/\1/p')
RG_NAME=$(azd env get-values | sed -n 's/^AZURE_RESOURCE_GROUP="\(.*\)"/\1/p')
if [[ -z "$ACR_NAME" ]]; then
    echo "ERROR: acrName not found in azd env. Did 'azd provision' succeed?" >&2
    exit 1
fi

echo "Building research-agent image into $ACR_NAME (rg=$RG_NAME)..."
if [[ -n "$RG_NAME" ]]; then
    az acr build --registry "$ACR_NAME" --resource-group "$RG_NAME" --image research-agent:latest "$SCRIPT_DIR"
else
    az acr build --registry "$ACR_NAME" --image research-agent:latest "$SCRIPT_DIR"
fi