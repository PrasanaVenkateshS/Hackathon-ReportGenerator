import os
import time
import fitz  # PyMuPDF for PDF text extraction
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, FilePurpose

# === 1. Setup environment and client ===
load_dotenv()

project_client = AIProjectClient.from_connection_string(
    credential=DefaultAzureCredential(),
    conn_str=os.getenv("PROJECT_CONNECTION_STRING")
)

# === 2. Preprocess PDFs to .txt if needed ===
def convert_pdf_to_text(input_pdf, output_txt):
    doc = fitz.open(input_pdf)
    text = "\n".join([page.get_text() for page in doc])
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Converted {input_pdf} -> {output_txt}")

# Optional: preprocess any PDF to .txt before upload (skip if already .txt or extractable)
# Example:
# convert_pdf_to_text("report1.pdf", "report1.txt")

# === 3. List of files to upload ===
DOCUMENT_FILES = [
    "FR_Y-9C20250327_f.pdf",
    "FR_Y-9C20250327_i.txt"
]

# for i in DOCUMENT_FILES:
#     convert_pdf_to_text(i,i.split('.')[0]+'.txt')

with project_client:
    # === 4. Upload all files and collect file IDs ===
    file_ids = []
    for file_path in DOCUMENT_FILES:
        uploaded = project_client.agents.upload_file_and_poll(
            file_path=file_path,
            purpose=FilePurpose.AGENTS
        )
        file_ids.append(uploaded.id)
        print(f"Uploaded {file_path} -> File ID: {uploaded.id}")

    # === 5. Create a combined vector store ===
    vector_store = project_client.agents.create_vector_store_and_poll(
        file_ids=file_ids,
        name="combined_vectorstore"
    )
    print(f"Created vector store: {vector_store.id}")

    # === 6. Create the FileSearchTool and agent ===
    file_search_tool = FileSearchTool(vector_store_ids=[vector_store.id])

    agent = project_client.agents.create_agent(
        model="gpt-4o",
        name="reg-report-agent",
        instructions=(
            "You are an expert in regulatory reporting. Use the provided documents "
            "in your vector store to answer the user's questions precisely. Always use grounded facts."
        ),
        tools=file_search_tool.definitions,
        tool_resources=file_search_tool.resources
    )
    print(f"Created agent: {agent.id}")

    # === 7. Create a conversation thread ===
    thread = project_client.agents.create_thread()
    print(f"Created thread: {thread.id}")

    # === 8. Ask the first question ===
    first_question = (
        "Please provide a comprehensive list of the schedules or templates in the FR Y-9C report. "
        "Include their template codes and descriptions in JSON format."
    )

    message = project_client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=first_question
    )

    run = project_client.agents.create_run(
        thread_id=thread.id,
        agent_id=agent.id
    )

    while True:
        run_status = project_client.agents.get_run(thread_id=thread.id, run_id=run["id"])
        if run_status["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(1)

    messages = project_client.agents.list_messages(thread_id=thread.id)
    sorted_messages = sorted(messages["data"], key=lambda x: x["created_at"])

    for msg in reversed(sorted_messages):
        if msg["role"] == "assistant":
            content_blocks = msg.get("content", [])
            if content_blocks and content_blocks[0]["type"] == "text":
                print(f"\nAssistant: {content_blocks[0]['text']['value']}\n")
                break

    # === 9. Interactive chat loop ===
    def chat_with_agent(project_client, agent_id, thread_id):
        print("Chat session started. Type your question or 'exit' to quit.\n")

        while True:
            user_input = input("You: ")
            if user_input.lower() in ("exit", "quit"):
                print("Chat session ended.")
                break

            project_client.agents.create_message(
                thread_id=thread_id,
                role="user",
                content=user_input
            )

            run = project_client.agents.create_run(
                thread_id=thread_id,
                agent_id=agent_id
            )

            while True:
                run_status = project_client.agents.get_run(thread_id=thread_id, run_id=run["id"])
                if run_status["status"] in ("completed", "failed", "cancelled"):
                    break
                time.sleep(1)

            messages = project_client.agents.list_messages(thread_id=thread_id)
            sorted_messages = sorted(messages["data"], key=lambda x: x["created_at"])

            for msg in reversed(sorted_messages):
                if msg["role"] == "assistant":
                    content_blocks = msg.get("content", [])
                    if content_blocks and content_blocks[0]["type"] == "text":
                        print(f"\nAssistant: {content_blocks[0]['text']['value']}\n")
                        break

    # === 10. Start chatting ===
    chat_with_agent(project_client, agent.id, thread.id)
