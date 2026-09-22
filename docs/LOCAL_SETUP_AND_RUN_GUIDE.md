# Running KasiBiz on your own machine

Written for Windows PowerShell, with macOS and Linux equivalents at the end.
Every command below uses this repository's real filenames.

---

## 1. Software you need

| What | Version | Where |
|---|---|---|
| Python | **3.12** | <https://www.python.org/downloads/release/python-3120/> |
| Git | any recent | <https://git-scm.com/downloads> |
| A browser | any | Chrome, Edge or Firefox |
| An OpenAI key | optional | <https://platform.openai.com/api-keys> |

**Python 3.12 specifically.** Some pinned packages do not yet publish wheels for
3.13 or 3.14, and the install fails partway through. Check what you have:

```powershell
py --list
```

If `3.12` is not in that list, install it before going further. During the
Windows installer, tick **"Add python.exe to PATH"**.

> **The OpenAI key is optional.** Without it KasiBiz still runs: every
> calculation, the router, all six languages, the whole test suite and the demo
> work offline. The key only makes the wording more natural.

---

## 2. Get the project

If you already have the folder, skip to step 3.

```powershell
git clone https://github.com/OmegaSithebe/KasiBiz_AI_Bot.git
```

## 3. Go into the project folder

```powershell
cd KasiBiz_AI_Bot
```

Check you are in the right place - you should see `requirements.txt`:

```powershell
Get-ChildItem requirements.txt, streamlit_app\app.py
```

If that errors, you are in the wrong folder.

## 4. Create the virtual environment

```powershell
py -3.12 -m venv .venv
```

This makes a `.venv` folder. It is git-ignored, so it never gets committed.

## 5. Activate it

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt now starts with `(.venv)`. **Every command after this needs that
prefix showing.**

If PowerShell refuses with *"running scripts is disabled on this system"*:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

That only affects the current window.

## 6. Upgrade pip

```powershell
python -m pip install --upgrade pip
```

## 7. Install the dependencies

```powershell
python -m pip install -r requirements.txt
```

Takes a few minutes. ChromaDB and Streamlit are the big ones.

## 8. Create your .env file

```powershell
Copy-Item .env.example .env
```

## 9. Fill in the variables

Open `.env` in any editor:

```powershell
notepad .env
```

| Variable | Must you change it? | What it is |
|---|---|---|
| `OPENAI_API_KEY` | **Only if you want AI wording** | Your key from platform.openai.com |
| `MODEL_NAME` | No | `gpt-4o-mini` |
| `DATABASE_URL` | No | `sqlite:///kasibiz.db` |
| `CHROMA_DB_PATH` | No | `chroma_db` |
| `SHOP_NAME` | Optional | The name on adverts and receipts |
| `KASIBIZ_LOG_LEVEL` | No | `INFO`. Use `DEBUG` when hunting a problem |
| `KASIBIZ_LOG_FILE` | No | Leave blank for console only |

**Only `OPENAI_API_KEY` is a secret.** The database and the knowledge base are
just folder paths on your own machine - no account, no password, no key. They
are created automatically the first time they are used.

`.env` is git-ignored. Never commit it.

## 10. Initialise the database

There is no separate migration step. The tables are created automatically the
first time anything opens the database, which the seed script in step 11 does.

To do it explicitly without adding data:

```powershell
python -c "from app.database.sqlite_db import get_db; get_db(); print('database ready')"
```

That creates `kasibiz.db` in the project folder.

## 11. Load the knowledge base (RAG)

```powershell
python scripts/rag_ingest.py --local
```

`--local` uses a free built-in text matcher and needs no API key. If you have a
key and want better search, leave the flag off:

```powershell
python scripts/rag_ingest.py
```

Useful extras:

```powershell
python scripts/rag_ingest.py --status              # what is indexed
python scripts/rag_ingest.py --search "CIPC"       # try a search
python scripts/rag_ingest.py --reset               # empty the index
```

Expect roughly **26 passages from 16 documents**.

## 12. Load the demonstration data

```powershell
python scripts/seed_demo.py
```

This creates 20 spaza products and about a week of invented sales, so the
Insights screen has something real to show. It prints a notice every time,
because **this is demonstration data, not a real shop's books**.

```powershell
python scripts/seed_demo.py --reset      # wipe and rebuild
python scripts/seed_demo.py --no-sales   # products only
python scripts/seed_demo.py --days 14    # a fortnight of trading
```

## 13. Run the health check

```powershell
python scripts/health_check.py
```

Eighteen checks. You want **ALL SYSTEMS READY**. Run this before any demo.

To also make one real call to OpenAI and prove the key works:

```powershell
python scripts/health_check.py --ai
```

## 14. Run the unit tests

```powershell
python -m pytest tests/test_calculation_service.py tests/test_sales_service.py tests/test_intents.py tests/test_conversation.py -q
```

## 15. Run the integration tests

```powershell
python -m pytest tests/test_integration.py -q
```

The whole suite at once:

```powershell
python -m pytest tests/ -q
```

Skip the slower browser-less UI tests:

```powershell
python -m pytest tests/ -q -k "not streamlit"
```

## 16. Run the journey demo

```powershell
python scripts/demo_journey.py
```

Thirteen steps through all six specialists, in the terminal.

```powershell
python scripts/demo_journey.py --pause   # stop between steps, good for recording
python scripts/demo_journey.py --ai      # same figures, AI wording
```

There is also a plain chat version:

```powershell
python scripts/kasibiz.py --chat
python scripts/kasibiz.py --chat --ai
python scripts/kasibiz.py --routing "what should I charge for bread?"
```

## 17. Start Streamlit

```powershell
streamlit run streamlit_app/app.py
```

If `streamlit` is not recognised, use the module form - this always works:

```powershell
python -m streamlit run streamlit_app/app.py
```

## 18. Open it

**<http://localhost:8501>**

It usually opens by itself. If port 8501 is busy:

```powershell
python -m streamlit run streamlit_app/app.py --server.port 8502
```

## 19. Stop Streamlit

Click the terminal and press **Ctrl + C**.

If it will not let go:

```powershell
Get-Process -Name python | Where-Object { $_.Path -like "*\.venv\*" } | Stop-Process
```

## 20. Reset the demo data safely

Most of the time, this is all you need:

```powershell
python scripts/seed_demo.py --reset
```

To start from absolutely nothing:

```powershell
Remove-Item kasibiz.db -ErrorAction SilentlyContinue
Remove-Item chroma_db -Recurse -Force -ErrorAction SilentlyContinue
python scripts/seed_demo.py
python scripts/rag_ingest.py --local
```

> This deletes your local shop database. It is demonstration data, so nothing of
> value is lost - but do not run it on a machine holding anything real.

---

## 21. When something goes wrong

### `python` is not recognised
The virtual environment is not active. Look for `(.venv)` in your prompt and
re-run step 5.

### `running scripts is disabled on this system`
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### `ModuleNotFoundError: No module named 'app'`
You are not in the project folder. `cd` into `KasiBiz_AI_Bot` - the one that
contains `requirements.txt` - and try again.

### `ModuleNotFoundError: No module named 'streamlit'`
Dependencies are not installed in the active environment. Repeat steps 5 and 7.

### `OPENAI_API_KEY is not set`
Only affects AI wording. Either put a key in `.env`, or turn **Use AI wording**
off in the sidebar and carry on.

### `Incorrect API key provided` (HTTP 401)
The key itself is wrong or revoked. **401 means invalid; 429 means out of
credit.** Make a new key in your default project.

### The Insights page says there are no sales
There genuinely are none. KasiBiz will not estimate. Run:
```powershell
python scripts/seed_demo.py
```

### The Business Advisor cannot answer anything
The knowledge base is empty:
```powershell
python scripts/rag_ingest.py --local
python scripts/rag_ingest.py --status
```

### `Port 8501 is already in use`
An older Streamlit is still running. Use `--server.port 8502`, or stop it as in
step 19.

### A build fails while installing
Almost always the wrong Python. Confirm:
```powershell
python --version
```
It must say **3.12.x**. If not, delete `.venv` and redo step 4 with `py -3.12`.

### Something failed and I want to see why
```powershell
$env:KASIBIZ_LOG_LEVEL = "DEBUG"
python scripts/health_check.py
```

---

## macOS and Linux

Same steps, three different commands:

```bash
# Step 4 - create
python3.12 -m venv .venv

# Step 5 - activate
source .venv/bin/activate

# Step 8 - copy the environment file
cp .env.example .env
```

Everything else is identical. Resetting from scratch:

```bash
rm -f kasibiz.db
rm -rf chroma_db
python scripts/seed_demo.py
python scripts/rag_ingest.py --local
```

There is also a helper that does steps 4 to 12 in one go on macOS and Linux:

```bash
bash setup.sh
```

---

## The short version

Once it is set up, this is the daily routine:

```powershell
cd KasiBiz_AI_Bot
.\.venv\Scripts\Activate.ps1
python scripts/health_check.py
streamlit run streamlit_app/app.py
```
