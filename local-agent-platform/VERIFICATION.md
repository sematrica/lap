# Stage 1 verification — 2026-09-21

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
