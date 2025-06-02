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
    existing_files = rs_agent_info.get("files", [])

    # === 3. Combine all files: previously known + new ===
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

    # === 4. Create new vector store ===
    if file_ids:
        vector_store = project_client.agents.create_vector_store_and_poll(
            file_ids=file_ids,
            name=f"RS_Agent_vectorstore_{int(time.time())}"
        )

        file_tool = FileSearchTool(vector_store_ids=[vector_store.id])

        # === 5. Update agent's tools ===
        project_client.agents.update_agent(
            agent_id=agent_id,
            tools=file_tool.definitions,
            tool_resources=file_tool.resources
        )

        # === 6. Update metadata ===
        agent_data["RS_Agent"]["vector_store_id"] = vector_store.id
        agent_data["RS_Agent"]["files"] = all_files
        agent_data["RS_Agent"].pop("vector_store_ids", None)  # remove old field if present

        with open("persistent_agents_metadata.json", "w") as f:
            json.dump(agent_data, f, indent=4)

        print(f"[Success] RS_Agent updated with new vector store and {len(file_ids)} total files.")
    else:
        print("[Info] No valid files uploaded. Vector store not updated.")

    # === 7. Prompt RS_Agent ===
    user_prompt = (
        f'You are working on project {project_name}. The attached documents are instructions for regulatory reports. '
        f'Your scope is only limited to the documents I have attached or information I have provided. '
        f'This report is applicable for our organization. For now, review the documents. '
        f'I will come back with project-specific tasks when ready. Reply with OKAY only.'
    )

    project_client.agents.create_message(thread_id=thread_id, role="assistant", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[RS_Agent Response]:\n{response}\n")
    return response

jira_creation("FRY9C", ["FR_Y-9C20250327_i.pdf","FR_Y-9C20250327_f.pdf"])


def jira_status_create(project_name):
    with open("persistent_agents_metadata.json") as f:
        agent_data = json.load(f)

    if "RS_Agent" not in agent_data:
        raise ValueError("RS_Agent not found in metadata.")

    rs_agent_info = agent_data["RS_Agent"]
    agent_id = rs_agent_info["agent_id"]
    thread_id = rs_agent_info["thread_id"]
    user_prompt = (
        f'For project {project_name},please provide a comprehensive list of the all schedules or templates including specific templates in the {project_name} report. The output should have 5 columns - 1 - template code including report name,  2 - template name including report name, 3 - one line description of the template, 4 - JIRA short title with atleast 10 words including column 1 and the words "report automation tasks". I must want output to be in a JSON format, where keys are the first column described above, with remaining columns are values only display JSON output, nothing else.'
    )

    project_client.agents.create_message(thread_id=thread_id, role="assistant", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[RS_Agent Response - Jira Task]:\n{response}\n")
    return response

jira_status_create("FRY9C")


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
        f'For project "FRY9C" , Schedule associated with "{jira_name}". Before you proceed look in your memory for the entity structure and chart of account. You are helping business system analyst create a detailed business requirement document with functional specifications. Remember that the business system analyst has very limited understand of regulatory reporting requirements or transformations, hence help business system analyst with maximum information. Review the entity structure and identify which set of entities should be excluded or included based on the jurisdiction and structure, also review the reporting requirements of the project to identify the reporting scope. Similarly, use chart of accounts to propose what how the data can be filtered for this specific JIRA. Review all the line items which need to be reported, and provided detailed interpretation which is applicable to the institution. Propose actual transformation, filter and validation rules for the BSA to document. Also provide snippets of reporting instructions and reporting form as additional information for BA as they do not have that information, provide all your reponses in well structured JSON, you must respond in JSON format only. Give me atleast 4000 to 5000 words.'
    )

    # === 3. Send message and get agent response ===
    project_client.agents.create_message(thread_id=thread_id, role="assistant", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[RS_Agent Response for {jira_id} - {jira_name}]:\n{response}\n")
    return response

HC_E_Task = process_jira_task('Schedule_HC_E','1')
#
#
# BA_Prompt = 'I am going to ask you to create business requirement document, remember that the document should be created in word format. Recollect your knowledge about chart of accounts and entity structure. Again, remember your role of regulatory reporting business analyst. attached JSON has the detail about the automation tasks for which document has to be created. you can ask 10 questions to regulatory reporting SME before you create the BRD that would help you provide more clarity on the documentation. you must structure your 10 questions in JSON format, and only display JSON'


def RS_Agent_calling_BA_Agent_call1(HC_E_Task):

    with open("persistent_agents_metadata.json") as f:
        agent_data = json.load(f)

    if "BA_Agent" not in agent_data:
        raise ValueError("BA_Agent not found in metadata.")

    rs_agent_info = agent_data["BA_Agent"]
    agent_id = rs_agent_info["agent_id"]
    thread_id = rs_agent_info["thread_id"]

    # === 2. Construct custom prompt using JIRA inputs ===
    user_prompt = (
        'I am going to ask you to create business requirement document, remember that the document should be created in word format. Recollect your knowledge about chart of accounts and entity structure. Again, remember your role of regulatory reporting business analyst. attached JSON has the detail about the automation tasks for which document has to be created. you can ask 10 questions to regulatory reporting SME before you create the BRD that would help you provide more clarity on the documentation. you must structure your 10 questions in JSON format, and only display JSON' +  HC_E_Task
    )

    # === 3. Send message and get agent response ===
    project_client.agents.create_message(thread_id=thread_id, role="assistant", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[BA_Agent Response for ]:\n{response}\n")
    return response

BA_Agent_response = RS_Agent_calling_BA_Agent_call1(HC_E_Task)

def BA_Agent_calling_RS_Agent_call2(BA_Agent_response):
    with open("persistent_agents_metadata.json") as f:
        agent_data = json.load(f)

    if "BA_Agent" not in agent_data:
        raise ValueError("RS_Agent not found in metadata.")

    rs_agent_info = agent_data["RS_Agent"]
    agent_id = rs_agent_info["agent_id"]
    thread_id = rs_agent_info["thread_id"]

    # === 2. Construct custom prompt using JIRA inputs ===
    user_prompt = (
        'For the above summary, the business analyst has asked few questions, can you help in clarifying the questions to the business system analyst which would help the business analyst create the requirement document. the queries are in JSON format. When responding, please respond in JSON format only.' +  BA_Agent_response
    )

    # === 3. Send message and get agent response ===
    project_client.agents.create_message(thread_id=thread_id, role="assistant", content=user_prompt)
    run = project_client.agents.create_run(thread_id=thread_id, agent_id=agent_id)

    wait_for_run_completion(project_client, thread_id, run["id"])
    response = get_last_assistant_response(project_client, thread_id)

    print(f"\n[RS_Agent Response for ]:\n{response}\n")
    return response


BA_Agent_calling_RS_Agent_call2(BA_Agent_response)