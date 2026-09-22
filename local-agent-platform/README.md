# Local Containerized AI Agent — Stage 1

One Python agent, one configurable Ollama endpoint, and one controlled SMTP email
tool. Python 3.12+ is required. Runtime dependencies are only `httpx` and PyYAML;
tests use Python's built-in `unittest`. Email defaults to **dry-run**.

## What each component does

**LLM ≠ Agent ≠ Tool ≠ Container.** Ollama hosts the language model on your Mac.
The model proposes answers or tool calls. The Python application is the agent:
it maintains the current conversation, validates proposals, requests approval,
and decides which registered tools can run. The email tool uses SMTP for delivery.
Podman isolates the application in a Linux container; it does not host the model.

```text
macOS: Ollama + local model, port 11434
                 ↑ HTTP
Podman Machine: agent container (non-root)
                 CLI → bounded agent loop → Ollama client
                            ↓ tool request
                 registry → validation → approval policy → SMTP email tool
                            ↓ result back to model
                        final answer
```

The application uses Ollama's [chat API](https://docs.ollama.com/api/chat), with
`stream: false` and native tool definitions. The model must support tool calling
for email requests. Ordinary questions require no tool. Model output is never
interpreted as Python or shell commands.

## Files and responsibilities

```text
local-agent-platform/
├── Containerfile                 Python 3.12 image; UID/GID 10001
├── requirements.txt              Two pinned direct dependencies
├── .env.example                  Safe defaults; no real credentials
├── .gitignore / .containerignore  Exclude secrets and local build files
├── config/agent.yaml             Identity, instructions, model, enabled tools
├── src/
│   ├── main.py                   Interactive CLI and connectivity check
│   ├── agent.py                  Explicit bounded conversation loop
│   ├── config.py                 YAML/env validation and configuration objects
│   ├── llm_client.py             HTTP transport and response validation
│   ├── approval.py               Separate approval policy and terminal preview
│   ├── logger.py                 JSON audit events to stderr
│   ├── errors.py                 Safe user-facing error messages
│   └── tools/
│       ├── registry.py           Registered AND enabled tool enforcement
│       └── email_tool.py         Email validation and SMTP transport
└── tests/                        Mocked HTTP/SMTP tests; no real emails
```

For each task, the email tool is offered only if the user's text contains a
literal recipient address. Dispatch also checks that the proposed recipient was
in that task, so an invented address cannot reach approval. This is a recipient
check, not a natural-language intent classifier: for tasks that contain addresses,
the model must still follow the instruction to send only when explicitly asked,
and the human must review the proposal. Questions without addresses get no email
tool definition. If a recipient is missing, repeat the complete email task with
the address; tasks do not share conversation history.

A tool must be registered in `main.py` **and** enabled in YAML. Setting `tools: []`
disables tools; an unregistered tool in YAML is a startup error. Approval happens
in the registry after validation and before execution. The SMTP implementation
contains no input prompts. Each task starts a fresh conversation; no conversation
or credential database is created.

## macOS setup, step by step

Open Terminal. The following commands assume this generated project location:

```sh
cd /Users/mac14/.codex/.chatgpt-projects/g-p-6ab1707274e481918b5ef8c7f9b868a0/local-agent-platform
```

If you move the folder, change that path. Do not run these commands from its parent.

### 1. Verify Podman and its Linux machine

```sh
podman --version
podman machine list
```

The first command checks the command-line installation; the second lists Linux
virtual machines. If `podman` is not found, open Podman Desktop and finish its
Podman engine/CLI setup, then open a new Terminal. See the official
[Podman Desktop installation guide](https://podman-desktop.io/docs/installation/macos).

Only if there is no machine, create one:

```sh
podman machine init
```

If the machine is stopped, start it, then verify the engine:

```sh
podman machine start
podman info
```

If it is already running, skip `start`. These are host setup commands, not
capabilities given to the agent.

### 2. Start and verify Ollama on the Mac

```sh
ollama --version
open -a Ollama
ollama list
```

Wait for the Ollama application to start before running `ollama list`. Use an
installed tool-capable model. On the implementation Mac, `llama3.1:latest` was
already installed and passed both live tests; set `OLLAMA_MODEL=llama3.1:latest`
in `.env` to use it without downloading another model. The sample YAML selects `qwen3`; if it is missing,
this command downloads its model weights to the Mac:

```sh
ollama pull qwen3
```

Check the API from macOS and request an ordinary answer:

```sh
curl --fail --show-error --max-time 10 http://localhost:11434/api/tags
curl --fail --show-error --max-time 180 http://localhost:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3","stream":false,"messages":[{"role":"user","content":"What is 2 + 2? Answer briefly."}]}'
```

The first response must list installed models. The second must contain
`message.content`. If using another model, substitute its exact name in the
request and `.env`. Cold model loading can take longer than a normal response.

### 3. Configure the agent safely

```sh
cp .env.example .env
chmod 600 .env
nano .env
```

Do the copy once; repeating it would overwrite your settings. Leave
`EMAIL_DRY_RUN=true` and the SMTP fields empty for initial tests. Keep
`OLLAMA_BASE_URL=http://host.containers.internal:11434` for containers.
`.env` is excluded from Git and the image build context. The application itself
does not parse `.env`: Podman injects it using `--env-file`. Use plain `KEY=value`
lines without `export` or shell quoting in this file.

Edit `config/agent.yaml` to change the name, role, description, prompt, model,
or enabled tools. The prompt is the model's instructions; update its self-name
if you change the agent name. `OLLAMA_MODEL` takes precedence over YAML; remove
that line from `.env` to use the YAML model.

### 4. Build the image

```sh
podman build -t local-agent:stage1 -f Containerfile .
```

This downloads the Python base image and dependencies and copies only application
code and sample YAML. Ollama and credentials are not included. On Apple Silicon,
Podman selects the matching architecture automatically.

### 5. Verify container-to-Mac Ollama connectivity

```sh
podman run --rm --env-file .env \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 --check
```

This executes `GET /api/tags` **inside the agent container** and checks that the
configured model appears. Success prints `Ollama: connected`, emits the JSON event
`ollama_connected`, and exits with status 0. It does not generate text or use SMTP.
A successful macOS `curl` alone does not prove this container route works.

Containers use `host.containers.internal`, not `localhost`: container-localhost
means the container itself. Podman Machine provides the special hostname through
its networking layer ([Podman networking reference](https://docs.podman.io/en/latest/markdown/podman-run.1.html#add-host-hostname-hostname-ip)).
No inbound port publishing is needed.

If macOS `curl` works but the container check fails, check Podman Machine, DNS,
and macOS firewall settings first. If the Podman route cannot reach a loopback-only
Ollama listener, quit Ollama from its menu, configure its listener, and reopen it:

```sh
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
open -a Ollama
```

The [Ollama macOS FAQ](https://docs.ollama.com/faq#setting-environment-variables-on-mac)
documents this setting. Binding to all interfaces can expose the unauthenticated
API to your network; use the Mac firewall to restrict access and do not publish
port 11434 to the Internet. For a foreground server instead of the Mac app, quit
the app first and run `OLLAMA_HOST=0.0.0.0:11434 ollama serve` in another Terminal.
To undo the Mac app setting, run `launchctl unsetenv OLLAMA_HOST` and restart Ollama.

### 6. Run one interactive agent, with dry-run forced on

```sh
podman run -it --name agent-01 --env-file .env -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

`-it` keeps the terminal attached for tasks and approval. `--name` gives this
container a convenient name for logs and lifecycle commands. The command drops
Linux capabilities, prevents privilege escalation, and makes the image filesystem
read-only. It mounts no host directories or administrative sockets. No `-p`
option is used because the agent has no inbound service.

First enter an ordinary question:

```text
What is 2 + 2? Answer briefly.
```

Then request this dry-run email:

```text
Use send_email to email person@example.com with subject "Stage 1 dry run" and body "The report is ready."
```

The exact address matters: the agent has no contacts or address-book access.
Check the preview. Press Enter or type `n` to reject. To test the approved dry
run, request the email again, review it, and type `y`. Expected runtime output:

```text
EMAIL SEND REQUEST
Agent: agent-01
Mode: DRY RUN — no email will be sent
To:
person@example.com
Subject:
Stage 1 dry run
Body:
The report is ready.
Approve this email operation? [y/N]: y
Tool result: DRY RUN — email would have been sent. No email was sent.
```

The model's final wording may vary. The runtime result and JSON `email_dry_run`
event are authoritative. Dry-run returns before any SMTP connection, even if
credentials are present. Approval defaults to no; only `y`/`yes` (case-insensitive)
approves. EOF or Ctrl-C at the approval prompt rejects the request. The rejection
is returned to the model. If the model retries, it still needs a fresh approval.

### 7. Logs, stopping, removing, and recreating

In another Terminal:

```sh
podman logs -f agent-01
```

JSON audit records include timestamp, level, agent, event, and iteration/tool
where applicable. Events cover startup, LLM requests, validation failures,
approval, execution, dry-run/sending, completion, and errors. Ctrl-C stops following
the logs. `podman logs agent-01` shows the existing log without following.

The interactive console also shows task responses and approval previews. With a
TTY, Podman combines stdout/stderr, so its full console log can contain email
previews even though **structured audit events omit email/task content**. Treat
console logs as sensitive. Outside a TTY, stderr contains only the JSON events.

Type `exit` or `quit`, or press Ctrl-D at the task prompt, to exit cleanly. Ctrl-C
during a model request also exits. From a second Terminal you can stop and remove
the container:

```sh
podman stop agent-01
podman rm agent-01
```

Stop only if still running. Removing the container removes its stored console
logs. Re-run step 6 to recreate it with the same code. There is no persistent
agent state. A container name cannot be reused until the old container is removed.

### 8. Enable real email only after the dry run works

Edit `.env` with your provider's settings, using a provider app password if required:

```dotenv
EMAIL_DRY_RUN=false
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your-username
SMTP_PASSWORD=your-app-password
SMTP_FROM=you@example.com
SMTP_USE_TLS=true
SMTP_TIMEOUT_SECONDS=30
```

These are placeholders, not working credentials. This implementation uses
**STARTTLS**, commonly on port 587; implicit TLS on port 465 is not implemented.
TLS certificate validation is enabled. Authenticated SMTP requires TLS. An
anonymous local relay may omit username/password; `SMTP_USE_TLS=false` is only
appropriate for an explicitly trusted test relay. SMTP configuration is checked
when an approved real-send request executes, so ordinary questions still work
without email credentials.

Stop/remove the dry-run container, then recreate it **without** the forced
`-e EMAIL_DRY_RUN=true` override:

```sh
podman run -it --name agent-01 --env-file .env \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

Ask it to email an address you own. Review the entire preview, which must say
`Mode: REAL EMAIL`, before typing `y`. Rejection must never connect to SMTP.
A successful result means the SMTP server accepted the email, not that inbox
delivery is guaranteed. SMTP errors can leave delivery uncertain: check the
provider before retrying. The runtime does not automatically retry network sends.

### 9. Run Python tests locally

Use a Python 3.12+ installation; Apple's system Python may be older:

```sh
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

If you use another Python 3.12+ executable, substitute its path for `python3.12`.
No test sends real email or needs Ollama. HTTP uses `httpx.MockTransport`; SMTP
uses mocks. For just the dry-run cases:

```sh
.venv/bin/python -m unittest discover -s tests -k dry_run -v
```

For an offline interactive preview using scripted model replies (no Ollama needed):

```sh
.venv/bin/python -m tests.dry_run_demo
```

Review the displayed proposal and type `y` or press Enter to reject. The demo
asserts that SMTP is never opened.

To run the CLI directly on the Mac instead of in a container:

```sh
OLLAMA_BASE_URL=http://localhost:11434 EMAIL_DRY_RUN=true .venv/bin/python -m src.main --check
OLLAMA_BASE_URL=http://localhost:11434 EMAIL_DRY_RUN=true .venv/bin/python -m src.main
```

The local CLI reads exported environment variables, not `.env`. These two
commands need no SMTP settings. For a one-task invocation, add
`--task 'What is 2 + 2?'`; approval still reads stdin if tools are requested.

## Configuration reference

| Setting | Default | Meaning |
| --- | --- | --- |
| YAML `name`, `role`, `description`, `system_prompt` | Sample agent | Agent identity and instructions |
| YAML `model` | `qwen3` | Model when no environment override exists |
| YAML `tools` | `[send_email]` | Enabled registered tools |
| `OLLAMA_MODEL` | YAML value | Model override |
| `OLLAMA_BASE_URL` | `http://host.containers.internal:11434` | Configurable HTTP endpoint |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | HTTP timeout, 1–3600 seconds |
| `MAX_AGENT_ITERATIONS` | `10` | Maximum model turns per task, 1–100 |
| `EMAIL_DRY_RUN` | `true` | Never contact SMTP when true |
| `SMTP_HOST`, `SMTP_FROM` | Empty | Required for real email |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Empty | Optional authentication pair |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USE_TLS` | `true` | STARTTLS with certificate validation |
| `SMTP_TIMEOUT_SECONDS` | `30` | SMTP timeout, 1–300 seconds |

Boolean environment values must be `true` or `false`. The model endpoint cannot
contain embedded credentials. HTTP proxy environment variables are deliberately
ignored for direct Ollama connectivity. Custom YAML paths use `--config PATH`.
For a different identity using the same image, mount only the chosen YAML file
read-only at `/app/config/agent.yaml`; do not mount your home directory. Stage 1
runs a single agent and implements no multi-agent orchestration.

## Boundaries and troubleshooting

- **Ollama unavailable:** check macOS `curl`, then the container `--check` command.
- **Missing model:** use `ollama list`, pull the model on the Mac, or change `OLLAMA_MODEL`.
- **Tool support error:** use a model supporting Ollama native tool calls. Plain-text
  mentions of tools are never executed.
- **Timeout:** try a smaller installed model or increase the timeout. A finite timeout
  bounds socket operations; it is not a total wall-clock task deadline.
- **Malformed response:** invalid JSON, incomplete messages, invalid tool structures,
  and batches over eight tool calls are rejected before dispatch.
- **Iteration limit:** the runtime stops after the configured number of model turns.
  Each response has at most eight tool calls, so total tool proposals are bounded.
  Already completed emails cannot be undone; review visible results before retrying.
- **Invalid email:** only one plain ASCII recipient address is supported. Display
  names, comma-separated lists, empty fields, and header injection are rejected.
- **SMTP failure:** check sender, STARTTLS port, credentials, and provider policy.
  Raw server errors are not forwarded to the model or logs because they may contain
  credentials. Errors use stable codes such as `smtp_authentication_error`.
- **Permission or data access:** no shell tool, filesystem tool, host-home mount,
  Podman socket, or administrative API is provided. The process has outbound network
  access, not a destination firewall allowlist. Model-requested actions can only use
  the registered and enabled email tool, with approval.

There are no orchestration services, databases, memory/RAG, MCP, web UI, cloud
integrations, or agent frameworks in Stage 1. Secrets stay in the environment,
never in model messages. For simplicity, interactive approval is the only provided
policy, and SMTP is the only external action.

## Verification in the implementation environment

See [VERIFICATION.md](VERIFICATION.md) for executed commands, test results, and
blocked live checks. A successful unit suite does not prove a container build or
live model/SMTP delivery; those checks are reported separately.
