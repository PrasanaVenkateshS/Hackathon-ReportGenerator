import streamlit as st
import asyncio
from chataibackend import run_agent_and_extract

st.set_page_config(page_title="Reg Imagine Chatbot", layout="wide")

st.title("Reg Imagine Chatbot")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Chat message display
for msg in st.session_state.messages:
    role, content = msg["role"], msg["content"]
    if role == "user":
        st.chat_message("user").markdown(content)
    else:
        st.chat_message("assistant").markdown(content)

# Chat input box
if user_input := st.chat_input("How can I help with your report today?"):
    st.chat_message("user").markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            async def run_task():
                return await run_agent_and_extract(user_input)

            response = asyncio.run(run_task())
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})