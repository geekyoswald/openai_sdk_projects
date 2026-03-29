# Local setup & run

Use this guide on **macOS** or a **dev laptop** to configure `.env`, create a **venv**, and execute the pipeline. For architecture and agent diagrams, see **[README.md](README.md)**.

---

## Prerequisites

- **Python 3** available as `python3` (e.g. macOS: Xcode CLI tools or Homebrew Python).
- Shell: **bash** or **zsh**.

---

## 1. Environment file

From the `complai_sdr_email` directory:

```bash
cp .env.example .env
```

Edit **`.env`** and set at least:

| Variable | Required for | Notes |
|----------|----------------|------|
| `OPENAI_API_KEY` | Yes | Orchestration, parser, reviewer, email formatting agents (`gpt-4o-mini`). |
| `DEEPSEEK_API_KEY` | Yes | Three drafting sub-agents (`deepseek-chat`). |
| `SENDGRID_API_KEY` | Yes | Outbound mail API. |
| `SENDGRID_FROM_EMAIL` | Yes | Verified sender in SendGrid. |
| `SENDGRID_TO_EMAIL` | Fallback | Used only if you do not pass a recipient in the NL message; parsed email usually overrides. |
| `WORKFLOW_TRACE_NAME` | No | Custom trace label (default `Automated SDR`). |
| `TELEGRAM_BOT_TOKEN` | No | Live step updates to Telegram. |
| `TELEGRAM_CHAT_ID` | No | Target chat for bot messages. |
| `TELEGRAM_STEP_DELAY_SEC` | No | Delay between steps (e.g. `0.5` for demos). Default `0`. |

---

## 2. One-command run (recommended)

```bash
chmod +x setup_and_run_local.sh
./setup_and_run_local.sh
```

This creates **`.venv`**, installs **`requirements.txt`**, and runs **`python run.py`**.

**Shortcut:** `./setup_and_run.sh` does the same as `setup_and_run_local.sh`.

### If venv creation fails

- **macOS:** install tools: `xcode-select --install`, or use Homebrew Python and run  
  `PYTHON=/opt/homebrew/bin/python3 ./setup_and_run_local.sh` (adjust path).
- Remove a broken env and retry: `rm -rf .venv` then run the script again.

---

## 3. Manual setup (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python run.py
```

---

## 4. Customize the demo message

Edit **`USER_MESSAGE`** in **`run.py`**. Include a valid **`someone@domain`** address in natural language so the input parser can extract **`recipient_email`**.

---

## 5. Telegram webhook (optional)

After `pip install -r requirements.txt`, from **`complai_sdr_email/`**:

```bash
uvicorn webhook_app:app --host 127.0.0.1 --port 8000
```

Point your bot’s webhook at your public URL (e.g. via **ngrok**):  
`https://<host>/telegram-webhook`

If Telegram env vars are missing or invalid, the pipeline still runs; only notifications are skipped.

---

## 6. EC2 / Ubuntu server

For **`apt`**-based **`python3-venv`** install and the same `run.py` flow, use **`./setup_and_run_aws.sh`**. Full project documentation: **[README.md](README.md)**.
