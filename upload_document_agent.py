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


import os
import json
from typing import List
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, FilePurpose


def upload_files_to_rs_agent(project_name: str, file_paths: List[str]):
    """
    Recreates RS_Agent's vector store with existing + new files.

    Args:
        project_name (str): Name to tag the new vector store.
        file_paths (List[str]): New files to add to the vector store.
    """
    # Load agent metadata
    audit_file = "persistent_agents_metadata.json"
    if not os.path.exists(audit_file):
        raise FileNotFoundError("persistent_agents_metadata.json not found.")

    with open(audit_file, "r") as f:
        agent_data = json.load(f)

    if "RS_Agent" not in agent_data:
        raise ValueError("RS_Agent not found in metadata.")

    rs_agent = agent_data["RS_Agent"]
    previous_files = rs_agent.get("files", [])
    combined_files = sorted(set(previous_files + file_paths))  # no duplicates

    # Connect to project
    client = AIProjectClient.from_connection_string(
        credential=DefaultAzureCredential(),
        conn_str=os.getenv("PROJECT_CONNECTION_STRING")
    )

    file_ids = []
    with client:
        for path in combined_files:
            ext = os.path.splitext(path)[1].lower()
            if ext in [
                ".txt", ".pdf", ".json", ".docx", ".doc", ".xlsx", ".csv", ".md",
                ".py", ".js", ".java", ".html", ".xml", ".pptx", ".c", ".cpp", ".cs"
            ]:
                file_obj = client.agents.upload_file_and_poll(file_path=path, purpose=FilePurpose.AGENTS)
                file_ids.append(file_obj.id)
                print(f"[Uploaded] {path}")
            else:
                print(f"[Skipped] {path} is not supported.")

        # Create new vector store
        vector_store = client.agents.create_vector_store_and_poll(
            file_ids=file_ids,
            name=f"RS_Agent_VectorStore_{project_name}"
        )

        # Prepare file search tool
        file_tool = FileSearchTool(vector_store_ids=[vector_store.id])

        # Update agent
        client.agents.update_agent(
            agent_id=rs_agent["agent_id"],
            tools=file_tool.definitions,
            tool_resources=file_tool.resources
        )

        # Update metadata
        rs_agent["vector_store_id"] = vector_store.id
        rs_agent["files"] = combined_files

        with open(audit_file, "w") as f:
            json.dump(agent_data, f, indent=4)

        print(f"[Success] RS_Agent vector store updated with project: {project_name}")


upload_files_to_existing_vectorstore('FRY9C',["FR_Y-9C20250327_f.pdf", "FR_Y-9C20250327_i.pdf"])