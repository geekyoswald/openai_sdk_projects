# ComplAI SDR

1. Copy `.env.example` to `.env` and fill in the keys.
2. Run venv + install + `run.py` in one step:

   ```bash
   chmod +x setup_and_run.sh
   ./setup_and_run.sh
   ```

   Or manually: `python3 -m venv .venv` → `source .venv/bin/activate` → `pip install -r requirements.txt` → `python run.py`.

The email brief is hardcoded in `run.py` (`BRIEF`).

On AWS (e.g. EC2), install Python 3 if needed, clone the repo, add `.env`, then run `./setup_and_run.sh` from this folder.
