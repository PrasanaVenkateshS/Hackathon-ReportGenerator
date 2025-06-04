import os
import re
import asyncio
import sys
import io
import base64
from dotenv import load_dotenv

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

from agent_roles import (RS_Agent_Name, RS_Agent_Role, BA_Agent_Name, BA_Agent_Role,
                         TA_Agent_Name, TA_Agent_Role, PYDEV_Agent_Name, PYDEV_Agent_Role,
                         DBDEV_Agent_Name, DBDEV_Agent_Role, DBMDLR_Agent_Name, DBMDLR_Agent_Role,
                         planning_agent_Name, planning_agent_Role_jiralist, planning_agent_Role_chatai)


# Load environment variables
load_dotenv()

# Azure OpenAI config
API_KEY = os.getenv("api_key")
MODEL_NAME = os.getenv("model-name")
API_VERSION = os.getenv("api-version")
AZURE_ENDPOINT = os.getenv("azure_endpoint")

# Azure AI Search config
SEARCH_SERVICE_NAME = os.getenv("AZURE_SEARCH_SERVICE_NAME")
SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME")
SEARCH_ADMIN_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY")
SEARCH_ENDPOINT = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"
CONTEXT_SEARCH_FILTER_PATH = os.getenv("AZURE_BLOB_CHATAI_PATH").split(",")

# === Azure OpenAI Chat Client ===
az_model_client = AzureOpenAIChatCompletionClient(
    azure_deployment=MODEL_NAME,
    model=MODEL_NAME,
    api_version=API_VERSION,
    azure_endpoint=AZURE_ENDPOINT,
    api_key=API_KEY
)

# === Azure Search Client ===
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_ADMIN_KEY)
)


def fetch_search_context(query_text: str, file_path, max_results=3):
    # This tells Azure Search to look for folder_path string in the metadata_storage_path field
    filters = [f"search.ismatch('{path}', 'metadata_storage_path')" for path in file_path]
    filter_expression = " or ".join(filters)

    print("Filter Expression: - ",filter_expression)

    results = search_client.search(query_text, filter=filter_expression, top=max_results)
    content_blocks = []
    for result in results:
        content = result.get("content")
        encoded_path = result.get("metadata_storage_path")
        print("Encoded Path: - ", encoded_path)
        try:
            path = base64.b64decode(encoded_path).decode("utf-8")
        except Exception:
            path = encoded_path or "UNKNOWN"

        if content:
            content_blocks.append(f"[SOURCE: {path}]\n{content.strip()}")

    return "\n\n".join(content_blocks)


# === Define Agents ===
planning_agent = AssistantAgent(planning_agent_Name,
    description="Facilitate collaboration and ensure synchronized execution across all roles.",
    model_client=az_model_client,
    system_message=planning_agent_Role_chatai
)

RS_Agent = AssistantAgent(RS_Agent_Name,model_client=az_model_client,system_message=RS_Agent_Role)
BA_Agent = AssistantAgent(BA_Agent_Name,model_client=az_model_client,system_message=BA_Agent_Role)
TA_Agent = AssistantAgent(TA_Agent_Name,model_client=az_model_client,system_message=TA_Agent_Role)
# PYDEV_Agent = AssistantAgent(PYDEV_Agent_Name, model_client=az_model_client,system_message=PYDEV_Agent_Role)
# DBDEV_Agent = AssistantAgent(DBDEV_Agent_Name, model_client=az_model_client,system_message=DBDEV_Agent_Role)
# DBMDLR_Agent = AssistantAgent(DBMDLR_Agent_Name, model_client=az_model_client,system_message=DBMDLR_Agent_Role)


# === Group Chat Setup ===
text_mention_termination = TextMentionTermination("TERMINATE")
max_messages_termination = MaxMessageTermination(max_messages=10)
termination = text_mention_termination | max_messages_termination

team = SelectorGroupChat(
#    [planning_agent, RS_Agent, BA_Agent, TA_Agent, PYDEV_Agent, DBMDLR_Agent, DBDEV_Agent],
[planning_agent, RS_Agent, BA_Agent, TA_Agent],
    model_client=az_model_client,
    termination_condition=termination
)


async def run_agent_and_extract(user_prompt: str):
    topic = ''
    filter_filepaths = [base64.b64encode(item.encode('utf-8')).decode('utf-8') for item in CONTEXT_SEARCH_FILTER_PATH]

    context = fetch_search_context(topic, file_path=filter_filepaths)

    task_prompt = f"""
Use the following context from research data:

==== START CONTEXT ====
{context}
==== END CONTEXT ====
{user_prompt}
"""
    print(CONTEXT_SEARCH_FILTER_PATH)
    print(task_prompt)

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf

    try:
        await Console(team.run_stream(task=task_prompt))
    finally:
        sys.stdout = old_stdout

    full_output = buf.getvalue()

    pattern = re.compile(
        r"SUMMARY END, TASK OUTPUT START\s*(.*?)\s*TASK OUTPUT END, TERMINATE",
        re.DOTALL
    )
    m = pattern.search(full_output)
    if m:
        return m.group(1).strip()

    # Fallback: split‐based extraction if regex fails
    parts = full_output.split("SUMMARY END, TASK OUTPUT START", 1)
    if len(parts) > 1:
        return parts[1].split("TASK OUTPUT END, TERMINATE", 1)[0].strip()

    # If markers weren’t found, return entire buffer so you can debug
    return full_output.strip()


# === Main Function ===
async def main():
    user_prompt = """
quick summary of information in 100 words
"""
    result = await run_agent_and_extract(user_prompt)
    print("=== TASK OUTPUT ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())