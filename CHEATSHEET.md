# Local Agent Platform — first-time user command guide

For macOS / Apple Silicon, Podman, native Ollama, and this Stage 1 application.
Prepared September 21, 2026. Commands use your new project location.

## 1. Understand what you are running

| Component | What it does | Where it runs |
| --- | --- | --- |
| Codex | Helps you develop and modify this project | Codex app |
| Ollama | Loads the local language model and answers model requests | Your Mac |
| Podman Machine | Provides the Linux virtual machine needed by containers | Your Mac |
| Image `local-agent:stage1` | Packaged Python application used to create containers | Podman image storage |
| Container `agent-01` | One running copy of your Python agent | Inside Podman Machine |
| `send_email` | Validates and delivers approved email through SMTP | Agent process |
| Yahoo SMTP | Accepts outgoing email using your sending account | Yahoo's servers |

Agent-01 is your Python application, not a Codex agent. The model proposes actions;
the runtime validates them and asks you to approve each email. A container is an
instance of an image. A Podman *pod* groups containers; you do not need a pod here.

Multiple containers can run independently from the same image. They do not talk
to one another or coordinate work. They share Ollama's resources, so concurrent
requests may be slower. The application has no web dashboard or persistent chat
memory. Each task starts a fresh conversation.

## 2. Know which prompt you are typing into

| Prompt on screen | What to enter |
| --- | --- |
| `mac14@... %` | Terminal commands such as `podman ps` |
| `Enter a task ... >` | Plain-language tasks, not Terminal commands |
| `Approve this email operation? [y/N]:` | `y` to approve; Enter or `n` to reject |
| Nano editor | File contents; Ctrl+O saves, Enter confirms, Ctrl+X exits |

Do not type the displayed `%` or `>` prompt yourself. Copy only the contents of
command blocks. The backslash at the end of a command line means the command
continues on the next line; copy the entire block, with nothing after each `\`.
These shell commands work in macOS's default zsh as well as bash.

For management commands while the agent is waiting for a task, open another
Terminal tab with Command+T. Do not enter `podman stop` into the agent task prompt.

## 3. Your folders: two different roots

**Git repository / Codex project root:**

```text
/Users/mac14/Developer/LocalAgentPlatform
```

**Application folder — most commands in this guide run here:**

```text
/Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
```

Enter the application folder at the start of each new Terminal tab:

```sh
cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
pwd
```

`pwd` prints the current folder. A prompt showing `~` means your home folder.
Relative paths such as `.env` and `Containerfile` are resolved from your current
folder; that is why `.env` was not found when you ran commands from `~`.

Useful navigation:

```sh
ls
ls -la
open .
```

`ls` lists files; `ls -la` includes hidden files such as `.env`; `open .` opens the
current folder in Finder. Finder's Command+Shift+Period toggles hidden files.

| File | Purpose |
| --- | --- |
| `.env` | Runtime environment and SMTP credentials; private |
| `.env.example` | Public sample settings with no real credentials |
| `config/agent.yaml` | Agent-01's identity, instructions, model, tools |
| `config/agent-02.yaml` | Separate configuration for Agent-02 |
| `config/agent-03.yaml` | Separate configuration for Agent-03 |
| `Containerfile` | Instructions for building the image |
| `src/` | Python application code |
| `tests/` | Automated tests with mocked external operations |
| `README.md` | Architecture and setup documentation |
| `VERIFICATION.md` | Historical test/build results |

## 4. First-time prerequisites — skip what is already installed

Check the installed tools:

```sh
brew --version
podman --version
ollama --version
```

If Homebrew is available but Podman is missing:

```sh
brew install podman
```

Podman Desktop is an optional graphical interface; the command-line engine is
enough. To install that interface through Homebrew:

```sh
brew install --cask podman-desktop
```

If Ollama is missing, install it from [ollama.com/download](https://ollama.com/download).
No Ollama installation belongs inside the agent image.

Check the Linux machine:

```sh
podman machine list
```

Only if no machine exists:

```sh
podman machine init
```

If the machine exists but is stopped:

```sh
podman machine start
```

Verify that Podman can reach it:

```sh
podman info
```

Do not create a new machine every time you run the application. Your existing
machine can host all of these containers.

## 5. Start Ollama and choose an installed model

```sh
open -a Ollama
ollama list
```

Wait a moment after opening Ollama if the list command cannot connect immediately.
This project's live tests used `llama3.1:latest`. If that model is absent:

```sh
ollama pull llama3.1:latest
```

This downloads model weights and can take time and disk space. To see currently
loaded models, rather than all installed models:

```sh
ollama ps
```

Verify the Ollama HTTP API on the Mac:

```sh
curl --fail --show-error --max-time 10 http://localhost:11434/api/tags
```

A JSON model list means the Mac can reach Ollama. Opening `http://localhost:11434/`
in a browser is a server check; it is not the agent's chat interface.

## 6. Configure the application without exposing credentials

Enter the application folder first:

```sh
cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
ls -l .env
```

If `.env` exists, keep it. **Only if it is missing**, create it:

```sh
cp .env.example .env
```

Restrict its permissions and open it:

```sh
chmod 600 .env
nano .env
```

For initial use, set these values, editing existing lines instead of adding duplicates:

```dotenv
OLLAMA_BASE_URL=http://host.containers.internal:11434
OLLAMA_MODEL=llama3.1:latest
OLLAMA_TIMEOUT_SECONDS=120
MAX_AGENT_ITERATIONS=10
EMAIL_DRY_RUN=true
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_USE_TLS=true
SMTP_TIMEOUT_SECONDS=30
```

Use plain `KEY=value`, no `export`, and no surrounding shell quotes. Keep comments
on their own lines. Save in Nano with Ctrl+O, Enter, Ctrl+X.

`.env` is a hidden text file, not a command. Podman loads it with `--env-file` when
creating the container. The Python application does not automatically load it.
Do not paste `.env` contents into chats, screenshots, or Git commits.

## 7. Build and verify the container image

From the application folder:

```sh
podman build -t local-agent:stage1 -f Containerfile .
podman images
```

The final `.` means use the current folder as the build context. The image includes
application code and the default YAML configuration, but not `.env` or Ollama.
Building an image does not start an agent and does not update existing containers.

Verify the actual container-to-Mac connection:

```sh
podman run --rm --env-file .env \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 --check
```

Expected: `Ollama: connected`, a JSON `ollama_connected` event, then exit.
This checks the endpoint and installed model; it does not send email.
`--rm` removes this temporary check container after it exits.

The container uses `host.containers.internal:11434`. Using `localhost:11434` from
inside a container would point back at that container, not your Mac.

## 8. First interactive run — force email dry-run

If no container named `agent-01` exists, run:

```sh
podman run -it --name agent-01 --env-file .env \
  -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

| Option | Meaning |
| --- | --- |
| `run` | Create a new container and start it |
| `-it` | Interactive terminal for tasks and approval |
| `--name agent-01` | Name used by status/log/stop commands |
| `--env-file .env` | Load the saved settings at creation time |
| `-e EMAIL_DRY_RUN=true` | Override the file and guarantee no SMTP delivery |
| `--read-only` | Make the container's application filesystem read-only |
| `--cap-drop=all` | Drop Linux capabilities |
| `--security-opt=no-new-privileges` | Prevent privilege escalation |

These commands publish no inbound ports and mount no home directory or Podman socket.

Try these at the **agent task prompt**, one at a time:

```text
What is the capital of France?
```

```text
Explain the difference between an image and a container in simple terms.
```

```text
Send an email to person@example.com with subject "Stage 1 dry run" and body "The report is ready."
```

Review the recipient, subject, body, and mode. Press Enter to reject a proposal.
Repeat the complete email task, then type `y` to test an approved dry run.
Expected runtime result: `DRY RUN — email would have been sent. No email was sent.`

A dry run does not test Yahoo authentication or SMTP networking. It returns before
opening SMTP. The model's wording can vary; the runtime result is the authority.

The corrected runtime offers email only when the current task contains an email
address, and it rejects invented recipients before approval. This is not a full
intent classifier: still review proposals for tasks that contain addresses.
Always include the recipient in the current task; earlier tasks are not remembered.

## 9. Daily start, resume, exit, and stop

Check what already exists before choosing `run` or `start`:

```sh
podman ps -a
```

| Container state | Action |
| --- | --- |
| No `agent-01` exists | Use `podman run ...` from section 8 or 11 |
| `agent-01` exists and is stopped | Use `podman start -ai agent-01` |
| `agent-01` is already running | Return to its Terminal, or use `podman attach agent-01` |
| Settings/code changed | Recreate it; a simple restart does not load new settings/image |

To start a stopped container and interact with it:

```sh
podman start -ai agent-01
```

To attach to an already running one:

```sh
podman attach agent-01
```

Use one attached input terminal per container to avoid conflicting keystrokes.
To detach while leaving it running, press **Ctrl+P, then Ctrl+Q**.

At the task prompt, type `exit` or `quit` to stop normally. At an email approval
prompt, Enter rejects the proposal; it does not quit the application.

From another Terminal, stop the container:

```sh
podman stop agent-01
```

After it has stopped, remove it if you need to recreate it:

```sh
podman rm agent-01
```

Removing this container does not remove your source files, `.env`, or image. It
removes the container and its stored console logs. Save needed logs first. Check
that no email operation is in progress before stopping; interrupted delivery may
be uncertain and should not be blindly retried.

To stop the Linux machine after stopping your agents:

```sh
podman machine stop
```

This affects all containers on that machine. It does not quit native Ollama.

## 10. See containers, resource usage, and logs

Run these in a separate Terminal:

```sh
podman ps
podman ps -a
podman stats
```

These show running containers, all containers, and live CPU/memory usage respectively.
Ctrl+C stops the stats display without stopping the containers.

Inspect recent output or follow it:

```sh
podman logs --tail 100 agent-01
podman logs -f agent-01
```

Ctrl+C stops following logs; the container continues running.

To save the current console log to a private file in the application folder:

```sh
(umask 077; podman logs agent-01 > agent-01.log 2>&1)
```

Console logs can contain email previews and answers. JSON audit events intentionally
omit email bodies and credentials, but a terminal session combines audit output
with human-facing previews. Treat saved logs as private.

| Event | Meaning |
| --- | --- |
| `ollama_connected` | Endpoint and configured model verified |
| `llm_request` / `llm_response` | A model turn started/completed |
| `tool_requested` | Model proposed a tool |
| `approval_requested` | Validated request reached the approval policy |
| `approval_denied` | Operation rejected; not executed |
| `email_dry_run` | Simulated operation; no SMTP connection |
| `email_sent` | SMTP server accepted the message |
| `tool_failed` / `agent_error` | Read the safe error code and user-facing explanation |

For basic container state without dumping secrets:

```sh
podman inspect --format '{{.State.Status}}' agent-01
```

Avoid sharing unrestricted `podman inspect` output: it can include environment secrets.
Podman Desktop's Containers screen is an optional graphical view of the same engine.

## 11. Configure Yahoo and send real email

Yahoo's outgoing server is `smtp.mail.yahoo.com`; this app uses port **587 with
STARTTLS**. Port 465 implicit TLS is not implemented in this application.
See [Yahoo SMTP settings](https://help.yahoo.com/kb/SLN4075.html).

Generate an app password for this application in
[Yahoo Account Security](https://login.yahoo.com/account/security), using
[Yahoo's app-password instructions](https://ca.help.yahoo.com/kb/account/generate-manage-rd-party-passwords-sln15241.html).
Use that generated password, not your normal Yahoo login password. Enter it only
in your local settings file.

```sh
cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
nano .env
```

Update the following, replacing placeholders with your **sending** account:

```dotenv
EMAIL_DRY_RUN=false
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USERNAME=your-address@yahoo.com
SMTP_PASSWORD=your-generated-app-password
SMTP_FROM=your-address@yahoo.com
SMTP_USE_TLS=true
SMTP_TIMEOUT_SECONDS=30
```

Leave the working Ollama settings in place. Save, then stop/remove the existing
container if it exists:

```sh
podman stop agent-01
podman rm agent-01
```

Create a new container, **without the dry-run override**:

```sh
podman run -it --name agent-01 --env-file .env \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

Ask it to send a test to an address you own. The preview must say **REAL EMAIL**.
Typing `y` now attempts real delivery. SMTP acceptance is not guaranteed inbox
delivery; check your inbox and spam folder. Do not assume the app saves a copy in
Yahoo's Sent folder: it uses SMTP only, not mailbox synchronization.

To go back to a guaranteed dry run, recreate the container with
`-e EMAIL_DRY_RUN=true` as in section 8. Editing `.env` alone does not change a
container that already exists.

## 12. Start Agent-02 and Agent-03 independently

Use another Terminal for each interactive agent. Start with dry-run enabled.

The copied project already has `config/agent-02.yaml` and `config/agent-03.yaml`.
When inspected, **both still declared `name: agent-01`**. Their filenames alone do
not change the identity. Edit them:

```sh
cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
nano config/agent-02.yaml
```

Change `name: agent-01` to `name: agent-02`, and change the prompt's
`You are Agent-01` to `You are Agent-02`. Keep the other required YAML fields.
You can adjust its role, description, and instructions. For Agent-03, do the same
in `config/agent-03.yaml` using `agent-03` / `Agent-03`.

If a future configuration is missing, copy a starting template once, before editing:

```sh
cp config/agent.yaml config/agent-04.yaml
```

Do not copy over configurations you already customized. YAML indentation matters;
use spaces, not tabs.

Start Agent-02:

```sh
podman run -it --name agent-02 --env-file .env \
  -e EMAIL_DRY_RUN=true \
  -v "$PWD/config/agent-02.yaml:/app/config/agent.yaml:ro" \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

In a separate Terminal, enter the application folder and start Agent-03:

```sh
cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform

podman run -it --name agent-03 --env-file .env \
  -e EMAIL_DRY_RUN=true \
  -v "$PWD/config/agent-03.yaml:/app/config/agent.yaml:ro" \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

Only the selected YAML file is mounted; `:ro` makes it read-only inside the
container. Keep that host file in place for future starts. The CLI reads YAML at
startup, so restart the agent to reload a mounted-file edit. A bind mount grants
access only to what you mount; do not substitute your home folder.

All these examples load the same `.env`, so they share its model and sending
account. To use separate settings, create a private `.env.agent-02` and replace
`--env-file .env` with `--env-file .env.agent-02`:

```sh
cp .env .env.agent-02
chmod 600 .env.agent-02
nano .env.agent-02
```

This duplicates credentials locally; keep it private. The application's ignore
rules exclude `.env.*`, except the public `.env.example`.

To disable email for an agent entirely, set this in its YAML:

```yaml
tools: []
```

Then restart it. To select a different installed model for one container, add
`-e OLLAMA_MODEL=MODEL_NAME` before the image name, replacing `MODEL_NAME` with the
exact name from `ollama list`. Environment model settings override YAML.

## 13. Updating code, settings, and images

| What you changed | What to do |
| --- | --- |
| Python code, dependencies, Containerfile | Rebuild image, then recreate container |
| Default `config/agent.yaml` copied into image | Rebuild image, then recreate container |
| A mounted Agent-02/03 YAML file | Stop and start the container to reread it |
| `.env` or environment flags | Recreate container; no image rebuild required |
| Container name or mounted file path | Recreate container |

For code updates, finish any active operation first. From the application folder:

```sh
podman build -t local-agent:stage1 -f Containerfile .
```

Only after the build succeeds:

```sh
podman stop agent-01
podman rm agent-01
```

Run the appropriate creation command from section 8 or 11 again. `podman start`
reuses the original container's image and environment; it does not upgrade it.
Rebuilding one image does not replace Agent-02 or Agent-03 automatically either.

## 14. Run automated tests and the offline demo

No real email is sent by the unit tests. They use mocked SMTP and HTTP calls.
A Python virtual environment is for local development; it is separate from Podman.
A copied `.venv` can contain paths to its old location, so recreate it after moving
a project if dependencies/scripts fail.

Check for a suitable Python installation:

```sh
python3.12 --version
```

If it is missing and you use Homebrew:

```sh
brew install python@3.12
```

Create the environment and run tests:

```sh
cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

For a broken/copied environment, this replacement command deletes and recreates
**only the contents of `.venv`**, not your code or `.env`:

```sh
python3.12 -m venv --clear .venv
.venv/bin/python -m pip install -r requirements.txt
```

Use an offline scripted-model demo to test preview, approval, and dry-run behavior:

```sh
.venv/bin/python -m tests.dry_run_demo
```

It prompts for approval and verifies that SMTP was never opened. It does not prove
live Ollama or Yahoo connectivity.

For optional host-only debugging:

```sh
OLLAMA_BASE_URL=http://localhost:11434 \
OLLAMA_MODEL=llama3.1:latest \
EMAIL_DRY_RUN=true \
.venv/bin/python -m src.main
```

This runs directly on the Mac, **not in a container**. Use the Podman commands for
normal operation. The direct command does not load your `.env` file.

## 15. One-task commands

For a temporary container that answers a single question and removes itself:

```sh
podman run --rm --env-file .env -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 --task 'What is the capital of France?'
```

For a one-task dry-run email with an interactive approval prompt:

```sh
podman run --rm -it --env-file .env -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1 \
  --task 'Send an email to person@example.com with subject "Test" and body "The report is ready."'
```

These temporary containers have no fixed `--name`, so they do not conflict with
`agent-01`. Do not pipe automatic approval into real-email runs.

## 16. Troubleshooting by exact symptom

### `.env: no such file or directory`

You are likely outside the application folder. Either `cd` there first, or use an
absolute path. This creation command works from any folder when `agent-01` does
not already exist:

```sh
podman run -it --name agent-01 \
  --env-file /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform/.env \
  -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

### `container name ... already in use`

Check `podman ps -a`. Use `podman start -ai agent-01` for the existing stopped
container, or stop/remove it before creating a replacement. Do not keep repeating
`podman run` with the same name.

### `cannot remove ... as it is running`

```sh
podman stop agent-01
podman rm agent-01
```

### `Cannot connect to Podman`

```sh
podman machine list
podman machine start
podman info
```

Start only if stopped. If `podman` itself is not found, check installation and
open a new Terminal after setup.

### Ollama unavailable from the container

First check the Mac:

```sh
curl --fail --show-error --max-time 10 http://localhost:11434/api/tags
```

Then use section 7's container `--check`. Confirm `.env` uses
`host.containers.internal`, not `localhost`. Check the machine and Mac firewall.

If only the container route fails and Ollama is listening only on loopback, quit
Ollama via its menu, change the Mac app's listener, and reopen it:

```sh
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
open -a Ollama
```

This is documented by the [Ollama FAQ](https://docs.ollama.com/faq). It can expose
the unauthenticated API to other network devices; restrict access with your
firewall and do not forward the port on your router. Do not change a working
listener unnecessarily. To undo it, run `launchctl unsetenv OLLAMA_HOST` and
quit/reopen Ollama.

### Model not installed

Run `ollama list`. Use the exact installed model name in `.env`, then recreate the
container. The sample YAML says `qwen3`; the tested override is `llama3.1:latest`.
Pull a model only if you actually want to download it.

### Email authentication failed

Check the sending Yahoo address, generated app password, `SMTP_FROM`, port 587,
and `SMTP_USE_TLS=true` in Nano. Recreate the container after edits. Do not print
or share your password for troubleshooting.

### Email says dry-run when you expected delivery

Check both `.env` and the original `podman run` command. The command-line
`-e EMAIL_DRY_RUN=true` overrides `.env`. Recreate without that override only when
you intend real delivery. `podman start` keeps the old environment.

### Ordinary questions trigger email proposals

Reject the proposal. Ensure the copied source includes the recipient-check fix,
rebuild from the new application folder, and recreate the container. Test with
`What is the capital of France?` before requesting email again.

### Agent-02 introduces itself as Agent-01

Edit both `name:` and the self-name in the YAML system prompt. Check that your
run command mounts the intended YAML. The Podman container name and agent identity
are separate settings.

### Maximum iterations or uncertain SMTP delivery

The loop is intentionally bounded by `MAX_AGENT_ITERATIONS`. A stopped task does
not undo an email already accepted by SMTP. Inspect the visible tool result and
check the recipient/provider before retrying; avoid sending duplicates.

## 17. Git and the Codex project boundary

Open this folder as the Codex project:

```text
/Users/mac14/Developer/LocalAgentPlatform
```

The old task was attached to the original `.codex/.chatgpt-projects/...` folder,
which inherited `/Users/mac14/.git`. That is why unrelated files appeared. Sidebar
placement alone does not change a task's working directory. Use a task created in
the new project, such as the verified `Clarify where to continue` task.

Verify the repository boundary:

```sh
git -C /Users/mac14/Developer/LocalAgentPlatform rev-parse --show-toplevel
```

Expected output: `/Users/mac14/Developer/LocalAgentPlatform`.
Do not reinitialize the repository; it already exists.

Inspect changes without changing files:

```sh
cd /Users/mac14/Developer/LocalAgentPlatform
git status --short
git diff --stat
git diff --cached --stat
```

`git diff` shows unstaged tracked edits; `--cached` shows staged changes. Staging
means selecting files for your next local commit. A commit does not upload files.

Check that your private settings are ignored and not tracked:

```sh
git check-ignore local-agent-platform/.env
git ls-files -- local-agent-platform/.env
```

The first should print the path; the second should print nothing. An ignore rule
does not untrack a file that was already staged. Do not commit credentials.

When ready, stage specific files rather than blindly adding everything:

```sh
git add CHEATSHEET.md local-agent-platform/README.md
git diff --cached --stat
git status --short
```

Review **all** staged files before a commit, including anything staged previously.
Only when the staged set is what you intend:

```sh
git commit -m "Document local agent setup and usage"
```

For unrelated-file warnings, confirm the task folder and repository boundary.
Do not use `git clean`, delete the home-folder `.git`, or run bulk cleanup to hide
those warnings. They can affect other work.

## 18. Compact daily reference

| Goal | Command |
| --- | --- |
| Open application folder | `cd /Users/mac14/Developer/LocalAgentPlatform/local-agent-platform` |
| Start Ollama app | `open -a Ollama` |
| Check machine | `podman machine list` |
| Start stopped machine | `podman machine start` |
| List all agents | `podman ps -a` |
| Resume stopped Agent-01 | `podman start -ai agent-01` |
| Attach to running Agent-01 | `podman attach agent-01` |
| Detach without stopping | Ctrl+P, then Ctrl+Q |
| Exit at task prompt | `exit` |
| Reject an email | Enter or `n` at approval prompt |
| Watch logs | `podman logs -f agent-01` |
| Watch resource usage | `podman stats` |
| Stop Agent-01 | `podman stop agent-01` |
| Remove stopped Agent-01 | `podman rm agent-01` |
| Rebuild image from app folder | `podman build -t local-agent:stage1 -f Containerfile .` |
| Edit settings from app folder | `nano .env` |

**Remember:** `run` creates; `start` resumes. Email mode comes from the container's
creation-time environment. Source changes require rebuilding and recreating. Your
Mac runs Ollama; Podman runs the agent.


## 19. Read public webpages with your agents

This extension reads public URLs you supply. It cannot search the web, click,
log in, run JavaScript, or read PDFs. The default configurations enable
`read_webpage`. It does not require an API key.

At the agent task prompt:

```text
Read https://example.com/ and summarize the page. Include its source URL.
```

Only URLs in your current task are eligible. The tool will not follow links chosen
from page text; redirects are limited and rechecked. Private network URLs, including
`localhost` and `host.containers.internal`, are blocked by the webpage tool. This
does not affect the Ollama client's separate connection to your Mac.

Webpage reads do not require an approval prompt. Email still does. `EMAIL_DRY_RUN`
does not disable webpage network requests. Treat summaries as model-generated
interpretations and check their cited source.

After this update, recreate each agent to use the rebuilt image. For Agent-01,
finish pending operations, then run from the application folder:

```sh
podman stop agent-01
podman rm agent-01
podman run -it --name agent-01 --env-file .env \
  -e EMAIL_DRY_RUN=true \
  --read-only --cap-drop=all --security-opt=no-new-privileges \
  local-agent:stage1
```

This example forces email dry-run. Omit that override only when you intend the
email mode specified in `.env`. For other agents use the matching container name
and YAML mount from section 12 (substitute `04` for Agent-04). Existing containers
were not stopped or recreated automatically during development.

To disable webpage reading for an agent, remove `read_webpage` from its YAML tools
list. For mounted YAML, restart the agent; for the default YAML copied into the
image, rebuild and recreate. Large/compressed/dynamic pages can return a clear
error rather than content. See the README's webpage section for precise limits.
