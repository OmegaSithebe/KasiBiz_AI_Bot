# KasiBiz

An AI business assistant for South African spaza and tuck shop owners.

Ring up a sale, watch your stock, check whether your prices are making money,
write a WhatsApp advert, and get straight answers about CIPC and SARS - by
typing in ordinary words, in your own language.

---

## What it does

| Specialist | What the owner asks | Where the answer comes from |
|---|---|---|
| **Sales Agent** | *"2 White Bread and 1 Milk 1L"*, *"they paid R50"* | Your stock, your prices, Python arithmetic |
| **Stock Agent** | *"What is low in stock?"* | The products table |
| **Pricing Helper** | *"What should I charge for bread?"* | Cost and selling prices, markup and margin |
| **Marketing Agent** | *"Write a WhatsApp advert"* | A real product, a real offer, real stock levels |
| **Insights Agent** | *"What is selling well this week?"* | Recorded sales only - never estimates |
| **Business Advisor** | *"How do I register with CIPC?"* | Indexed guides, with the source cited |

One assistant, one chat box. The owner never chooses a specialist - a router
works that out from what they typed.

### Where to go next

| If you want to... | Read |
|---|---|
| **Run it on your own machine, step by step** | [docs/LOCAL_SETUP_AND_RUN_GUIDE.md](docs/LOCAL_SETUP_AND_RUN_GUIDE.md) |
| **Understand how it works, in plain language** | [docs/KASIBIZ_PROJECT_BASELINE.md](docs/KASIBIZ_PROJECT_BASELINE.md) |
| **Present or record a demonstration** | [docs/FINAL_DEMO_GUIDE.md](docs/FINAL_DEMO_GUIDE.md) |

The quick version is below.

### Five rules the whole system is built on

1. **Python does the arithmetic. The AI does the language.** No total, no change
   and no profit figure is ever produced by a language model.
2. **Money is counted in whole cents**, like a bank. Never a float.
3. **Everything works when the AI is off.** Switch it off and you get the same
   figures in plainer words. The test suite runs entirely without it.
4. **Refusing is a feature.** KasiBiz will not advertise a product that is out of
   stock, and will not name a best seller in a shop with no recorded sales.
5. **Every answer is auditable.** The facts are kept beside the words, sources
   are cited, and every figure is checked against the facts before it is shown.

---

## Getting started

### 1. Clone and enter the project

```bash
git clone <your-repository-url>
cd KasiBiz_AI_Bot
```

### 2. Create and activate a virtual environment

Python **3.12** is recommended. Newer versions do not yet have wheels for all
the pinned packages.

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. Install the dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Configure your environment

```bash
cp .env.example .env
```

On Windows: `copy .env.example .env`

Then open `.env` and paste in your OpenAI key.

| Variable | Secret? | What it is | Default |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | From <https://platform.openai.com/api-keys> | none |
| `MODEL_NAME` | No | Which model to use for wording | `gpt-4o-mini` |
| `DATABASE_URL` | No | Where the SQLite file lives | `sqlite:///kasibiz.db` |
| `CHROMA_DB_PATH` | No | Where the knowledge base lives | `chroma_db` |
| `SHOP_NAME` | No | The name adverts are signed with | `KasiBiz Spaza` |
| `KASIBIZ_LOG_LEVEL` | No | `DEBUG` when hunting a problem | `INFO` |
| `KASIBIZ_LOG_FILE` | No | Blank logs to the console only | blank |

**Only `OPENAI_API_KEY` is a secret.** SQLite and ChromaDB run locally and need
no key, no password and no account - they are just folder paths, created
automatically the first time they are used.

`.env` is git-ignored and must never be committed. `.env.example` holds
placeholders only.

### 5. Load the demonstration data

```bash
python scripts/seed_demo.py
```

This creates 20 spaza products and about a week of invented sales, so the
Insights Agent has something real to report. It prints a notice every time it
runs, because this is **demonstration data, not a real shop's books**.

```bash
python scripts/seed_demo.py --reset      # wipe everything and rebuild
python scripts/seed_demo.py --no-sales   # products only, empty sales history
python scripts/seed_demo.py --days 14    # a fortnight of trading instead of a week
```

### 6. Build the knowledge base

```bash
python scripts/rag_ingest.py --local     # free, no API key needed
python scripts/rag_ingest.py             # better search, uses OpenAI embeddings
```

### 7. Run it

```bash
streamlit run streamlit_app/app.py
```

Then open <http://localhost:8501>.

Prefer the terminal?

```bash
python scripts/kasibiz.py --chat         # free and offline
python scripts/kasibiz.py --chat --ai    # with AI wording
```

### On macOS or Linux, steps 2 to 6 in one command

```bash
bash setup.sh
```

---

## Checking that it works

```bash
python scripts/health_check.py           # sixteen checks, about ten seconds
python scripts/health_check.py --ai      # also makes one live OpenAI call
```

Run this before any demonstration. It verifies the configuration, the database,
the sales tables, the knowledge base, all six specialists, the router, the six
languages, conversation memory, the figure checker, a complete till journey, and
that an empty shop refuses to invent an insight.

### The tests

```bash
python -m pytest tests/ -q                       # everything
python -m pytest tests/ -q -k "not streamlit"    # skip the slower UI tests
python -m pytest tests/test_sales_service.py -v  # one file
```

The whole suite runs **without the AI and without internet**, so it is free and
fast. Nothing in it calls OpenAI except `tests/test_llm_connection.py`, which
skips itself when no key is present.

### The demonstration journey

```bash
python scripts/demo_journey.py           # thirteen steps, all six specialists
python scripts/demo_journey.py --pause   # stop between steps, for recording
python scripts/demo_journey.py --ai      # same figures, AI wording
```

---

## Starting the demo data over

```bash
python scripts/seed_demo.py --reset
```

To wipe absolutely everything and begin from nothing:

```bash
# Windows:  del kasibiz.db  &&  rmdir /s /q chroma_db
rm kasibiz.db && rm -rf chroma_db
python scripts/seed_demo.py
python scripts/rag_ingest.py --local
```

---

## How it is put together

```
            the owner types one thing
                       |
                 COORDINATOR
        routes it, remembers the subject,
            detects the language
                       |
   +-------+------+----+----+---------+----------+
   |       |      |         |         |          |
 Stock   Sales  Pricing  Marketing  Insights  Advisor
   |       |      |         |         |          |
   +-------+------+---------+---------+          |
                       |                         |
              SQLite (whole cents)      ChromaDB (documents)
```

| Folder | What lives there |
|---|---|
| `app/agents/` | The six specialists, the router and the vocabulary |
| `app/services/` | The business rules and all the arithmetic |
| `app/database/` | The schema and every read and write |
| `app/rag/` | Document loading, chunking and retrieval |
| `app/utils/` | Config, the OpenAI client, language, memory, figure checking, logging |
| `streamlit_app/` | The screen |
| `scripts/` | Seeding, health check, demos, ingestion |
| `tests/` | The test suite |
| `docs/` | The setup, architecture and demonstration guides |
| `rag/documents/` | The guides the Business Advisor quotes from |

### The three files that matter most

- **`app/agents/intents.py`** is the single source of truth for what words mean.
  Both the router (*which specialist*) and each specialist (*what to do*) are
  derived from one table, so a phrase is written once.
- **`app/services/calculation_service.py`** is the only place money arithmetic
  happens. Line totals, basket totals, change and profit all live here.
- **`app/database/sqlite_db.py::record_sale`** writes the sale and reduces the
  stock in a single transaction. They succeed together or neither happens.

### The database

| Table | What it holds |
|---|---|
| `products` | Name, cost, selling price, quantity, alert level. Prices in whole cents. |
| `sales` | One row per completed sale: total, paid, change, cost, profit, timestamp. |
| `sale_items` | One row per line. The price is **copied in**, so repricing tomorrow never rewrites what happened today. |

`sales.reference` is `UNIQUE`. That single constraint is what makes a double-tap
on Confirm harmless.

---

## Known limitations

- **The isiZulu, isiXhosa, Afrikaans, Sesotho and Setswana phrases have not been
  reviewed by native speakers.** They were written from reference material and
  need checking before this goes in front of real shop owners.
- **Speech input is not implemented.** It is in the project plan but no part of
  it is built, so there is deliberately no half-working microphone button on
  screen.
- **One shop, one till.** There is no login, no multi-user support and no concept
  of separate shops in one database.
- **Insights cover units, money and gross profit only.** Gross profit counts what
  you paid for the goods - not rent, transport, electricity or your own time.
- **SQLite means one machine.** Hosting this for several users means moving to
  PostgreSQL. `DATABASE_URL` exists so that change stays small.
- **The knowledge base is small** - 16 documents. It answers common CIPC and SARS
  questions and declines anything outside them.
- **Hosting is not set up.** Running this publicly needs a spend cap on the
  OpenAI key and a passcode on the app.
- **Guidance is educational.** KasiBiz is not a legal, tax or financial adviser,
  and says so on every screen.

---

## What it costs to run

Almost nothing. The database, the router, language detection, memory, every
calculation and the entire test suite run without touching OpenAI. The AI is
used only to reword answers, and `gpt-4o-mini` costs fractions of a cent per
reply. Building the knowledge base with OpenAI embeddings costs under one US
cent.

Turn the AI off with the toggle in the sidebar and KasiBiz still works - same
figures, plainer words.
