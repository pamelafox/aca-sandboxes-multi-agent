"""Run an autonomous harness agent inside an ACA sandbox image."""

import asyncio
import os
import sys

from agent_framework import Agent, create_harness_agent
from agent_framework.openai import OpenAIChatClient
from agent_framework.tools import LocalShellTool, ShellEnvironmentProviderOptions
from openai import AsyncOpenAI


OUTPUT_MOUNT = "/workspace/out"
OUTPUT_VOLUME_INSTRUCTIONS = (
    f" {OUTPUT_MOUNT} is a persistent volume; everything else is lost when this sandbox is deleted. "
    f"Always save the final version of every deliverable in {OUTPUT_MOUNT}, "
    "overwriting any earlier copy, and keep drafts and scratch files in /workspace."
    if os.path.ismount(OUTPUT_MOUNT) else ""
)


def build_agent(shell: LocalShellTool, client: OpenAIChatClient) -> Agent:
    return create_harness_agent(
        client=client,
        name="sandbox-agent",
        agent_instructions=(
            "Complete the user's task autonomously using the shell in this ACA Linux sandbox. "
            "Use Bash to inspect, create, and edit files and run installed programs. "
            "Work in /workspace and report the paths of files you create. "
            "Execute and verify your work; do not merely describe a plan. "
            "Check exit codes and output before claiming success. "
            "An egress policy outside this sandbox controls network access: you may attempt any "
            "request, and blocked ones fail with HTTP 403. Report those results; "
            "do not launch background processes or try to work around the policy."
            + OUTPUT_VOLUME_INSTRUCTIONS
        ),
        shell_executor=shell,
        shell_environment_provider_options=ShellEnvironmentProviderOptions(
            probe_tools=("git", "python"),
        ),
        disable_file_memory=True,
        disable_web_search=True,
        disable_mode=True,
        disable_tool_auto_approval=True,
    )


# The sandbox holds no model credential. The egress proxy replaces this placeholder
# with an Entra token for the sandbox group's managed identity on the way out.
PROXY_INJECTED_AUTH = "injected-by-egress-proxy"


async def run_agent(prompt: str, *, endpoint: str, deployment: str) -> str:
    async with AsyncOpenAI(
        base_url=endpoint.rstrip("/") + "/openai/v1/",
        api_key=PROXY_INJECTED_AUTH,
    ) as openai_client:
        client = OpenAIChatClient(model=deployment, async_client=openai_client)
        async with LocalShellTool(
            shell="/bin/bash",
            workdir="/workspace",
            mode="persistent",
            approval_mode="never_require",
            acknowledge_unsafe=True,
            clean_env=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/workspace"},
            timeout=30,
            max_output_bytes=65_536,
        ) as shell:
            async with build_agent(shell, client) as agent:
                response = await asyncio.wait_for(
                    agent.run(prompt, session=agent.create_session()),
                    timeout=300,
                )
                if response.user_input_requests:
                    raise RuntimeError("Autonomous agent unexpectedly requested user input.")
                print(response.text, flush=True)
                return response.text


def main() -> None:
    if sys.platform != "linux" or os.environ.get("SANDBOX_AGENT_RUNTIME") != "aca":
        raise RuntimeError("Run this module in the sandbox-agent image, not on your host.")
    asyncio.run(run_agent(
        os.environ["AGENT_PROMPT"],
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    ))


if __name__ == "__main__":
    main()