import os
import json
import time
import pandas as pd
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, FilePurpose
from pathlib import Path

# === 1. Setup ===
load_dotenv()

project_client = AIProjectClient.from_connection_string(
    credential=DefaultAzureCredential(),
    conn_str=os.getenv("PROJECT_CONNECTION_STRING")
)

def wait_for_run_completion(client, thread_id, run_id):
    while True:
        status = client.agents.get_run(thread_id=thread_id, run_id=run_id)
        if status["status"] in ("completed", "failed", "cancelled"):
            return
        time.sleep(1)

def get_last_assistant_response(client, thread_id):
    messages = client.agents.list_messages(thread_id=thread_id)
    sorted_msgs = sorted(messages["data"], key=lambda x: x["created_at"])
    for msg in reversed(sorted_msgs):
        if msg["role"] == "assistant":
            blocks = msg.get("content", [])
            if blocks and blocks[0]["type"] == "text":
                return blocks[0]["text"]["value"]
    return "[No response found]"

def process_jira_task(project_name ,jira_name, jira_id):
    # === 1. Load RS_Agent metadata ===
    with open("persistent_agents_metadata.json") as f:
        agent_data = json.load(f)

    if "RS_Agent" not in agent_data:
        raise ValueError("RS_Agent not found in metadata.")

    rs_agent_info = agent_data["RS_Agent"]
    agent_id = rs_agent_info["agent_id"]
    thread_id = rs_agent_info["thread_id"]

    # === 2. Construct custom prompt using JIRA inputs ===
    user_prompt = (
        f'for project "FRY9C" , Schedule associated with "{project_name}"-"{jira_name}" Before you proceed look in your memory for the entity structure and chart of account. You are helping business system analyst create a detailed business requirement document with functional specifications. Remember that the business system analyst has very limited understand of regulatory reporting requirements or transformations, hence help business system analyst with maximum information. Review the entity structure and identify which set of entities should be excluded or included based on the jurisdiction and structure, also review the reporting requirements of the project to identify the reporting scope. Similarly, use chart of accounts to propose what how the data can be filtered for this specific JIRA. Review all possible the line items which need to be reported incllude MDRM number in your responses als review instructions, and provided detailed interpretation which is applicable to the institution. Propose actual transformation, filter and validation rules for the BSA to document. Also provide snippets of reporting instructions and reporting form as additional information for BA as they do not have that information, provide all your reponses in well structured JSON, you must respond in JSON format only.'
    )

    # === 3. Send message and get agent response ===
    project_client.agents.create_message(thread_id=thread_id, role="assistant", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[RS_Agent Response for {jira_id} - {jira_name}]:\n{response}\n")
    return response

process_jira_task('FRY9C','Schedule_HC_E','1')