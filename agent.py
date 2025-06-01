import os
import time
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, FilePurpose

# === 1. Setup ===
load_dotenv()

project_client = AIProjectClient.from_connection_string(
    credential=DefaultAzureCredential(),
    conn_str=os.getenv("PROJECT_CONNECTION_STRING")
)

DOCUMENT_FILES = [
    "FR_Y-9C20250327_f.pdf",
    "FR_Y-9C20250327_i.txt"
]

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

with project_client:
    # === 2. Upload Files ===
    file_ids = [
        project_client.agents.upload_file_and_poll(file_path=f, purpose=FilePurpose.AGENTS).id
        for f in DOCUMENT_FILES
    ]

    # === 3. Vector Store and Tools ===
    vector_store = project_client.agents.create_vector_store_and_poll(
        file_ids=file_ids,
        name="dual_agent_vectorstore"
    )
    file_tool = FileSearchTool(vector_store_ids=[vector_store.id])

    # === 4. Agent 1: Regulatory Report Expert ===
    agent1 = project_client.agents.create_agent(
        name="agent1-reg-report",
        model="gpt-4o",
        instructions="You are an expert in regulatory reporting.",
        tools=file_tool.definitions,
        tool_resources=file_tool.resources
    )
    thread1 = project_client.agents.create_thread()

    # === 5. Agent 2: Task Executor Based on Agent 1 ===
    agent2 = project_client.agents.create_agent(
        name="agent2-task-generator",
        model="gpt-4o",
        instructions="You are a high-level task planner. Wait for user role input, then generate tasks. Ask Agent 1 for any regulatory report details as needed.",
    )
    thread2 = project_client.agents.create_thread()

    # === 6. Agent 1 - Initial Question ===
    q1 = (
        "Please provide a comprehensive list of the schedules or templates in the FR Y-9C report. Include their template codes and descriptions in JSON format. Moreover, understands the questions that agent 2 has and give the answer to that accordingly."
    )
    project_client.agents.create_message(thread_id=thread1.id, role="user", content=q1)
    run1 = project_client.agents.create_run(thread_id=thread1.id, agent_id=agent1.id)
    wait_for_run_completion(project_client, thread1.id, run1["id"])

    agent1_response = get_last_assistant_response(project_client, thread1.id)
    print(f"\n[Agent 1 Response]:\n{agent1_response}\n")

    # === 7. Human Confirms to Trigger Agent 2 ===
    input("\n[Press Enter to trigger Agent 2 after reviewing Agent 1's output...]\n")

    # === 8. Agent 2 - Provide Role and Responsibilities ===
    user_role_info = input("Enter role and responsibilities for Agent 2 to generate the output:\n")
    project_client.agents.create_message(thread_id=thread2.id, role="user", content=user_role_info)
    run2 = project_client.agents.create_run(thread_id=thread2.id, agent_id=agent2.id)
    wait_for_run_completion(project_client, thread2.id, run2["id"])

    agent2_response = get_last_assistant_response(project_client, thread2.id)
    print(f"\n[Agent 2 Initial Response]:\n{agent2_response}\n")

    # === 9. Agent 2 Asks Agent 1 if Needed ===
    while True:
        next_action = input("\n[Agent 2 asks a question to Agent 1? Type the question or 'done' to exit]:\n")
        if next_action.strip().lower() == "done":
            break
        next_action = agent2_response
        # Ask Agent 1
        project_client.agents.create_message(thread_id=thread1.id, role="user", content=next_action)
        run1 = project_client.agents.create_run(thread_id=thread1.id, agent_id=agent1.id)
        wait_for_run_completion(project_client, thread1.id, run1["id"])
        agent1_response = get_last_assistant_response(project_client, thread1.id)
        print(f"\n[Agent 1's Answer]:\n{agent1_response}\n")

        # Give the answer back to Agent 2
        print("[Passing Agent 1's answer back to Agent 2...]\n")
        project_client.agents.create_message(thread_id=thread2.id, role="user", content=agent1_response)
        run2 = project_client.agents.create_run(thread_id=thread2.id, agent_id=agent2.id)
        wait_for_run_completion(project_client, thread2.id, run2["id"])

        agent2_response = get_last_assistant_response(project_client, thread2.id)
        print(f"\n[Agent 2's Updated Output]:\n{agent2_response}\n")

    print("\n[Session ended. Both agent threads remain active for further messaging if needed.]")
