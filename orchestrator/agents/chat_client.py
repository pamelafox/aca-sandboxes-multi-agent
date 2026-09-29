"""
Shared Azure OpenAI chat client factory for MAF agents in the orchestrator.
"""
import os

from agent_framework.openai import OpenAIChatClient

from azure_credentials import build_async_credential


def build_chat_client() -> OpenAIChatClient:
    """
    Returns an OpenAIChatClient configured for Azure OpenAI from environment
    variables. Auth is keyless: uses managed identity in Azure and the selected
    Azure CLI tenant locally to mint Cognitive Services bearer tokens.
    The orchestrator's principal needs 'Cognitive Services OpenAI User' on
    the AOAI account (granted by infra/main.bicep).
    """
    endpoint   = os.environ["AZURE_OPENAI_ENDPOINT"]
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    return OpenAIChatClient(
        model=deployment,
        azure_endpoint=endpoint,
        credential=build_async_credential(),
    )