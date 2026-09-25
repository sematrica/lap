# Local Agent Platform — Stage 2

Three independent agents can now run as background HTTP services with one Compose
command. The existing interactive CLI, bounded reasoning loop, Ollama client,
tool registry, and tools remain available. Python 3.12+ is required. Dependencies
are httpx, PyYAML, FastAPI, and Uvicorn (plus their dependencies). Tests use unittest.

## Stage 2 architecture

```text
macOS
├── Ollama host service :11434 (shared model server)
├── curl → localhost:8101 / :8102 / :8103
└── Podman Machine (Linux VM)
    └── Compose manages three independent containers, without a pod
        ├── agent-01 :8000 ← config/agent.yaml
        ├── agent-02 :8000 ← config/agent-02.yaml
        └── agent-03 :8000 ← config/agent-03.yaml
            Each: HTTP → Agent → Ollama client
                            └→ ToolRegistry → approval policy → tool
            Ollama URL: http://host.containers.internal:11434
```

An **image** is the packaged Python application. A **container** is a running copy
of that image. An **agent** is that copy's identity, instructions, model, and tool
allowlist, loaded from YAML. **Compose** starts and manages the containers together;
it does not coordinate their reasoning. **Ollama** remains a separate service on
your Mac. Each agent has its own task lock and conversation; models share the same
Ollama server and compete for its resources.

The repository root is `/Users/mac14/Developer/LocalAgentPlatform`. The application
stays in its existing `local-agent-platform` subfolder to preserve paths and tooling.

## Start all three agents

Run these commands in a macOS terminal, not inside an agent prompt:

```bash
cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
podman machine list
podman compose version
ollama list
```

If the Podman machine is stopped, run `podman machine start`. If Compose reports
that no provider exists, run `brew install podman-compose`. Podman's Compose command
uses an [external provider](https://docs.podman.io/en/latest/markdown/podman-compose.1.html).
Open the Ollama application, or use `ollama serve` if it is not already running.

Keep your existing `.env`. For a first installation only, copy `.env.example` to
`.env` and fill in your settings. Set `OLLAMA_MODEL` to an exact installed model
from `ollama list`, for example `llama3.1:latest`. This overrides all three YAML model
values; remove that environment entry if you want different models per YAML.
Compose supplies the host Ollama address explicitly. SMTP/IMAP/NASA credentials
remain in `.env`, never in YAML or the image. Do not share `podman compose config`
output: a provider can expand environment secrets into it.

```bash
podman compose up -d --build
podman compose ps
```

Subsequent starts without code changes: `podman compose up -d`.
Containers use Compose-generated names such as `lap_agent-01_1`; use service names
(`agent-01`) with Compose commands. Old standalone containers named `agent-01` etc.
are separate and are not replaced by Compose. Stop them if you no longer need them:

```bash
podman stop agent-01 agent-02 agent-03 agent-04
```

That optional command stops only the old standalone containers. Their files and
YAML configurations are retained. All Compose services reuse `localhost/local-agent:stage2`.

## Use the HTTP endpoints

| Agent | Base URL | YAML file |
| --- | --- | --- |
| agent-01 | `http://localhost:8101` | `config/agent.yaml` |
| agent-02 | `http://localhost:8102` | `config/agent-02.yaml` |
| agent-03 | `http://localhost:8103` | `config/agent-03.yaml` |

Check identity and health:

```bash
curl -sS http://localhost:8101/info
curl -i http://localhost:8101/health
curl -i http://localhost:8102/health
curl -i http://localhost:8103/health
```

Submit a task to Agent 1 (change the port for another agent):

```bash
curl -sS http://localhost:8101/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task":"What is the capital of France? Answer directly."}'
```

Example response:

```json
{"agent":"agent-01","status":"completed","result":"Paris.","task_id":"generated-uuid"}
```

Web and inbox tools work through the same endpoint and their existing protections:

```bash
curl -sS http://localhost:8101/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task":"Summarize https://example.com and cite the URL."}'

curl -sS http://localhost:8101/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task":"Read my latest 5 emails and summarize them."}'
```

Inbox reading requires IMAP settings and reads real email even when EMAIL_DRY_RUN
is true. Only explicitly enabled tools are available. Nothing executes arbitrary
shell commands. Tools remain behind the original validation and registry boundary.

Requests wait synchronously for a result; there is no queue or task polling endpoint.
Each agent accepts one task at a time. Another request receives HTTP 409 with
`status: busy`; another agent can still accept work. Each task gets a new conversation.
Request bodies must be JSON with only `task`, at most 32 KiB and 16,000 task characters.
Empty/malformed tasks return 422, oversized bodies 413, and incorrect content types 415.

`GET /health` returns 200 when Ollama is reachable and the configured model is
installed. It uses a separate connection with a 3-second timeout, remains available
while a task runs, and returns 503 with `alive: true` when Ollama/model verification
fails. It is not a model-generation benchmark and does not log in to IMAP/SMTP or
call NASA. If another health probe is running, it returns 503 with `status: checking`.
The service stays alive and can recover after Ollama returns. Task-time Ollama errors
return 503; other controlled task failures return 422, and unexpected failures return
a sanitized 500. `/info` exposes identity, model, tools, and approval policy only.

## Approval in a background service

HTTP mode cannot obtain terminal approval. When a validated request reaches any
approval-required tool, the task immediately stops with HTTP 409:

```json
{"agent":"agent-01","status":"approval_required","result":"HTTP services cannot obtain human approval. No email was sent. Run this task through the interactive CLI to review and approve it.","task_id":"generated-uuid","code":"approval_required"}
```

This applies to both real and dry-run email. There is no approval bypass field,
pending approval store, approval link, or automatic resume. Earlier read operations
in a multi-step task may already have completed. To send an email, launch the existing
interactive CLI with the same image and explicitly review its prompt:

```bash
podman run --rm -it --env-file .env \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  localhost/local-agent:stage2
```

The image still defaults to the CLI; Compose explicitly selects the HTTP entrypoint.
`EMAIL_DRY_RUN` controls CLI sending, not service approval or inbox reading.

## Logs, stopping, and updates

```bash
# All agents; Control+C stops following logs, not the services
podman compose logs -f

# Agent 1 only
podman compose logs -f agent-01

# Stop and remove this Compose stack (source, .env, YAML and image stay)
podman compose down
```

Agent events remain JSON on stderr. Task events carry the same generated `task_id`
returned in the response. Tasks, tool arguments, email content, credentials, and
model answers are not written to service logs. HTTP access logs are disabled.
Podman/Compose may add their own prefixes when displaying logs.

After source/dependency changes: `podman compose up -d --build`.
After `.env` or YAML edits: `podman compose up -d --force-recreate`.
A simple restart does not load new environment values; YAML is read at process startup.
Do not delete configurations when rebuilding containers.

## Security and Stage 2 limitations

Host ports bind only to `127.0.0.1`. The service rejects browser Origin headers and
unexpected Host names, has no CORS permission, and marks responses `no-store`.
There is no authentication in this local development stage: other local processes
and users able to access these ports can submit tasks, including reading the configured
mailbox. Other containers on the Compose network are also within the trust boundary.
Do not publish the ports publicly, add a public proxy, or remove these protections.
Compose injects the same `.env` into each agent; choose per-agent env files if account
separation is needed. Podman administrators can inspect container environment values.

Containers run as UID 10001 with read-only filesystems, read-only YAML mounts,
all capabilities dropped, and no privilege escalation. No secret is copied into
the image. There is no Podman socket mount, pod, orchestrator, database, broker,
dashboard, memory, RAG, MCP, or cloud deployment.

Exactly one Uvicorn worker must run per container; multiple workers would have
independent busy locks. A task remains busy if its caller disconnects, until its
bounded loop finishes. There is no cancellation, deduplication, durable task history,
or recovery after a container restart. Avoid automatically retrying timed-out tasks.
Individual HTTP/tool timeouts and iteration limits still apply; a multi-step task
can take several minutes. A forced shutdown can interrupt work. Restart policies
restart exited containers, not merely unhealthy ones, and require Podman Machine to run.

To add Agent 4 later, give `config/agent-04.yaml` its intended name/prompt and add
a Compose service using the shared `*agent` settings, port 8104, and that YAML mount.
No Python copy or orchestrator is needed.

## Project structure and tests

```text
LocalAgentPlatform/
├── .gitignore
├── AGENTS.md
├── CHEATSHEET.md
└── local-agent-platform/
    ├── compose.yaml            # Three persistent services
    ├── Containerfile           # Shared non-root image; CLI default
    ├── requirements.txt
    ├── .env.example            # Copy only on first setup
    ├── config/agent.yaml       # Agent 1
    ├── config/agent-02.yaml    # Agent 2
    ├── config/agent-03.yaml    # Agent 3
    ├── config/agent-04.yaml    # Optional CLI configuration
    ├── src/
    │   ├── service.py          # HTTP lifecycle, validation, busy lock
    │   ├── runtime.py          # Shared registry construction
    │   ├── main.py             # Existing interactive CLI
    │   ├── agent.py            # Existing bounded reasoning loop
    │   ├── approval.py         # CLI approval and service stop policy
    │   ├── llm_client.py
    │   ├── config.py
    │   ├── logger.py
    │   ├── errors.py
    │   └── tools/              # Registry, SMTP, web, IMAP, NASA
    ├── tests/                 # Original tests plus test_service.py
    ├── README.md
    └── VERIFICATION.md
```

Finder `.DS_Store` metadata and `*.save` editor backups are ignored. Existing
backups are preserved locally, including `.env.save` (potential credentials) and
`config/agent-02.yaml.save` (old YAML plus a pasted shell command). Do not use the
backup as an agent configuration or include it in the image. Git ignores do not
erase previously committed data from repository history.

From the application folder with Python 3.12+:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Tests mock Ollama, SMTP, IMAP, and external HTTP. They send no real email and do not
require a running Ollama server. Service tests cover endpoints, validation, busy
behavior, dependency recovery, approval refusal, allowlisting, and secret omission.
FastAPI's [lifespan testing pattern](https://fastapi.tiangolo.com/advanced/testing-events/)
is used to open and close clients predictably.

## Optional public web search

`search_web` discovers sources; `read_webpage` retrieves their contents. No browser,
JavaScript, crawling, login, or new dependency was added. Every call still passes
through ToolRegistry. Search is **opt-in**: the supplied YAML files contain a commented
`search_web` entry, so existing agents do not start sending queries to a provider.

```text
User asks a current question
  → Agent → search_web → BraveSearchProvider
  → titles / snippets / result URLs (untrusted)
  → Agent selects a useful result
  → read_webpage → existing DNS/IP/redirect/content checks
  → Agent → answer with verified source URLs
```

### Provider and cost

The first backend is [Brave Web Search](https://api-dashboard.search.brave.com/api-reference/web/search/get).
It provides structured JSON through a fixed HTTPS endpoint and requires a private
API key. As checked on September 23, 2026, [Brave lists](https://brave.com/search/api/)
$5 per 1,000 Search requests, $5 monthly credits, and a 50-query/second plan capacity.
Check your account's current pricing, quotas, and billing terms before enabling it.
This implementation makes no purchase, creates no account, and has no global billing
cap. Up to three provider attempts per task are allowed; there are no transport retries.
Multiple agents share any account quota associated with the same key.

Queries leave your Mac for Brave. Do not include private email bodies, credentials,
or other sensitive material in a search task. LAP does not log the query, returned
titles, URLs, snippets, or API key. Only the query is sent to Brave, not the whole
conversation or Ollama system prompt. Returned snippets subsequently go to Ollama.

The `SearchProvider` protocol in `src/search_provider.py` accepts a query and returns
title/url/snippet dictionaries. Only its factory/provider implementation needs to
change for a future backend. The initial factory supports `brave` only; there is no
arbitrary endpoint setting or model-controlled provider parameter.

### Enable search for Agent 1

1. Obtain a Search API key through Brave's linked site. Add these settings to your
   existing private `.env` (do not overwrite it with `.env.example`):

   ```dotenv
   SEARCH_PROVIDER=brave
   BRAVE_SEARCH_API_KEY=put-your-real-key-here
   SEARCH_TIMEOUT_SECONDS=10
   ```

2. Edit `config/agent.yaml` and uncomment `search_web` under `tools`. Keep
   `read_webpage` enabled for source verification. For example:

   ```yaml
   tools:
     - search_web
     - read_email
     - nasa_neo_feed
     - read_webpage
     - send_email
   ```

   Agent 2 and Agent 3 remain unchanged unless you enable the tool in their YAMLs.
   Credentials belong in `.env`, never YAML, task JSON, source code, or Git.

3. Install the code update and recreate Agent 1 with the new environment:

   ```bash
   cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
   podman compose up -d --build --force-recreate agent-01
   curl -sS http://localhost:8101/info
   ```

   Check that `tools` includes both `search_web` and `read_webpage`. After future
   `.env`/YAML-only edits, `podman compose up -d --force-recreate agent-01` is enough.
   `/health` still checks Ollama/model availability, not your Brave key or quota.

Should search and read a source:

```bash
curl -sS http://localhost:8101/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task":"What is the latest stable Python release? Prefer python.org and cite the source."}'
```

Should answer without searching:

```bash
curl -sS http://localhost:8101/tasks \
  -H 'Content-Type: application/json' \
  -d '{"task":"What is polymorphism in Java?"}'
```

Watch `podman compose logs -f agent-01` for `web_search_requested`,
`web_search_started`, `web_search_completed`, or `web_search_failed`. Events retain
the HTTP task ID and include counts/error codes, not queries or result contents.

### Bounds and retrieval rules

- Input is exactly `{"query":"..."}`: 1–300 characters, at most 50 words, no control
  characters. No arbitrary headers, endpoints, provider parameters, or credentials.
- At most 5 results per search. Titles are at most 200 characters, URLs 2,048,
  snippets 600. Total serialized tool output is at most 20 KiB; provider bodies
  are capped at 256 KiB. URLs over the limit are discarded, never shortened.
- The provider uses TLS verification, no proxies inherited from the environment,
  no redirects, no reused cookies, and a configurable 1–60 second socket timeout
  (default 10). A body deadline is checked between chunks; one blocked read can
  extend wall time by a socket timeout. Compressed responses are rejected.
- Only actual result `url` fields grant permission to request a page. URLs embedded
  in snippets, webpage text, or invented by the model do not. Permission resets at
  every task, even if the same task text is submitted twice.
- Discovered URLs go through the unchanged read_webpage transport: all DNS answers
  must be public, sockets are pinned, TLS certificates checked, redirects rechecked,
  local/private addresses blocked, HTTPS downgrade blocked, and the existing 2 MiB
  download / 50,000-character text / content-type restrictions still apply. Search
  results can contain inaccessible URLs; discovery never proves a URL safe to fetch.
- Explicit time-sensitive wording (latest/current/news/prices/releases, etc.)
  requires an actual search when enabled. After a substantive search, an enabled
  reader must retrieve at least one page before the final answer. The existing loop
  allows one missing-tool reminder, then stops instead of returning an invented answer.
- Stable programming concepts (polymorphism, inheritance, encapsulation, abstraction,
  recursion) do not offer search unless the task also asks for research, verification,
  or changing information. Other stable questions rely on the model's routing judgment.
- Simple navigation can return discovered links without reading. With the reader
  disabled, substantive requests return a runtime-generated discovery-only message
  and actual result URLs. Empty results return an honest inability to verify.
- HTTP(S) citations in retrieval answers are checked against actual result URLs and
  final page URLs; made-up URLs cause `unverified_source_url`. When the model omits
  citations, the runtime appends returned sources, preferring final read URLs. This
  verifies URL provenance, not whether every claim is supported by the page.
- Explicit no-search instructions and private email/NASA-only tasks block search.
  Mixed research/email tasks require an explicit research request in the original
  user task. These English keyword rules are conservative heuristics, not a complete
  intent classifier or a semantic prompt-injection detector. Prompts additionally
  tell the model never to use external content as instructions or put private tool
  contents in queries. Existing email approval and recipient checks remain mandatory.

Failures use stable tool codes: `invalid_search_query`, `search_configuration_error`,
`search_authentication_error`, `search_rate_limited`, `search_provider_error`,
`search_timeout`, `search_response_error`, `search_response_too_large`,
`search_not_authorized`, and `search_limit`. The existing agent loop reports unresolved
tool errors without displaying model-invented success. Error responses never include
raw provider bodies, authentication headers, or raw transport exceptions.

Search freshness and relevance depend on Brave's index. Source selection and reading
comprehension still depend on the configured Ollama model. Some pages require JavaScript,
block automated clients, or exceed download limits. There is no autonomous crawling,
search scheduling, persisted search history, or cross-task URL permission.

## Existing tools and interactive CLI reference (continued)

The sections below document tools and the original standalone CLI workflow.
Their `local-agent:stage1` examples are historical; use `localhost/local-agent:stage2`
to run the same CLI with the current image. The Compose workflow above is the default
for persistent agents. HTTP mode never prompts for approval or sends email.



## Read email and call NASA NeoWs

Two dedicated tools extend the original runtime. Both are enabled in the supplied
Agent-01 through Agent-04 YAML files; remove a tool name from `tools` to disable it.
No new packages are required. Known numeric/boolean strings emitted by local models
are normalized and then checked against the same limits. If a tool fails and the
model does not correct the call, the runtime reports the unresolved error instead
of showing a potentially invented successful answer. Explicit inbox reads and dated
NASA requests also require an actual tool result before a final answer; the runtime
allows one reminder if the model skips the call, then reports an error. Neither tool performs writes or requires the email
send-approval prompt. The existing `send_email` approval remains mandatory.

### Read Yahoo INBOX

Add these lines to your private `.env`, replacing placeholders locally:

```dotenv
IMAP_HOST=imap.mail.yahoo.com
IMAP_PORT=993
IMAP_USERNAME=your-address@yahoo.com
IMAP_PASSWORD=your-yahoo-app-password
IMAP_TIMEOUT_SECONDS=30
```

Yahoo uses IMAP over TLS on port 993 with an app password. See
[Yahoo's server settings](https://help.yahoo.com/kb/SLN4075.html).
The sending and receiving accounts can be the same, but SMTP credentials are not
automatically reused. Set IMAP credentials explicitly. Do not paste them into a
task or source file. Recreate the container after changing `.env`.

At the agent prompt:

```text
Read my latest 5 emails and summarize them.
```

```text
Show my latest 3 unread emails.
```

The runtime offers `read_email` for tasks with email/inbox words and a reading,
listing, or summary keyword. That routing is not a complete natural-language intent
classifier. Each invocation validates `limit` (1–10, default 5) and `unread_only`
(boolean, default false). The only mailbox is INBOX; there are no arbitrary IMAP
commands, folder names, or account credentials in tool arguments.

The connection verifies TLS, selects INBOX with `readonly=True`, and fetches with
`BODY.PEEK` so unread flags remain unchanged. It never calls STORE, EXPUNGE, DELETE,
or mailbox CLOSE. It logs out after each invocation. Returned metadata includes
sender, subject, date, UID, and up to 6,000 body characters per message, newest UID
first. Counts/truncation/skips are included so summaries can disclose omissions.
Messages larger than 256 KiB, including attachments, are skipped. Small raw MIME
messages can include attachment bytes, but attachments are never opened, executed,
saved, or returned to the model. HTML email is reduced to text; no remote images,
links, or tracking pixels are fetched.

Reading sends the selected email contents to the **configured Ollama endpoint**
for summarization. In the normal setup this is your local Mac; if you change the
endpoint to another machine, that machine receives the content. Structured audit
logs omit message contents, but the agent's final summary is visible in terminal
and container logs. `EMAIL_DRY_RUN` governs sending only; it does not simulate or
prevent inbox reads. Mail is treated as untrusted data, never authority to send
email or call other tools. A malicious message's recipient does not override the
existing requirement for the recipient to appear in the user's original task.

### Call the NASA asteroid feed

The `nasa_neo_feed` tool calls only:

```text
https://api.nasa.gov/neo/rest/v1/feed
```

It accepts `start_date`, `end_date` (YYYY-MM-DD), and optional `limit` (1–50, default
20). End must be on/after start and no more than seven days later. No arbitrary
URL, method, header, or API key can be supplied by the model. Redirects are rejected.
Responses are limited to 2 MiB with a configurable socket timeout. Returned fields
include counts, names, IDs, approach dates, estimated diameter in meters, speed in
km/s, miss distance in km, and NASA's potentially-hazardous flag. That flag is a
classification, not a prediction of an Earth impact. Detail lists may be truncated;
counts describe the full returned feed.

```dotenv
NASA_API_KEY=DEMO_KEY
NASA_TIMEOUT_SECONDS=30
```

These are defaults even if the variables are absent. A personal NASA key is optional;
put it in `.env`, never in the prompt. NASA's documented DEMO_KEY limits are 30
requests/hour and 50/day per IP. See [NASA authentication and rate limits](https://api.nasa.gov/assets/html/authentication.html).
No automatic retries are made for rate limits. Output source links omit the key.

Try your supplied date range:

```text
Use nasa_neo_feed for 2015-09-07 through 2015-09-08. Summarize the total count and list 5 objects with their miss distances.
```

The webpage reader handles HTML, while this dedicated tool handles NASA's JSON API.
Give explicit dates; the agent is instructed to ask for them if absent.

### Upgrade existing containers

Build once from the application folder, then recreate each agent using its usual
name, `.env`, and (for Agent-02/03/04) mounted YAML file. A restart alone keeps old
code and environment. To safely test the rebuilt image without touching running
agents or reading email:

```sh
podman run --rm \
  -e OLLAMA_BASE_URL=http://host.containers.internal:11434 \
  -e OLLAMA_MODEL=llama3.1:latest -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 \
  --task 'Use nasa_neo_feed for 2015-09-07 through 2015-09-08 and summarize the count.'
```

No `.env` is used in this NASA test; it relies on DEMO_KEY and cannot authenticate
to Yahoo. Inbox behavior is covered by mocked unit tests; live mailbox verification
must be done after you configure IMAP and request a read in your own agent session.

## Public webpage reading (added after Stage 1)

Agents can now read static public HTML/text from URLs you put in the current task.
This is a URL reader, not a search engine or interactive browser. No new dependency,
API key, browser installation, or SMTP credentials are needed. Example task:

```text
Read https://example.com/ and summarize what the page is for. Cite the URL.
```

`read_webpage` is registered through `runtime.py` and enabled in the supplied Agent-01 through
Agent-04 YAML configurations. Remove `read_webpage` from an agent's `tools` list to
disable it. The tool is offered for user-supplied URLs and, when search is enabled,
URLs returned in actual search results during the current task. Its requested URL
must belong to one of those two sets. Redirects are followed at most three
times, checking each new destination. Links found in page text are not fetched.

The reader accepts HTTP port 80 and HTTPS port 443, verifies HTTPS certificates,
rejects credentials in URLs, checks all DNS results for public addresses, and pins
the connection to a validated address. Local/Podman services, private/reserved IPs,
and IPv6 translation/tunnel destinations are blocked. It ignores proxy environment
variables, sends no credentials or cookies, runs no scripts, and fetches no images.
Limits: 2 MiB response body, 50,000 characters returned to the model, 10-second
socket timeout, and a 20-second body-read budget per response. DNS uses the system
resolver timeout; these are not a hard wall-clock deadline for the entire tool call.
Compressed responses are rejected to avoid decompression expansion. Large pages,
PDFs, authenticated sites, and JavaScript-only pages may not work.

Page content is returned as `untrusted_text`, with a system instruction that it is
source information rather than authority to change tasks or invoke tools. Prompt
instructions reduce model mistakes; they are not a guarantee against misleading
summaries. The runtime separately prevents reading URLs invented by page content
and prevents email to recipients not supplied by the user. Email approval remains
mandatory. Read operations themselves do not prompt for approval; including a URL
in a task enables reading that URL. Use public URLs intended to be retrieved.
`EMAIL_DRY_RUN` affects email only: webpage reads still make real HTTP requests.

### Use the updated image

From `/Users/mac14/Developer/LocalAgentPlatform/local-agent-platform`:

```sh
podman build -t local-agent:stage1 -f Containerfile .
podman run --rm -it \
  -e OLLAMA_BASE_URL=http://host.containers.internal:11434 \
  -e OLLAMA_MODEL=llama3.1:latest -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 \
  --task 'Read https://example.com/ and summarize what the page is for. Cite the URL.'
```

This temporary test uses no `.env` or SMTP credentials and does not replace existing
agents. Existing containers still use their old code: stop/remove and recreate each
one using its usual run command to adopt the new image. Agent-02/03/04 should keep
their existing YAML mount. Rebuilding alone, or restarting an old container, does
not change the code in that container.

The separate `src/tools/web_tool.py` module uses standard-library HTTP/socket/TLS
code to pin the checked IP while preserving the original HTTPS hostname. The
Ollama client continues to use `httpx`. See the
[OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
for the network validation concerns behind this design.

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
