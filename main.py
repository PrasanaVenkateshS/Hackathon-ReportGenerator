import streamlit as st
from azure.storage.blob import BlobServiceClient
import os
import PyPDF2
from openai import AzureOpenAI
import base64

#STORAGE_ACCOUNT creds
AZURE_CONNECTION_STRING = "<CONN-STRING>"
CONTAINER_NAME = "<CONTAINER_NAME>"
blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# FSD agent creds
endpoint = "<AGENT_END_POINT>"
deployment = "gpt-4o-mini"
subscription_key = "<AGENT_KEY>"
api_version = "2024-12-01-preview"

fsd_client = AzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)


def show_pdf(file):
    file.seek(0)
    pdf_bytes = file.read()
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_display = f"""
    <iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="900" type="application/pdf"></iframe>
    """
    st.markdown(pdf_display, unsafe_allow_html=True)
    file.seek(0)

def get_fsd_content(blob_name):
    fsd_blob_name = blob_name.replace(".pdf", "_fsd.txt")
    try:
        blob_client = container_client.get_blob_client(fsd_blob_name)
        fsd_bytes = blob_client.download_blob().readall()
        return fsd_bytes.decode("utf-8")
    except Exception:
        return ""

def extract_pdf_text(uploaded_file):
    uploaded_file.seek(0)
    reader = PyPDF2.PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def call_fsd_agent(pdf_text, existing_fsd=""):
    messages = [
        {"role": "system", "content": "You are the fsd_agent. Analyze the form and provide a structured summary. Explain what each field is about. Start the resposne with Function Specification Document header"},
        {"role": "user", "content": f"Previous FSD:\n{existing_fsd}\n\nNew Form:\n{pdf_text}"}
    ]
    response = fsd_client.chat.completions.create(
        messages=messages,
        max_tokens=1500,
        temperature=0.3,
        top_p=1.0,
        model=deployment
    )
    return response.choices[0].message.content

def save_fsd_content(blob_name, content):
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(content, overwrite=True)

# Initialize session state
if "step" not in st.session_state:
    st.session_state.step = 1

# Enforce navigation rules
if st.session_state.step == 2 and not st.session_state.get("fsd_output"):
    st.session_state.step = 1

steps = ["1. Upload Document", "2. FSD Agent", "3. TDD Agent", "4.Code Generator"]
st.title("Report Generator")

# Display step indicator
st.markdown("---")
cols = st.columns(len(steps))
for idx, col in enumerate(cols):
    with col:
        step_label = steps[idx]
        color = "#4CAF50" if idx + 1 <= st.session_state.step else "#cccccc"
        st.markdown(f"<div style='text-align: center; padding: 8px; background-color: {color}; color: white; border-radius: 5px;'>{step_label}</div>", unsafe_allow_html=True)
st.markdown("---")

# Step 1: Upload
if st.session_state.step == 1:
    st.header("Step 1: Upload Form Document")
    uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])

    if uploaded_file:
        blob_name = uploaded_file.name
        container_client.upload_blob(blob_name, uploaded_file, overwrite=True)
        st.success("File uploaded successfully and stored in Azure Blob!")

        # show_pdf(uploaded_file)

        if st.button("Analyze with FSD Agent"):
            with st.spinner("Analyzing document using FSD Agent..."):
                pdf_text = extract_pdf_text(uploaded_file)
                existing_fsd = get_fsd_content(blob_name.replace(".pdf", "_fsd.txt"))
                fsd_output = call_fsd_agent(pdf_text, existing_fsd)

                save_fsd_content(blob_name.replace(".pdf", "_fsd.txt"), fsd_output)
                st.session_state.fsd_output = fsd_output
                st.session_state.pdf_blob_name = blob_name
                st.session_state.step = 2
                st.rerun()

    col1, col2 = st.columns([1, 6])
    with col1:
        if st.session_state.step > 1:
            if st.button("⬅️ Back"):
                st.session_state.step -= 1
                st.rerun()

    with col2:
        if st.session_state.get("fsd_output"):
            if st.button("Next ➡️"):
                st.session_state.step = 2
                st.rerun()




# Step 2: FSD Agent Output
elif st.session_state.step == 2:
    st.header("Step 2: FSD Agent Response")
    st.text_area("FSD Agent Generated Output", st.session_state.get("fsd_output", ""), height=400)

    col1, col2 = st.columns([1, 6])
    with col1:
        if st.button("⬅️ Back"):
            st.session_state.step = 1
            st.rerun()

    with col2:
        if st.button("Agree with AI & Proceed to TDD Agent"):
            st.session_state.step = 3
            st.rerun()

# Step 3: TDD Agent Placeholder
elif st.session_state.step == 3:
    st.header("Step 3: TDD Agent Output")
    st.info("To be implemented")

    col1, col2 = st.columns([1, 6])
    with col1:
        if st.button("⬅️ Back"):
            st.session_state.step = 2
            st.rerun()

# Step 4: Generate Code Placeholder
elif st.session_state.step == 4:
    st.header("Step 4: Generate Code")
    st.info("We'll implement this after Step 3!")
