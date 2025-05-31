import streamlit as st
from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas
import os
import PyPDF2
from openai import AzureOpenAI
import base64
import pymssql
import hashlib
from datetime import datetime, timedelta
import requests

#STORAGE_ACCOUNT creds
AZURE_CONNECTION_STRING = "<YOUR _CONN>"
CONTAINER_NAME = "<YOUR_CONTAINER>"
DATA_DICTIONARY="data_dictionary.txt"
STORAGE_ACCOUNT="<YOUR_STORAGE_ACCOUNT>"
STORAGE_ACCOUNT_KEY="<YOUR_KEY>"
LOGICAPP_URL = "<YOUR_URL>"
DB_SERVER_URL="<YOUR_DB_SERVER_URL>"
DB_NAME="<DB>"
DB_USERNAME="<DB_USER>"
DB_PASSWORD="<DB_PWD>"


# FSD agent creds
endpoint = "<YOUR_END_POINT>"
deployment = "gpt-4o-mini"
subscription_key = "<YOUR_KEY>"
api_version = "2024-12-01-preview"

fsd_client = AzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)

blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# Initialize session state
if 'page' not in st.session_state:
    st.session_state.page = 'login'
if 'doc_name' not in st.session_state:
    st.session_state.doc_name = ''
if 'subFormName' not in st.session_state:
    st.session_state.subFormName = ''

#Get document url for sending as email attchment
def generate_blob_sas_url(blob_name):
    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT,
        container_name=CONTAINER_NAME,
        blob_name=blob_name,
        account_key=STORAGE_ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1)
    )
    return f"https://uploadeddocumentstore.blob.core.windows.net/files/{blob_name}?{sas_token}"

#Triiger Email via LogicApps
def send_email_via_logicapps(email, subject, message, blob_url, doc_name):
    payload = {
        "document_name": doc_name,
        "email": email,
        "subject": subject,
        "message": message,
        "blob_url": blob_url
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(LOGICAPP_URL, json=payload, headers=headers)
    return response.status_code in [200, 202]

def show_pdf(file):
    file.seek(0)
    pdf_bytes = file.read()
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_display = f"""
    <iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="900" type="application/pdf"></iframe>
    """
    st.markdown(pdf_display, unsafe_allow_html=True)
    file.seek(0)

def get_content(blob_name):
    fsd_blob_name = blob_name
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

def call_tdd_agent(data_dict_text,existing_tdd,existing_fsd):
    messages = [
        {"role": "system", "content": "You are the tdd_agent. Analyze fsd, data_dictionary and give a clear TDD logic document on how to fill the values. Start the resposne with Technical Specification Document header"},
        {"role": "user", "content": f"Previous TDD:\n{existing_tdd}\n\nFSD content:\n{existing_fsd}\n\nDataDictionary:\n{data_dict_text}"}
    ]
    response = fsd_client.chat.completions.create(
        messages=messages,
        max_tokens=1500,
        temperature=0.3,
        top_p=1.0,
        model=deployment
    )
    return response.choices[0].message.content

def call_code_agent(data_dict_text,existing_tdd,existing_fsd):
    messages = [
        {"role": "system", "content": "You are the code_generator_agent. Analyze fsd, data_dictionary, tdd and give a clear Python code runnable on how to fill the values from the csv input files to the form. Output on running the python code you generate shoud be a pdf form with filled values"},
        {"role": "user", "content": f"TDD:\n{existing_tdd}\n\nFSD content:\n{existing_fsd}\n\nDataDictionary:\n{data_dict_text}"}
    ]
    response = fsd_client.chat.completions.create(
        messages=messages,
        max_tokens=1500,
        temperature=0.3,
        top_p=1.0,
        model=deployment
    )
    return response.choices[0].message.content

def save_content(blob_name, content):
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(content, overwrite=True)

def get_data_dictionary_text():
    blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=DATA_DICTIONARY)
    return blob_client.download_blob().readall().decode("utf-8")

# Hashing passwords
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Database connection
def get_connection():
    conn = pymssql.connect(server=DB_SERVER_URL, user=DB_USERNAME, password=DB_PASSWORD, database=DB_NAME)
    return conn

# Check if user exists
def user_exists(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Users WHERE username=%s", (username,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Signup function
def signup_user(username, password):
    if user_exists(username):
        return False, "Username already exists."
    conn = get_connection()
    cursor = conn.cursor()
    hashed_pw = hash_password(password)
    cursor.execute("INSERT INTO Users (username, password) VALUES (%s, %s)", (username, hashed_pw))
    conn.commit()
    conn.close()
    return True, "User registered successfully."

# Login function
def login_user(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    hashed_pw = hash_password(password)
    cursor.execute("SELECT * FROM Users WHERE username=%s AND password=%s", (username, hashed_pw))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Login Page
def login():
    st.set_page_config(page_title="Login System", layout="centered")
    st.title("Login / Signup Page")

    menu = ["Login", "Sign Up"]
    choice = st.sidebar.selectbox("Choose Option", menu)

    if choice == "Login":
        st.subheader("Login to Your Account")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if login_user(username, password):
                st.success(f"Welcome {username}! You are now logged in.")
                st.session_state.page = 'page1'
                st.rerun()
            else:
                st.error("Incorrect username or password.")

    elif choice == "Sign Up":
        st.subheader("Create New Account")
        username = st.text_input("Create Username")
        password = st.text_input("Create Password", type="password")
        if st.button("Sign Up"):
            success, message = signup_user(username, password)
            if success:
                st.success(message)
                st.info("You can now log in using your credentials.")
            else:
                st.error(message)


#PAGE 1
def page1():
    st.title("Page 1: Select a Project")
    if st.button("Project FYR"):
        st.session_state.doc_name = "Project FYR"
        st.session_state.page = 'page2'
        st.rerun()
    if st.button("Project Bronco"):
        st.session_state.doc_name = "Project Bronco"
        st.session_state.page = 'page2'
        st.rerun()


# PAGE 2
def page2():
    st.title("Page 2: Project Details")
    st.write(f"Selected Project: **{st.session_state.doc_name}**")
    if st.button("Generate HC-E"):
        st.session_state.subFormName = "HC -E"
        st.session_state.page = 'page3'
        st.rerun()
    if st.button("Generate HC-D"):
        st.session_state.subFormName = "HC -D"
        st.session_state.page = 'page3'
        st.rerun()

    if st.button("<- Back",key="back_button_page2"):
        st.session_state.page = 'page1'
        st.rerun()


# PAGE3
def page3():
    # Initialize session state
    if "step" not in st.session_state:
        st.session_state.step = 1
    print(st.session_state.doc_name)
    print(st.session_state.subFormName)


    # Enforce navigation rules
    if st.session_state.step == 2 and not st.session_state.get("fsd_output"):
        st.session_state.step = 1

    steps = ["1. Provide Email", "2. FSD Agent", "3. TDD Agent", "4.Code Generator"]
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
        # st.header("Step 1: Upload Form Document")
        # uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])

        st.session_state.fsd_email = st.text_input("Email Address of FSD Reviewer")
        st.session_state.tdd_email = st.text_input("Email Address of TDD Reviewer")
        st.session_state.code_email = st.text_input("Email Address of Code Reviewer")

        blob_name="HC-E_Form.pdf"

            # show_pdf(uploaded_file)

        if st.button("Analyze with FSD Agent"):
            with st.spinner("Analyzing document using FSD Agent..."):
                # pdf_text = extract_pdf_text(uploaded_file)
                pdf_text=get_content(blob_name)
                print(pdf_text)
                existing_fsd = get_content(blob_name.replace(".pdf", "_fsd.txt"))
                fsd_output = call_fsd_agent(pdf_text, existing_fsd)

                save_content(blob_name.replace(".pdf", "_fsd.txt"), fsd_output)
                st.session_state.fsd_output = fsd_output
                st.session_state.pdf_blob_name = blob_name
                st.session_state.step = 2
                st.rerun()

        col1, col2 = st.columns([1, 6])
        with col1:
            if st.session_state.step > 1:
                if st.button("<- Back"):
                    st.session_state.step -= 1
                    st.rerun()

        with col2:
            if st.session_state.get("fsd_output"):
                if st.button("Next ->"):
                    st.session_state.step = 2
                    st.rerun()




    # Step 2: FSD Agent Output
    elif st.session_state.step == 2:
        st.header("Step 2: FSD Agent Response")
        st.text_area("FSD Agent Generated Output", st.session_state.get("fsd_output", ""), height=400)
        
        if st.button("Send FSD Email"): 
            blob_url = generate_blob_sas_url(st.session_state.pdf_blob_name.replace(".pdf", "_fsd.txt"))
            if send_email_via_logicapps(
                st.session_state.fsd_email,
                subject="FSD Document Generated",
                message="Please review the attached FSD document.",
                blob_url=blob_url,
                doc_name=st.session_state.pdf_blob_name.replace(".pdf", "_fsd.txt")
            ):
                st.info(f"An email has been sent to {st.session_state.fsd_email}.")
        
        col1, col2 = st.columns([1, 6])
        with col1:
            if st.button("<- Back"):
                st.session_state.step = 1
                st.rerun()

        with col2:
            if st.button("Agree with AI & Proceed to TDD Agent"):
                with st.spinner("Analyzing document using TDD Agent..."):
                    data_dict_text = get_data_dictionary_text()
                    existing_tdd = get_content(st.session_state.pdf_blob_name.replace(".pdf", "_tdd.txt"))
                    tdd_output = call_tdd_agent(data_dict_text, existing_tdd, st.session_state.get("fsd_output", ""))

                    save_content(st.session_state.pdf_blob_name.replace(".pdf", "_tdd.txt"), tdd_output)
                    st.session_state.tdd_output = tdd_output
                    st.session_state.step = 3
                    st.rerun()


    # Step 3: TDD Agent Placeholder
    elif st.session_state.step == 3:
        st.header("Step 3: TDD Agent Output")
        st.text_area("TDD Agent Generated Output", st.session_state.get("tdd_output", ""), height=400)

        if st.button("Send TDD Email"): 
            blob_url = generate_blob_sas_url(st.session_state.pdf_blob_name.replace(".pdf", "_tdd.txt"))
            if send_email_via_logicapps(
                st.session_state.tdd_email,
                subject="TDD Document Generated",
                message="Please review the attached TDD document.",
                blob_url=blob_url,
                doc_name=st.session_state.pdf_blob_name.replace(".pdf", "_tdd.txt")
            ):
                st.info(f"An email has been sent to {st.session_state.tdd_email}.")

        col1, col2 = st.columns([1, 6])
        with col1:
            if st.button("Back"):
                st.session_state.step = 2
                st.rerun()

        with col2:
            if st.button("Agree with AI & Proceed to Code Agent"):
                with st.spinner("Analyzing document using Code Agent..."):
                    data_dict_text = get_data_dictionary_text()
                    existing_tdd = get_content(st.session_state.pdf_blob_name.replace(".pdf", "_tdd.txt"))
                    code_output = call_code_agent(data_dict_text, existing_tdd, st.session_state.get("fsd_output", ""))

                    save_content(st.session_state.pdf_blob_name.replace(".pdf", "_code.txt"), code_output)
                    st.session_state.code_output = code_output
                    st.session_state.step = 4
                    st.rerun()

    # Step 4: Generate Code Placeholder
    elif st.session_state.step == 4:
        st.header("Step 4: Code Agent Output")
        st.text_area("Code Agent Generated Output", st.session_state.get("code_output", ""), height=400)


        if st.button("Send Code to Email"): 
            blob_url = generate_blob_sas_url(st.session_state.pdf_blob_name.replace(".pdf", "_code.txt"))
            if send_email_via_logicapps(
                st.session_state.code_email,
                subject="Code Generated",
                message="Please review the attached Code document.",
                blob_url=blob_url,
                doc_name=st.session_state.pdf_blob_name.replace(".pdf", "_code.txt")
            ):
                st.info(f"An email has been sent to {st.session_state.code_email}.")


        col1, col2 = st.columns([1, 6])
        with col1:
            if st.button("Back"):
                st.session_state.step = 3
                st.rerun()
        with col2:
            if st.button("Agree with AI & Finish"):
                    st.session_state.step = None
                    st.session_state.page ='page1'
                    st.rerun()


if st.session_state.page == 'login':
    login()
elif st.session_state.page == 'page1':
    page1()
elif st.session_state.page == 'page2':
    page2()
elif st.session_state.page == 'page3':
    page3()