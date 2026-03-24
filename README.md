# ComplAI SDR

1. Copy `.env.example` to `.env` and fill in the keys.
2. Run venv + install + `run.py` in one step:

   ```bash
   chmod +x setup_and_run.sh
   ./setup_and_run.sh
   ```

   Or manually: `python3 -m venv .venv` → `source .venv/bin/activate` → `pip install -r requirements.txt` → `python run.py`.

The email brief is hardcoded in `run.py` (`BRIEF`).

### Ubuntu / Debian (including EC2)

Install the venv module once (needed for `python3 -m venv`):

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
```

If the error says to install `python3.12-venv`, use that package name instead (match your `python3 --version`). If a previous run left a broken `.venv`, remove it: `rm -rf .venv`, then `./setup_and_run.sh` again.
