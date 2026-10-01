# My-Ai-Project

练手项目：从零构建并理解一个带工具、记忆、LangGraph 和 MCP 的 AI Agent。

## 01 · Mini Agent: Day 1

This first exercise is deliberately **not** an agent framework. It makes one
LLM request from a command-line program. The next exercises will add tools,
an action loop, logging, tests, and MCP one at a time.

## What you will learn

- How an application reads a secret without putting it in source control.
- How to make a request with the OpenAI Responses API.
- How to handle the most common failure modes instead of merely printing a
  Python traceback.

## Setup (Windows PowerShell)

From this directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace `your_api_key_here` with your own OpenAI API key.
Never paste a real key into GitHub, chat, or source code.

## Run

```powershell
python main.py "用两句话解释 AI Agent 是什么。"
```

## Completion checklist

- [ ] The command returns an answer.
- [ ] Deleting the key from `.env` produces the clear missing-key message.
- [ ] `.env` does not appear in `git status`.
- [ ] You can explain the purpose of `load_dotenv`, `OpenAI()`, and
      `client.responses.create(...)`.

## Why start here?

An agent is not a special API call. It is an application that repeatedly asks
a model to choose a next action, executes approved tools, records the result,
and decides whether to continue. Before building that loop, this small program
makes the model call and its error handling completely visible.

## Next milestone

Add a `calculate` function as the first tool. The model will receive its tool
schema, request a call when appropriate, and the program will execute it and
return the result to the model.

## Day 2: Tool Calling Agent

`02_tool_calling_agent.py` is the next exercise. It gives the model one local
tool, `calculate`. For arithmetic questions, the model must ask Python to run
the tool; it then receives the result and writes the final answer.

Run the offline calculator tests first (this has no API cost):

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Then run an arithmetic question:

```powershell
.\.venv\Scripts\python.exe 02_tool_calling_agent.py "(25 + 17) * 3 等于多少？"
```

You should see three stages: `[工具调用]`, `[工具结果]`, and `[最终回答]`.

## Day 3: Local Notes Learning Assistant

`03_learning_assistant.py` adds a second tool: `search_notes`. The model can
now choose between calculation and searching the Markdown files in `notes/`.
This is deliberately a visible, keyword-based retrieval step before learning
vector databases and full RAG.

Run all local tests first (no API cost):

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Then ask a question that should use your notes:

```powershell
.\.venv\Scripts\python.exe 03_learning_assistant.py "根据我的笔记解释 LangGraph 是什么？"
```

Expected flow:

```text
你的问题
  ↓
[工具调用] search_notes(...)
  ↓
Python 从 notes/ 读取相关笔记
  ↓
[最终回答] 模型依据笔记组织答案
```

Try editing or adding your own `.md` file in `notes/`, then ask the assistant
about it. That is the key idea of retrieval: change the knowledge source
without retraining the model.

## Day 4: The Same Agent as a LangGraph Workflow

`04_langgraph_learning_assistant.py` keeps the same DeepSeek model and the
same two local tools, but replaces the hidden `for` loop with a visible graph:

```text
START → model → (tools → model) → finish → END
                 \________________/
                    repeat if needed
```

- **State**: the shared `messages`, `rounds`, and `answer` data.
- **Node**: a named step: `model`, `tools`, or `finish`.
- **Edge**: the route between steps. The conditional edge checks whether the
  model asked to call a tool.

Run all local tests first (no API cost):

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Then run the LangGraph version:

```powershell
.\.venv\Scripts\python.exe 04_langgraph_learning_assistant.py "根据笔记解释 LangGraph 的状态、节点和边"
```

Watch the console output. `[节点：...]` tells you which graph node is running;
`[条件边]` tells you why the workflow continues or ends. This is the same
Agent loop from Day 2, now expressed as a graph you can extend with retries,
human approval, memory, or more tools.

## Day 5: Short-Term Memory Chat

`05_memory_chat_agent.py` adds an `InMemorySaver` checkpointer. The graph now
saves the message state under one `thread_id`, so later questions in the same
running program can use earlier turns as context.

```text
同一个 thread_id
第 1 次提问 → 保存 messages 到内存
第 2 次提问 → 读取已有 messages → 回答 → 再保存
```

Run it:

```powershell
.\.venv\Scripts\python.exe 05_memory_chat_agent.py
```

Then type these two messages one at a time:

```text
我叫小王，我的目标是成为 AI Agent 工程师。
我叫什么？我的目标是什么？
```

Useful commands: `/history` displays the current saved messages, `/new` starts
a new empty conversation, and `/exit` exits. This is **short-term memory only**:
it is stored in RAM and is lost when the program stops. Do not put passwords,
API keys, or private data into a learning demo's chat history.

## Day 6: Persistent Local Memory (SQLite)

`06_persistent_memory_agent.py` replaces Day 5's RAM-only `InMemorySaver`
with `SqliteSaver`. It saves the same LangGraph state in `agent_memory.sqlite`
inside this project folder. The database is ignored by Git because it can
contain your conversation text.

```text
第一次运行（--thread xiaowang） → messages 写入 agent_memory.sqlite
关闭程序
再次运行（--thread xiaowang） → 读取相同 messages → 继续聊天
```

Run this command exactly. Choose a simple, non-secret thread name:

```powershell
.\.venv\Scripts\python.exe 06_persistent_memory_agent.py --thread xiaowang
```

First run, say:

```text
我叫小王，我正在学习 AI Agent。
/exit
```

Run the exact same command again, then ask:

```text
我叫什么？我正在学习什么？
```

It should remember both facts. `/history`, `/new`, and `/exit` work as in Day
5. Do not put API keys, passwords, ID numbers, or other sensitive information
into the chat: this version deliberately writes conversation text to a local
database. For a production service, you would also add authentication,
encryption, data-retention rules, and a server database.

## Day 7: MCP Notes Server

MCP (Model Context Protocol) is a standard way for an AI application to
discover and use tools supplied by a separate service. Day 7 moves the local
note search and calculator out of the Agent and into an MCP Server.

```text
DeepSeek Agent (MCP Client) → discovers tools → Local MCP Server → notes/ and calculator
```

The server is [mcp_notes_server.py](mcp_notes_server.py). It exposes three
tools: `search_learning_notes`, `list_learning_notes`, and
`calculate_expression`.

First, run the offline client demo. It has no API cost and proves that the MCP
Client can discover and invoke the server's tools:

```powershell
.\.venv\Scripts\python.exe 07_mcp_client_demo.py
```

Then run the complete DeepSeek + MCP Agent:

```powershell
.\.venv\Scripts\python.exe 07_mcp_learning_agent.py "根据我的笔记解释 MCP 是什么？"
```

The expected output is: `[MCP 发现工具]` → `[MCP 工具调用]` → `[MCP 工具结果]`
→ final answer. `notes/mcp.md` is the new MCP learning note. The server is
local and only exposes the three explicitly defined tools, but in real work
never connect to an unknown MCP Server before checking its source and what
permissions its tools need.

## Day 8: Integrated Learning Agent

`08_integrated_learning_agent.py` combines the four engineering pieces you
have learned into one small, real Agent:

```text
You → LangGraph model node → DeepSeek decides
              ↓ tool call                  ↓ answer
       MCP tools node → Local MCP Server → finish
              ↓
     SQLite saves all conversation messages under --thread
```

- **LangGraph** makes the loop and its conditional route visible.
- **MCP** lets the Agent discover the note-search and calculator tools instead
  of hard-coding them in the Agent.
- **SQLite** retains one conversation after the program is closed.
- **DeepSeek** chooses whether to answer or to call an MCP tool.

Run the offline tests first (they do not call DeepSeek):

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Then start the complete Agent with a non-secret conversation name:

```powershell
.\.venv\Scripts\python.exe 08_integrated_learning_agent.py --thread xiaowang
```

Try this sequence, entering one line at a time:

```text
我叫小王，我正在完成第八步。
根据我的笔记解释 MCP 是什么？
(25 + 17) * 3 等于多少？
/exit
```

Run the exact same command again and ask `我叫什么？我正在完成哪一步？`.
It should remember the answer. The new `integrated_agent_memory.sqlite` file
contains the conversation text locally and is ignored by Git. Do not enter API
keys, passwords, ID numbers, or other sensitive data. This demo connects to the
local MCP Server in one Python process so it is easy to debug; the same server
can later be run through stdio for an external MCP host.

## Day 9: Transparent RAG Knowledge Base

`09_rag_learning_assistant.py` introduces RAG (Retrieval-Augmented
Generation). It does not send every note to the model. Instead, it splits the
local Markdown/text notes into short chunks, ranks them with the transparent
BM25 retrieval formula, and sends only the best chunks to DeepSeek.

```text
Question → retrieve local note chunks → DeepSeek answers from those chunks → citations
```

The program prints the retrieved source labels before the answer. A source
such as `mcp.md#片段2` lets you inspect exactly which local note passage was
given to the model. If retrieval finds no relevant material, the program does
not call the model and says that the local knowledge base lacks enough
information.

Run the offline tests first (no API cost):

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Then run the RAG assistant:

```powershell
.\.venv\Scripts\python.exe 09_rag_learning_assistant.py "根据我的笔记解释 RAG 是什么？"
```

Watch for this order: `[检索]` → `[来源]` → `[最终回答]`. Add your own `.md` or
`.txt` note under `notes/`, then ask a question about it. That is the practical
idea of RAG: update the source files and the assistant can use the new
knowledge without retraining a model. The MCP Server also exposes
`retrieve_note_chunks`, so a later Agent can discover this RAG tool just like
the calculator and note-search tools.

## Day 10: RAG Regression Evals

`10_evaluate_rag.py` is an offline, repeatable quality gate for Day 9. It
uses fixed questions in `evals/rag_retrieval_cases.json` to check whether the
expected note source still appears in the top-k retrieval results. This metric
is called **Hit@K**.

```text
fixed question → retrieve top K chunks → expected source found? → pass / fail
```

Run it before and after changing notes, chunking, or the retrieval algorithm.
It does not call DeepSeek and costs nothing:

```powershell
.\.venv\Scripts\python.exe 10_evaluate_rag.py
```

The default benchmark requires 100% Hit@3. A failed case prints its expected
source and the sources actually retrieved, so you can investigate a real
regression instead of guessing. `rag_evaluation.py` also validates that a RAG
answer's `【file#片段N】` citations only refer to chunks retrieved in that turn.

To add a benchmark, append one JSON object to
`evals/rag_retrieval_cases.json`:

```json
{
  "id": "my-topic",
  "question": "我要测试的问题",
  "expected_sources": ["my-note.md"]
}
```
