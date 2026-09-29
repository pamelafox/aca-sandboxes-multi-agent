"""Azure credential selection for managed Azure hosting and isolated local CLI use."""

import os

from azure.core.credentials import TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from azure.identity.aio import (
    AzureCliCredential as AsyncAzureCliCredential,
    ManagedIdentityCredential as AsyncManagedIdentityCredential,
)


def build_sync_credential() -> TokenCredential:
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return AzureCliCredential(tenant_id=os.environ.get("AZURE_TENANT_ID"))


def build_async_credential() -> AsyncTokenCredential:
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if client_id:
        return AsyncManagedIdentityCredential(client_id=client_id)
    return AsyncAzureCliCredential(tenant_id=os.environ.get("AZURE_TENANT_ID"))
