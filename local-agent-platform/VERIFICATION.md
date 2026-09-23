# Stage 1 verification — 2026-09-21

## Read-only inbox and NASA feed tools — 2026-09-22

Added `read_email` (verified-TLS IMAP INBOX, read-only selection, BODY.PEEK) and
`nasa_neo_feed` (fixed HTTPS NASA endpoint, validated dates, environment API key).
Both are enabled in the four existing YAML configurations. No private `.env` files
were read or changed, and no existing containers were stopped or replaced.

- **62 unit tests passed** in the Developer project, including MIME handling,
  unread-preserving commands, skipped oversized messages, credential redaction,
  fixed NASA endpoint, date limits, rate limits, malformed responses, tool gating,
  model round trips, and rejection of invented answers after errors/missing calls.
- The initial direct NASA request succeeded with DEMO_KEY: 21 objects for
  2015-09-07 through 2015-09-08 (one flagged potentially hazardous).
- An early container test failed validation because llama3.1 supplied limit as a
  numeric string, then fabricated an answer. Numeric strings are now normalized
  before bounds validation, and unresolved tool errors suppress model final prose.
- A second test exposed routing that missed the exact `nasa_neo_feed` name.
  Routing was fixed; explicit inbox reads/dated NASA requests now require actual
  tool results, with one reminder and a safe error if the model omits the call.
- Final Podman build passed: image
  `07e96b5b1bf931111364a1caace3e01374a6c554b14606fc403af306e0bf0592`.
- Final live container + Ollama test passed in two model turns: NASA tool_requested,
  tool_completed/read, 21 objects, and accurate details for three returned objects.
- Yahoo inbox access was tested with mocks only. No mailbox contents were accessed,
  no messages were marked read/deleted, and no real email was sent during development.
  Live account verification requires IMAP_USERNAME and IMAP_PASSWORD supplied by
  the user in `.env`, then an explicit read request in their agent session.

Final command executed:

```sh
podman run --rm \
  -e OLLAMA_BASE_URL=http://host.containers.internal:11434 \
  -e OLLAMA_MODEL=llama3.1:latest -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 \
  --task 'Use nasa_neo_feed for 2015-09-07 through 2015-09-08. Tell me the total count and list 3 objects. Do not read or send email.'
```

Model interpretation is still fallible even after a successful tool result. The
new checks prevent unchecked final answers when required data was never retrieved;
they do not prove the model's summary is factually correct in every case.


## Webpage completion fix — 2026-09-22

The Context-AI-DataSet URL returned HTTP 200 and a 6,554-byte body, but the reader
set a socket timeout after HTTPResponse had consumed Content-Length and closed
the final socket reference. That raised EBADF and became web_connection_error.
The read loop now checks response completion before touching the socket again.

A regression test using the real HTTPResponse parser failed on the old code and
passes on the fix; premature EOF remains an error. All 45 tests pass. A live read
of https://sematrica.github.io/Context-AI-DataSet/ now returns 2,399 characters
without truncation. User changes MAX_BYTES=2 MiB and MAX_TEXT=50,000 are preserved.
Download-size error messages now use the configured byte limit.


## Public webpage reader — 2026-09-22 UTC

Added `read_webpage` to the current Developer copy, registered it, and enabled it in
Agent-01/02/03/04 YAML. No `.env` files or running agents were changed.

- **43 unit tests passed** in the copied project. Tests cover URL/task allowlisting,
  public-IP validation, mixed DNS answers, DNS pinning, private redirect blocking,
  downgrade/redirect limits, HTML extraction, content/size/time limits, untrusted
  content, the model tool-result round trip, and unchanged email approval.
- A real HTTPS read of `https://example.com/` succeeded using the pinned transport.
- Podman image build succeeded: `local-agent:stage1`, image
  `d6066243e7aa5a7ccfae48b69706fadb515861b0c2f6d0cf968ee4c1a6b4771a`.
- A temporary non-root/read-only container reached native Ollama, called
  `read_webpage`, retrieved example.com, and produced a correct summary with its URL
  in two model turns (exit 0). Email dry-run was forced and no SMTP credentials
  were passed. No real email was sent.

Command used for the live container test:

```sh
podman run --rm \
  -e OLLAMA_BASE_URL=http://host.containers.internal:11434 \
  -e OLLAMA_MODEL=llama3.1:latest -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 \
  --task 'Use read_webpage to read https://example.com/ and summarize what the page is for. Cite its URL. Do not send email.'
```

Limitations: supplied URLs only, static HTML/plain text only, no search/login/JS/PDF.
The model can still misinterpret sources; untrusted-content instructions are not a
proof of prompt-injection immunity. DNS uses the system resolver's timeout; socket
and body-read limits do not establish a hard whole-operation wall-clock deadline.
Existing containers must be recreated to use the new image.


## Follow-up: unwanted email proposals (22:22 UTC)

Fixed the always-offered email tool: definitions now depend on a literal recipient
in the current task, and dispatch rejects recipients absent from that task before
approval. System instructions explicitly distinguish answering, drafting, and sending.
This recipient check does not replace human approval or classify all natural-language
intent. Tests now total **31 passing**, including unsolicited email and invented
recipient regressions.

Podman is now installed. Rebuilt `local-agent:stage1` successfully (image
`54587631165e7303b3d3eb9fada4d43a991dd7a9384142879a6d4daaa6261d02`).
The sandbox initially blocked the Podman socket; the approved outside-sandbox build
succeeded. No credentials file was read during this fix.

Tested temporary containers with the documented read-only/capability restrictions,
`OLLAMA_BASE_URL=http://host.containers.internal:11434`,
`OLLAMA_MODEL=llama3.1:latest`, and `EMAIL_DRY_RUN=true`, without SMTP credentials:

- The exact France question returned **Paris.** in one turn with no tool request.
- An explicit email request displayed its preview, accepted the dry-run approval,
  returned `email_dry_run`, and completed in two turns. No real email was sent.

The existing interactive `agent-01` container was not replaced: it still uses the
old image until the user stops/removes it and runs the rebuilt image.

## Original implementation verification (historical)

The results below describe the original environment before Podman was installed.

Implementation follows the uploaded `Pasted text.txt` requirements. The supplied
`/mnt/data/Pasted text.txt` path did not exist on this Mac; the attachment was
retrieved from the referenced conversation. The workspace contained no existing
code repository. All new files are under `local-agent-platform/`; synced `sources/`
was left untouched.

## Results

| Check | Result |
| --- | --- |
| Python runtime | Bundled Python 3.12.14; system Python is 3.9.6 |
| Dependency installation | Passed after an approved network-sandbox retry |
| Unit tests | **28 passed**; HTTP and SMTP mocked |
| Dependency consistency | `pip check`: no broken requirements |
| Python compilation | Passed for `src` and `tests` |
| Offline dry-run demonstration | Passed; mock asserts SMTP was never opened |
| Host Ollama API | Passed outside the network sandbox |
| Default sample model `qwen3` | Not installed; useful `model_not_found` error verified |
| Live ordinary question | Passed with `OLLAMA_MODEL=llama3.1:latest`; returned 4 |
| Live Ollama email dry run | Passed in two model turns; preview, approval, tool result, final response |
| Podman image build | **Blocked:** `zsh:1: command not found: podman` (exit 127) |
| Container → host Ollama | Not run: Podman unavailable |
| Real SMTP delivery | Not run; no real credentials configured and no real email sent |

The initial sandboxed Ollama requests reported connection failures. An approved
check outside the sandbox reached Ollama, so the initial failures were not evidence
that the host server was down. Host model listing returned `qwen3.8:latest`,
`llama2:latest`, and `llama3.1:latest`. The latter was used for the live tests without
downloading or changing models. Both local and outside-sandbox Podman build
attempts returned command-not-found; common Podman installation paths were absent.

## Exact commands executed

From this project directory, the test environment was created with:

```sh
/Users/mac14/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q src tests
```

The first dependency attempt failed with DNS/network errors inside the sandbox;
the retry above completed successfully. Direct dependencies installed were
`httpx==0.28.1` and `PyYAML==6.0.3`.

Offline dry-run check, with scripted Ollama responses and mocked SMTP:

```sh
printf 'y\n' | .venv/bin/python -m tests.dry_run_demo
```

It displayed the email preview, emitted `approval_granted` and `email_dry_run`,
returned `DRY RUN — email would have been sent. No email was sent.`, and printed
`Verified: SMTP was never opened.` You can run the demo without the pipe to review
and enter approval yourself. Automated affirmative input is used only for this
explicitly forced dry-run test; real email should be reviewed interactively.

Host connectivity and installed-model checks:

```sh
curl --fail --show-error --silent --max-time 10 http://localhost:11434/api/tags
ollama list
OLLAMA_BASE_URL=http://localhost:11434 .venv/bin/python -m src.main --check
```

The API/list commands succeeded outside the sandbox. The final command deliberately
used the sample model and exited 1 with `model_not_found`, since `qwen3` is absent.

Successful ordinary task using an installed model:

```sh
OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_MODEL=llama3.1:latest EMAIL_DRY_RUN=true \
  .venv/bin/python -m src.main \
  --task 'What is 2 + 2? Answer briefly without using tools.'
```

It printed `Ollama: connected`, answered `4`, and exited 0.

Successful live-model email dry run:

```sh
printf 'y\n' | OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_MODEL=llama3.1:latest EMAIL_DRY_RUN=true \
  .venv/bin/python -m src.main \
  --task 'Use send_email exactly once to email person@example.com with subject "Stage 1 dry run" and body "The report is ready." Report the tool result accurately.'
```

Observed sequence:

```text
ollama_connected
llm_request (iteration 1)
tool_requested (send_email)
approval_requested
[full email preview; dry-run mode]
approval_granted
tool_started
email_dry_run
tool_completed (status: dry_run)
llm_request (iteration 2)
agent_completed
```

The runtime and final model response both stated that no email was sent. Exit 0.
No SMTP credentials were necessary, and `EMAIL_DRY_RUN=true` forces the email
implementation to return before opening SMTP.

Image build attempted both inside and outside the sandbox:

```sh
podman build -t local-agent:stage1 -f Containerfile .
```

Both attempts failed with exit 127: `zsh:1: command not found: podman`. No image
was built, so non-root execution, image contents, and the Podman-to-Ollama network
route have not yet been verified in a running container.

## Remaining checks on your Mac

Follow the [README](README.md) to finish Podman CLI/engine setup. In `.env`, use
`OLLAMA_MODEL=llama3.1:latest` to repeat the successful host-model tests without a
new model download, or install the sample `qwen3` model. Keep the container endpoint
as `http://host.containers.internal:11434`.

After building, this command verifies the actual container route and model:

```sh
podman run --rm --env-file .env \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 --check
```

Then run the interactive dry-run workflow in the README, reject one proposal, and
approve a fresh proposal. Configure SMTP and test real delivery to an address you
own only after those checks pass. These remaining live checks are required before
claiming the full operational Stage 1 definition of done.
