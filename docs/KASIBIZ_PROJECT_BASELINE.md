# KasiBiz explained

Written for someone still learning software and AI engineering. It assumes you
can read a little Python but not that you know what RAG, a vector store or an
agent router is.

---

## 1. What KasiBiz does

A spaza shop owner runs their whole business from memory and a notebook. They
know roughly what sells, roughly what they make on a loaf of bread, and they
find out they are out of paraffin when a customer asks for it.

KasiBiz is an assistant they talk to in ordinary words, in their own language,
that answers from their own records:

- rings up a sale and works out the customer's change
- tells them what is running out
- tells them whether a price is actually making money
- writes a WhatsApp advert for a product
- tells them what sold well this week and what did not
- answers questions about CIPC and SARS

They type one thing into one box. They never choose which part of the system
should answer.

## 2. The main user journeys

| Journey | What the owner types | What happens |
|---|---|---|
| **Sell something** | `2 White Bread`, then `they paid R50` | A basket is built, the change is worked out, and nothing is saved until they say **yes** |
| **Check stock** | `What is low in stock?` | The products table is read and sorted by urgency |
| **Check a price** | `Am I making enough profit on White Bread?` | Cost and selling price are compared, markup and margin both shown |
| **Advertise** | `Write a WhatsApp advert for Simba Chips 36g` | An advert built from the real price and the real stock level - or a refusal |
| **See performance** | `What is selling well this week?` | Counted from recorded sales, or a clear "I cannot tell you that yet" |
| **Get guidance** | `How do I register with CIPC?` | Retrieved from indexed documents, with the source named |

## 3. What the frontend is responsible for

The frontend is `streamlit_app/app.py`. Streamlit is a Python library that turns
a script into a web page - there is no HTML, no JavaScript and no separate
server to run.

The frontend's job is only:

- showing things (products, baskets, totals, answers)
- collecting input (dropdowns, number boxes, the chat box)
- **asking "are you sure?" before anything is written**
- showing friendly messages instead of errors

It has four pages: **Assistant** (chat), **New Sale**, **Stock** and
**Insights**.

**The frontend contains no business rules.** It never works out a total, never
decides whether stock is low, never calculates profit. If you deleted it
tomorrow, everything would still work from the terminal - which is exactly what
`scripts/kasibiz.py` does.

## 4. What the backend is responsible for

Everything else. It splits into three layers, and the split matters:

| Layer | Folder | Job |
|---|---|---|
| **Data** | `app/database/` | Reading and writing SQLite. Knows nothing about agents. |
| **Services** | `app/services/` | The business rules and **all the arithmetic**. Plain Python, no AI. |
| **Agents** | `app/agents/` | Understanding what was asked, and putting the answer into words. |

The rule that holds it together:

> **A service works out *what is true*. An agent decides *how to say it*.**

That is why every service can be tested without an API key, and why the whole
test suite runs offline.

## 5. How Streamlit talks to the backend

It imports it. That is the whole answer.

```python
from app.agents.coordinator import KasiBizCoordinator

response = assistant().ask("What is low in stock?")
st.markdown(response.answer)
```

There is no REST API, no HTTP call and no separate backend process. Streamlit
runs the Python, the Python calls the services, the services read SQLite.

One Streamlit habit worth understanding: **the whole script re-runs from the top
every time you click anything.** That is why the agents are built inside a
`@st.cache_resource` function - so they are created once per session and not
rebuilt on every click - and why the open basket is held in the service object
rather than in a local variable.

## 6. How the router chooses an agent

This is the part people find surprising: **most of the routing uses no AI at
all.**

`app/agents/intents.py` holds one table of phrases. Each phrase says which
specialist it belongs to and how much it is worth:

```python
_p("what is low",        S, StockIntent.LOW_STOCK,   4)   # strong
_p("stock",              S, None,                    2)   # weak
_p("customer paid",      SA, SalesIntent.PAYMENT,    4)
```

A question is scored against the table. Multi-word phrases score 4 because they
are unlikely to appear by accident; single common words score 2. Highest total
wins.

Confidence is two things multiplied together:

```
confidence = (how much evidence)  x  (how dominant that route was)
```

Both halves are needed. An early version used dominance alone, and a single
stray keyword scored 100% simply because nothing else matched.

Three things happen before the score is trusted:

1. **Memory completes the question.** "how much is it?" becomes "how much is
   White Bread?" *before* routing, so the router always sees a whole question.
2. **An open basket changes the meaning of short messages.** "yes" means nothing
   on its own; it means a great deal when a sale is waiting. Changing the subject
   outright still wins, but it needs strong evidence, not a stray keyword.
3. **A sale is recognised by its shape.** "2 White Bread" contains no keyword at
   all. A number in front of a known product name is treated as a sale.

Only when the rules are genuinely torn does it ask the language model - and only
for one word.

### The one-table rule

Both layers of intent detection are derived from that same table:

```
VOCABULARY  ->  router_patterns()      WHICH specialist answers
            ->  agent_keywords(route)  WHAT that specialist does
```

Before this existed, the same phrase had to be typed into two different files.
Forgetting the second copy did not raise an error - it quietly sent the question
to the wrong specialist. That cost three separate bugs.

## 7. What each agent does

| Agent | File | What it is for |
|---|---|---|
| **Coordinator** | `coordinator.py` | Not a specialist. Resolves, routes, dispatches, records. |
| **Stock Agent** | `inventory_agent.py` | What is low, what to reorder, do I have enough |
| **Sales Agent** | `sales_agent.py` | The till: basket, payment, change, confirmation |
| **Pricing Helper** | `pricing_agent.py` | What to charge, am I making money, what if I charged X |
| **Marketing Agent** | `marketing_agent.py` | WhatsApp, social and poster copy - and refusals |
| **Insights Agent** | `insight_agent.py` | Best sellers, slow movers, takings, gross profit |
| **Business Advisor** | `business_advisor_agent.py` | CIPC, SARS, budgeting, from indexed documents |

Every agent has the same three steps:

```
1. UNDERSTAND   what is being asked, and about which product
2. GATHER       the facts, from a service, in plain Python
3. SAY IT       either the fallback sentence, or the AI rewording those facts
```

Step 2 never involves the AI. Step 3 is optional.

## 8. How calculations work

`app/services/calculation_service.py` is the only file that does arithmetic with
money:

```python
line_total       = unit_price x quantity
basket_total     = sum of the line totals
change           = amount_paid - basket_total     # refuses if negative
profit_per_item  = selling_price - cost_price
line_profit      = profit_per_item x quantity
```

**Money is stored and calculated as whole cents in an `int`.** R15.50 is `1550`.

The reason is that decimals lose money. In floating point, ten lots of ten cents
comes to `0.9999999999999999`. In cents it is `100`, every time. Rand is only
produced at the very edge, for display, by `to_rand`.

### The check that catches a lying answer

`app/utils/answer_check.py` compares the numbers in the final sentence against
the facts the agent was given. If a figure appears in the answer that was not in
the facts, it is flagged as invented.

Note the direction: it tests for **invented** figures, not missing ones. A
shorter answer is fine. A number with no source is a hallucination.

## 9. How inventory is stored

One `products` table in SQLite:

| Column | Note |
|---|---|
| `name` | Unique, case-insensitive, so "Bread" and "bread" cannot both exist |
| `cost_price_cents`, `selling_price_cents` | Integers. Always. |
| `quantity` | `CHECK (quantity >= 0)` - the database refuses to go negative |
| `low_stock_threshold` | When to start warning |

There is also a `low_stock_products` view, so "what is low" is one query rather
than logic scattered around the app.

## 10. How sales are stored

Two tables, written together:

- **`sales`** - one row per completed sale: total, paid, change, cost, profit
- **`sale_items`** - one row per line

Two decisions worth understanding:

**The price is copied into `sale_items`, not looked up later.** A sale is a
historical record. If you reprice bread tomorrow, last week's profit must not
silently change.

**`sales.reference` is `UNIQUE`.** Every basket carries its own id. If the owner
taps Confirm twice, the second insert hits that constraint and fails cleanly
instead of recording a second sale.

### The transaction

```sql
BEGIN IMMEDIATE
  INSERT INTO sales ...
  INSERT INTO sale_items ...
  UPDATE products SET quantity = quantity - ?
   WHERE id = ? AND quantity >= ?      <-- the guard
COMMIT
```

That `WHERE` clause is doing the real work. It is not a check made earlier and
trusted afterwards - the database itself refuses the update if the stock is not
there, and the entire sale rolls back. A sale that fails halfway leaves the
shelf exactly as it was.

## 11. How insights are produced

`app/services/analytics_service.py` reads the sales tables for a period, groups
the lines by product, and adds them up. No model is involved.

The important behaviour is the refusal. Every insight states:

- **the period** it covers
- **how many recorded sales** it is based on
- **the result**
- **one thing to do about it**

If there are no sales, it says so. If a ranking rests on one or two sales, it
says the order is early days rather than a trend.

> A shop owner told the wrong thing about their best seller will order the wrong
> stock with real money. Silence is the safe answer.

## 12. How RAG works

RAG means **Retrieval-Augmented Generation**. In plain terms: *look it up first,
then answer from what you found.*

Without it, asking a language model about CIPC gets you a confident answer
assembled from whatever it absorbed during training - possibly out of date,
possibly about a different country, with no way to check.

With it:

```
1. SPLIT     the guides in rag/documents/ into ~800-character passages
2. EMBED     turn each passage into a list of numbers that represents its meaning
3. STORE     keep those numbers in ChromaDB
4. RETRIEVE  embed the question the same way, find the 4 closest passages
5. ANSWER    hand ONLY those passages to the model and say "answer from this"
```

Two rules make it safe to show a real shop owner:

- **If nothing relevant is found, it says so** rather than answering anyway.
- **Every answer names its source**, so the owner can go and read it.

There is a relevance floor (`MIN_RELEVANCE = 0.25`) below which a passage is
treated as not really matching. That number was **measured against real
questions**, not guessed.

## 13. How ChromaDB is used

ChromaDB is the vector database - it stores those lists of numbers and answers
"which passages are closest to this one?".

It runs **embedded**: a folder on your disk (`chroma_db/`), created
automatically. **No server, no account, no API key.** `CHROMA_DB_PATH` is just a
path.

There are two ways to make the numbers:

| Embedder | Needs a key? | Used for |
|---|---|---|
| `OpenAIEmbedder` | Yes | Better search quality |
| `LocalEmbedder` | No | Tests and offline use |

That is why the test suite is free: it uses the local one.

## 14. How the language model is used

In exactly three places:

1. **Rewording facts** that Python already worked out
2. **Writing advert copy** from an approved brief
3. **Breaking a routing tie**, when the keyword scores are genuinely level

Different jobs get different settings. Stock and pricing use a low temperature
(0.3) because predictability matters. Marketing uses 0.85 because an advert
should not sound like a spreadsheet.

## 15. What the language model must never decide

- **Any number.** Not a total, not change, not profit, not a stock level.
- **Whether there is enough stock.**
- **Whether to save a sale.**
- **What a product costs or sells for.**
- **Whether an advert is safe to run.**

If the model is unavailable, KasiBiz still answers - in plainer words, with
identical figures. This is not a fallback bolted on afterwards; it is how the
system is built, and it was proved during two days when the API key was dead.

## 16. How confirmation protects data

A sale has two halves, deliberately kept apart:

```
BEFORE the owner confirms    nothing written, nothing leaves the shelf
AFTER the owner confirms     sale and stock move together, or not at all
```

Before `confirm_sale()` runs, `ready_to_confirm()` must pass: there must be
items, there must be a payment, and the payment must cover the total. Cancelling
throws the basket away - there is nothing to undo, because nothing was written.

The screen adds a second gate: **Save this sale** only reveals **Yes, save it**.

## 17. How environment variables protect secrets

Secrets live in `.env`, which is listed in `.gitignore` and never committed.
`.env.example` is committed, and holds placeholders only.

```python
OPENAI_API_KEY=sk-...      # a real secret
DATABASE_URL=sqlite:///kasibiz.db   # a file path
CHROMA_DB_PATH=chroma_db            # a folder path
```

**Only the first one is a secret.** The other two are locations on your own
machine that need no account and no password.

The code enforces the split: `get_database_url()` and `get_chroma_db_path()`
deliberately do **not** call `load_settings()`, so the database and knowledge
base keep working when no key is present at all.

## 18. How tests protect the system

Roughly 1,200 automated tests, in three kinds:

| Kind | What it does |
|---|---|
| **Unit** | One piece alone, neighbours replaced by stand-ins. Fast and precise. |
| **Integration** | Real database, real knowledge base, real agents, wired together. |
| **Screen smoke** | Runs the Streamlit script and checks what rendered. |

Three are worth calling out:

- **`test_intents.py`** takes *every* phrase in the vocabulary that claims to
  route and checks it actually reaches its own specialist. It caught two
  mistakes the day it was written.
- **`test_sales_service.py`** spends most of its time on failure: cancelled
  sales, failed sales, double confirmations, stock that must not move.
- **`test_streamlit_app.py`** includes a test that reproduces Streamlit's own
  import order, because the app once started and died while 27 screen tests
  passed.

And the lesson under all of it: **a green suite is evidence, not proof.** Every
build day so far has found something by opening the app and using it.

## 19. A request, followed all the way through

The owner types **`2 White Bread`** and presses enter.

```
 1. Streamlit    reads the chat box, calls coordinator.ask("2 White Bread")
 2. Memory       nothing to complete - it is already a whole instruction
 3. Language     no strong markers, stays English
 4. Router       scores it: no phrase matches, so UNKNOWN
 5. Shape rule   a number in front of a known product -> Route.SALES
 6. Sales Agent  intent = ADD_ITEM, product = "White Bread", quantity = 2
 7. Service      match_product -> one exact match
                 is 2 <= 24 in stock? yes
                 price comes from the DATABASE, never from the message
 8. Calculation  line_total = 2000c x 2 = 4000c
 9. Basket       held in memory. NOTHING IS WRITTEN.
10. Check        every figure in the reply appears in the facts - passes
11. Streamlit    shows the basket and asks how much they paid
```

Then **`they paid R50`**:

```
12. Router      "they paid" scores 4 for SALES
13. Calculation change = 5000c - 4000c = 1000c
14. Streamlit   shows R10.00 change and a Save this sale button
    STILL NOTHING WRITTEN
```

Then **yes**:

```
15. Router      a basket is open, so "yes" belongs to the till
16. Guard       ready_to_confirm(): items? paid? enough? - all yes
17. Transaction BEGIN IMMEDIATE
                  INSERT INTO sales       (reference is UNIQUE)
                  INSERT INTO sale_items  (price copied in)
                  UPDATE products ... WHERE quantity >= 2
                COMMIT
18. Streamlit   shows the receipt; the sidebar count goes up
```

As a diagram:

```
Owner
  -> Streamlit page (validates the shape of the input)
  -> Coordinator: resolve -> detect language -> route
  -> Specialist agent
       -> Service          (business rules)
       -> Calculation      (deterministic arithmetic)
       -> SQLite or ChromaDB
  -> facts
  -> optional AI rewording of those facts
  -> figure check (did anything get invented?)
  -> shown to the owner
  -> CONFIRMATION, if this would change records
  -> one database transaction
  -> screen refreshes from the database
```

Notice where the AI sits: near the end, downstream of every decision that
matters, and it can be removed without breaking the chain.

## 20. Known limitations

- **The five non-English languages have not been checked by native speakers.**
  They were written from reference material. This should be fixed before real
  shop owners see it.
- **Speech input is not built.** It is in the plan, but nothing exists, so there
  is deliberately no half-working microphone button.
- **One shop, one till, no login.** No multi-user support.
- **SQLite means one machine.** Hosting for several users means PostgreSQL.
  `DATABASE_URL` exists so that change stays small.
- **Gross profit only.** It counts what you paid for the goods - not rent,
  transport, electricity or your own time.
- **The knowledge base is 16 documents.** It answers common CIPC and SARS
  questions and declines everything else.
- **Nothing is hosted.** A public demo needs a spend cap on the OpenAI key and a
  passcode on the app.
- **Guidance is educational.** KasiBiz is not a legal, tax or financial adviser,
  and says so on every screen.
