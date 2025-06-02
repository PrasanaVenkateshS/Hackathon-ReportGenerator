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

# === Helper: Convert .xlsx to .json files ===
def convert_xlsx_to_json(agent_name, file_path, output_dir="converted_files"):
    os.makedirs(output_dir, exist_ok=True)
    xl = pd.ExcelFile(file_path)
    converted_files = []
    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name)
        json_file = os.path.join(output_dir, f"{agent_name}_{sheet_name}.json")
        df.to_json(json_file, orient="records", indent=2)
        converted_files.append(json_file)
    return converted_files

# === 2. File List (including xlsx which will be converted) ===
AGENT_DOCUMENT_FILES = {
    "RS_Agent": ["sample_data_rs.xlsx"],
    "BA_Agent": ["sample_data_ba.xlsx"],
    "TA_Agent": ["FR_Y-9C20250327_i.txt"],
    "Test_Agent": ["FR_Y-9C20250327_f.pdf", "FR_Y-9C20250327_i.txt"],
    "Developer_Agent": ["FR_Y-9C20250327_f.pdf"]
}

# === 3. Agent Definitions ===
AGENT_DETAILS = {
    "RS_Agent": "You are a senior regulatory reporting interpreting subject matter expect at a global financial institution dealing with complex loans, credit arrangements, derivatives, bonds, repos, securities, etc. ",
    "BA_Agent": "You are a senior business analyst at a global financial institution dealing with complex loans, credit arrangements, derivatives, bonds, repos, securities, etc. Your role is to support implementation of external regulatory reporting projects at the institution. ",
    "TA_Agent": "Technical Analyst Agent",
    "Test_Agent": "Test Case Analyst (Test Case Writter) Agent",
    "Developer_Agent": "Developer Agent"
}

# === 4. Load existing agent metadata if exists ===
audit_file = "persistent_agents_metadata.json"
if os.path.exists(audit_file):
    with open(audit_file) as f:
        created_agents = json.load(f)
else:
    created_agents = {}

with project_client:
    for agent_name, files in AGENT_DOCUMENT_FILES.items():
        regenerate_vector_store = False
        all_files = []

        # Convert .xlsx files and collect all valid files
        for file_path in files:
            if file_path.lower().endswith(".xlsx"):
                converted = convert_xlsx_to_json(agent_name, file_path)
                all_files.extend(converted)
            else:
                all_files.append(file_path)

        if agent_name in created_agents:
            existing_files = set(created_agents[agent_name].get("files", []))
            current_files = set(all_files)
            if current_files != existing_files:
                print(f"[Updating vector store] New or changed files detected for {agent_name}.")
                regenerate_vector_store = True
            else:
                print(f"[Skipping creation] Agent {agent_name} already exists with ID: {created_agents[agent_name]['agent_id']}")
                continue

        print(f"\n[Creating or Updating vector store and agent for {agent_name}]")

        # Upload supported files only
        file_ids = []
        for f in all_files:
            ext = os.path.splitext(f)[1].lower()
            if ext in [
                ".c", ".cpp", ".cs", ".css", ".doc", ".docx", ".go", ".html", ".java",
                ".js", ".json", ".md", ".pdf", ".php", ".pptx", ".py", ".rb", ".sh", ".tex", ".ts", ".txt"
            ]:
                file_ids.append(project_client.agents.upload_file_and_poll(file_path=f, purpose=FilePurpose.AGENTS).id)
            else:
                print(f"[Skipped] {f} is not a supported file type for retrieval.")

        vector_store = project_client.agents.create_vector_store_and_poll(
            file_ids=file_ids,
            name=f"{agent_name}_vectorstore"
        ) if file_ids else None

        file_tool = FileSearchTool(vector_store_ids=[vector_store.id]) if vector_store else None

        if agent_name not in created_agents:
            agent = project_client.agents.create_agent(
                name=agent_name,
                model="gpt-4o",
                instructions=AGENT_DETAILS[agent_name],
                tools=file_tool.definitions if file_tool else [],
                tool_resources=file_tool.resources if file_tool else {}
            )
            thread = project_client.agents.create_thread()
        else:
            agent_id = created_agents[agent_name]["agent_id"]
            thread_id = created_agents[agent_name]["thread_id"]
            agent = project_client.agents.update_agent(
                agent_id=agent_id,
                tools=file_tool.definitions if file_tool else [],
                tool_resources=file_tool.resources if file_tool else {}
            )
            thread = project_client.agents.get_thread(thread_id=thread_id)

        created_agents[agent_name] = {
            "agent_id": agent.id,
            "vector_store_id": vector_store.id if vector_store else None,
            "thread_id": thread.id,
            "files": all_files,
            "note": "persistent, do-not-delete"
        }

        print(f"[Agent {agent_name} ready with thread ID: {thread.id}]")

    with open(audit_file, "w") as f:
        json.dump(created_agents, f, indent=4)

    print("\n[Agent setup complete. Metadata saved to persistent_agents_metadata.json]")

#======================================================================================================================================================================
# === 1. Load Metadata and Setup ===
with open("persistent_agents_metadata.json") as f:
    agent_data = json.load(f)

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

# === 2. Interactive Training ===
training_prompts = {
    'RS_Agent':['You are a senior regulatory reporting interpretting subject matter expect at a global financial institution dealing with complex loans, credit arrangements, derivatives, bonds, repos, securities, etc. sample_data_rs.xlsx has 6 sheets. "EntityStructure Metadata" sheet has metadata for "EntityStructure" sheet, which defines the entity structure of institution. "chartofaccounts Metadata" has metadata for "chartofaccounts" sheet, which defines the chart of accounts of institution, the insitution follows same chart of accounts is based on IFRS for all entities. "Additionalinfo Metadata" has metadata for "Additionalinfo" sheet, which have additional information about the questions you might have to do your role better. this should be considered as information at hand to do your role better. Your job is to interpret the reporting requirements defined by the regulator and answer questions asked by subject matter experts in other departments like business system analyst, reporting team, technology team. Crucial point to note in all your future responses and questions from other subject matter experts, that you should to also mention references where possible, and simplify your responses. I will provide you the regulatory report which you would be helping with at a later point. For now, review the excel thoroughly - you are not allowed to ask any questions at this point. I will come back with tasks or actions during project initiation.'],
    "BA_Agent": ['You are a senior business analyst at a global financial institution dealing with complex loans, credit arrangements, derivatives, bonds, repos, securities, etc. Your role is to support implementation of external regulatory reporting projects at the institution. Your job is to interface between regulatory subject matter expert and technical team to define business requirements document. sample_data_rs.xlsx has 6 sheets. "EntityStructure Metadata" sheet has metadata for "EntityStructure" sheet, which defines the entity structure of institution. "chartofaccounts Metadata" has metadata for "chartofaccounts" sheet, which defines the chart of accounts of institution, the insitution follows same chart of accounts is based on IFRS for all entities. "Additionalinfo Metadata" has metadata for "Additionalinfo" sheet, which have additional information about the questions you might have to do your role better. this should be considered as information at hand to do your role better. Crucial point to note is that you are not supposed to interpret the regulatory requirements, that is the role for regulatory reporting SME. In your capacity and in all your future responses and questions from other subject matter experts, that you should focus on supporting the role of interfacing between business and technology team. I will provide you the regulatory report project which you would be helping with at a later point. For now, review the excel thoroughly multiple times, you are not allowed to ask any questions at this point. I will come back with tasks or actions during project initiation.'],
    "TA_Agent": ["FR_Y-9C20250327_i.txt"],
    "Test_Agent": ["FR_Y-9C20250327_f.pdf", "FR_Y-9C20250327_i.txt"],
    "Developer_Agent": ["FR_Y-9C20250327_f.pdf"]
}

for agent, roles_duties in training_prompts.items():
    selected_agent = agent
    if selected_agent == "exit":
        break

    if selected_agent not in agent_data:
        print("Agent not found. Please try again.")
        continue

    agent_id = agent_data[selected_agent]["agent_id"]
    thread_id = agent_data[selected_agent]["thread_id"]

    prompt = roles_duties[0] if isinstance(roles_duties, list) else roles_duties

    # Send message and run
    project_client.agents.create_message(thread_id=thread_id, role="user", content=prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)
    wait_for_run_completion(project_client, thread_id, run["id"])

    response = get_last_assistant_response(project_client, thread_id)
    print(f"\n[{selected_agent} Response]:\n{response}\n")

########################################################################################################################################################################################################################
#Actual Agent Process Begins Steps in the Excels No - 2
########################################################################################################################################################################################################################
#
# import os
# import json
# from azure.identity import DefaultAzureCredential
# from azure.ai.projects import AIProjectClient
# from azure.ai.projects.models import FilePurpose
# from typing import List
#
# def upload_files_to_existing_vectorstore(roject_name, file_paths):
#     # Load metadata to find RS_Agent vector store
#     audit_file = "persistent_agents_metadata.json"
#     if not os.path.exists(audit_file):
#         raise FileNotFoundError("Agent metadata file not found.")
#
#     with open(audit_file) as f:
#         agent_data = json.load(f)
#
#     if "RS_Agent" not in agent_data:
#         raise ValueError("RS_Agent not found in metadata.")
#
#     rs_agent_meta = agent_data["RS_Agent"]
#     vector_store_id = rs_agent_meta.get("vector_store_id")
#
#     if not vector_store_id:
#         raise ValueError("RS_Agent does not have a vector store ID.")
#
#     # Create project client
#     project_client = AIProjectClient.from_connection_string(
#         credential=DefaultAzureCredential(),
#         conn_str=os.getenv("PROJECT_CONNECTION_STRING")
#     )
#
#     # Upload supported files
#     file_ids = []
#     with project_client:
#         for path in c:
#             ext = os.path.splitext(path)[1].lower()
#             if ext in [
#                 ".c", ".cpp", ".cs", ".css", ".doc", ".docx", ".go", ".html", ".java",
#                 ".js", ".json", ".md", ".pdf", ".php", ".pptx", ".py", ".rb", ".sh", ".tex", ".ts", ".txt"
#             ]:
#                 file_obj = project_client.agents.upload_file_and_poll(file_path=path, purpose=FilePurpose.AGENTS)
#                 file_ids.append(file_obj.id)
#                 print(f"[Uploaded] {path}")
#             else:
#                 print(f"[Skipped] {path} is not a supported file type.")
#
#         if not file_ids:
#             print("[No valid files uploaded.]")
#             return
#
#         # Add to existing vector store
#         project_client.agents.add_files_to_vector_store_and_poll(
#             vector_store_id=vector_store_id,
#             file_ids=file_ids
#         )
#
#         print(f"[{project_name}] Files successfully added to RS_Agent vector store.")
#
#
# upload_files_to_existing_vectorstore('FRY9C',["FR_Y-9C20250327_f.pdf", "FR_Y-9C20250327_i.pdf"])
# Example usage (after defining):
# upload_files_to_existing_vectorstore(["new_file1.txt", "new_file2.pdf"], "Q2_Enhancement")
