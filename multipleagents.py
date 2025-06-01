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

def jira_creation(project_name, file_list, jira_flag=False):
    from pathlib import Path

    # === 1. Load agent metadata ===
    with open("persistent_agents_metadata.json") as f:
        agent_data = json.load(f)

    if "RS_Agent" not in agent_data:
        raise ValueError("RS_Agent not found in metadata.")

    # === 2. Setup RS_Agent info ===
    rs_agent_info = agent_data["RS_Agent"]
    agent_id = rs_agent_info["agent_id"]
    thread_id = rs_agent_info["thread_id"]

    # === 3. If jira_flag is True: skip upload, just send a message ===
    if jira_flag:
        user_prompt = (
            f'For project {project_name},please provide a comprehensive list of the all schedules or templates including specific templates in the FR Y-9C report. The output should have 5 columns - 1 - template code including report name,  2 - template name including report name, 3 - one line description of the template, 4 - JIRA short title with atleast 10 words including column 1 and the words "report automation tasks". I must want output to be in a JSON format, where keys are the first column described above, with remaining columns are values only display JSON output, nothing else.'
        )

        project_client.agents.create_message(thread_id=thread_id, role="user", content=user_prompt)
        run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

        wait_for_run_completion(project_client, thread_id, run["id"])
        response = get_last_assistant_response(project_client, thread_id)

        print(f"\n[RS_Agent Response - Jira Task]:\n{response}\n")
        return response

    # === 4. Otherwise, perform full upload & update ===
    existing_files = rs_agent_info.get("files", [])
    full_new_paths = [os.path.join(project_name, f) for f in file_list]
    all_files = list(set(existing_files + full_new_paths))  # remove duplicates

    file_ids = []
    for full_path in all_files:
        if not os.path.exists(full_path):
            print(f"[Warning] File not found: {full_path}")
            continue

        ext = Path(full_path).suffix.lower()
        supported_ext = [
            ".c", ".cpp", ".cs", ".css", ".doc", ".docx", ".go", ".html", ".java",
            ".js", ".json", ".md", ".pdf", ".php", ".pptx", ".py", ".rb", ".sh", ".tex", ".ts", ".txt"
        ]

        if ext in supported_ext:
            file_id = project_client.agents.upload_file_and_poll(
                file_path=full_path, purpose=FilePurpose.AGENTS
            ).id
            file_ids.append(file_id)
        else:
            print(f"[Skipped] Unsupported file type: {full_path}")

    if file_ids:
        vector_store = project_client.agents.create_vector_store_and_poll(
            file_ids=file_ids,
            name=f"RS_Agent_vectorstore_{int(time.time())}"
        )

        file_tool = FileSearchTool(vector_store_ids=[vector_store.id])

        project_client.agents.update_agent(
            agent_id=agent_id,
            tools=file_tool.definitions,
            tool_resources=file_tool.resources
        )

        agent_data["RS_Agent"]["vector_store_id"] = vector_store.id
        agent_data["RS_Agent"]["files"] = all_files
        agent_data["RS_Agent"].pop("vector_store_ids", None)

        with open("persistent_agents_metadata.json", "w") as f:
            json.dump(agent_data, f, indent=4)

        print(f"[Success] RS_Agent updated with new vector store and {len(file_ids)} total files.")
    else:
        print("[Info] No valid files uploaded. Vector store not updated.")

    user_prompt = (
        f'You are working on project {project_name}. The attached documents are instructions for regulatory reports. '
        f'Your scope is only limited to the documents I have attached or information I have provided. '
        f'This report is applicable for our organization. For now, review the documents. '
        f'I will come back with project-specific tasks when ready. Reply with OKAY only.'
    )

    project_client.agents.create_message(thread_id=thread_id, role="user", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[RS_Agent Response]:\n{response}\n")
    return response


jira_creation("FRY9C", ["FR_Y-9C20250327_i.pdf","FR_Y-9C20250327_f.pdf"])

jira_creation("FRY9C", ["FR_Y-9C20250327_i.pdf","FR_Y-9C20250327_f.pdf"], True)


def process_jira_task(jira_name, jira_id):
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
        f'for project "FRY9C" , Schedule associated with "{jira_name}" Before you proceed look in your memory for the entity structure and chart of account. You are helping business system analyst create a detailed business requirement document with functional specifications. Remember that the business system analyst has very limited understand of regulatory reporting requirements or transformations, hence help business system analyst with maximum information. Review the entity structure and identify which set of entities should be excluded or included based on the jurisdiction and structure, also review the reporting requirements of the project to identify the reporting scope. Similarly, use chart of accounts to propose what how the data can be filtered for this specific JIRA. Review all the line items which need to be reported, and provided detailed interpretation which is applicable to the institution. Propose actual transformation, filter and validation rules for the BSA to document. Also provide snippets of reporting instructions and reporting form as additional information for BA as they do not have that information, provide all your reponses in well structured JSON, you must respond in JSON format only.'
    )

    # === 3. Send message and get agent response ===
    project_client.agents.create_message(thread_id=thread_id, role="user", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[RS_Agent Response for {jira_id} - {jira_name}]:\n{response}\n")
    return response

process_jira_task('Schedule_HC_E','1')