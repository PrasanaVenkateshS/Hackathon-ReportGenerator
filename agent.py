import os
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, MessageAttachment, FilePurpose
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

project_client = AIProjectClient.from_connection_string(
    credential=DefaultAzureCredential(), conn_str=os.getenv('PROJECT_CONNECTION_STRING')
)

with project_client:

    # We will upload the local file and will use it for vector store creation.

    #upload a file
    file = project_client.agents.upload_file_and_poll(file_path='FR_Y-9C20250327_i.pdf', purpose=FilePurpose.AGENTS)
    print(f"Uploaded file, file ID: {file.id}")

    # create a vector store with the file you uploaded
    vector_store = project_client.agents.create_vector_store_and_poll(file_ids=[file.id], name="my_vectorstore")
    print(f"Created vector store, vector store ID: {vector_store.id}")

    # create a file search tool
    file_search_tool = FileSearchTool(vector_store_ids=[vector_store.id])

    # notices that FileSearchTool as tool and tool_resources must be added or the agent will be unable to search the file
    agent = project_client.agents.create_agent(
        model="gpt-4o",
        name="my-agent",
        instructions="You are a helpful agent which is exceptional in the regulatory reporting and having end to end knowledge about the regulatory domain. You are helping the user with their question while retaining your memory for future conversations.",
        tools=file_search_tool.definitions,
        tool_resources=file_search_tool.resources,
    )
    print(f"Created agent, agent ID: {agent.id}")

    # Create a thread
    thread = project_client.agents.create_thread()
    print(f"Created thread, thread ID: {thread.id}")

    # Upload the user provided file as a messsage attachment
    message_file = project_client.agents.upload_file_and_poll(file_path='FR_Y-9C20250327_f.pdf', purpose=FilePurpose.AGENTS)
    print(f"Uploaded file, file ID: {message_file.id}")

    # Create a message with the file search attachment
    # Notice that vector store is created temporarily when using attachments with a default expiration policy of seven days.
    attachment = MessageAttachment(file_id=message_file.id, tools=FileSearchTool().definitions)
    message = project_client.agents.create_message(
        thread_id=thread.id, role="user", content="Please provide a comprehensive list of the schedules or templates including specific templates in the FR Y-9C report, divided into all schedules or templates with template codes along with their descriptions. I must want output to be in a JSON format, where keys are title of schedule and value will be the description.", attachments=[attachment]
    )
    print(f"Created message, message ID: {message.id}")

    run = project_client.agents.create_and_process_run(thread_id=thread.id, agent_id=agent.id)
    print(f"Created run, run ID: {run.id}")

    # project_client.agents.delete_vector_store(vector_store.id)
    # print("Deleted vector store")
    #
    # project_client.agents.delete_agent(agent.id)
    # print("Deleted agent")

    # Retrieve and Print Messages in a Clean Format
    messages = project_client.agents.list_messages(thread_id=thread.id)

    messages_data = messages["data"]

    # Sort messages by creation time (ascending)
    sorted_messages = sorted(messages_data, key=lambda x: x["created_at"])

    print("\n--- Thread Messages (sorted) ---")
    for msg in sorted_messages:
        role = msg["role"].upper()
        # Each 'content' is a list; get the first text block if present
        content_blocks = msg.get("content", [])
        text_value = ""
        if content_blocks and content_blocks[0]["type"] == "text":
            text_value = content_blocks[0]["text"]["value"]
        print(f"{role}: {text_value}")
