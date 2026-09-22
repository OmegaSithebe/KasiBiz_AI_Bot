# KasiBiz final demonstration guide

Everything here uses the real products in `data/products.csv` and the real
behaviour of the code. Nothing is invented for the slides.

**Total running time: about 12 minutes.**

---

## A. Pre-demo checklist

Do this **30 minutes before**, not 30 seconds before.

### A1. The code

```powershell
cd KasiBiz_AI_Bot
git status --short
```

Uncommitted work is fine — just know what it is. Nothing here depends on a
clean tree.

### A2. The environment

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt must show `(.venv)`. If not, nothing else will work.

```powershell
python --version          # expect 3.12.x
python -m pip check       # expect: No broken requirements found
```

### A3. Secrets

```powershell
Test-Path .env            # expect True
```

`.env` must exist. It is git-ignored. **Never open it on screen while
recording** — your API key is in it.

### A4. Reset and reseed the demo shop

```powershell
python scripts/seed_demo.py --reset
```

Expect roughly:

```
Products loaded: 20 new, 20 on the shelf.
Sales invented: ~38 over the last 7 day(s).
Shelf restocked after those sales: 16 product(s).
Forced low stock for the demo: Paraffin 1L -> 0, Candles 6-pack -> 1, Milk 1L -> 4
```

Those three forced items are what you will demonstrate with. **Note the exact
numbers you get** — the invented sales vary slightly, and you will quote the
totals on camera.

### A5. The knowledge base

```powershell
python scripts/rag_ingest.py --status
```

Expect about **26 passages from 16 documents**. If it is empty:

```powershell
python scripts/rag_ingest.py --local
```

### A6. The health check

```powershell
python scripts/health_check.py
```

**You want `ALL SYSTEMS READY`.** Do not start recording until you see it. If
you plan to demo with AI wording on, also run:

```powershell
python scripts/health_check.py --ai
```

### A7. The tests

```powershell
python -m pytest tests/ -q -k "not streamlit"
```

Faster than the full suite and enough to prove the engine is sound. If an
assessor asks for everything, run `python -m pytest tests/ -q` — it takes about
five minutes.

### A8. Start the app

```powershell
streamlit run streamlit_app/app.py
```

### A9. The browser

Open **<http://localhost:8501>**.

- Close every other tab
- Zoom to **110%** so figures are readable on video
- Hide bookmarks
- Turn off notifications

### A10. Data safety

The shop on screen is invented. There is **no real customer data anywhere**.
Say so once, out loud, early — assessors notice.

### A11. If OpenAI is down

**This is the strongest part of the demo, so rehearse it.**

Turn **Use AI wording** off in the sidebar. Everything still works: same
figures, plainer words. Say:

> "The AI is only writing the sentences. The arithmetic, the stock rules and the
> decisions are ordinary Python, so the shop keeps trading whether or not the
> internet does."

If Streamlit itself fails, fall back to the terminal:

```powershell
python scripts/demo_journey.py --pause
```

Same journey, thirteen steps, no browser.

---

## B. The demonstration journey

| # | Step | Roughly |
|---|---|---|
| 1 | The problem | 45s |
| 2 | What KasiBiz is | 45s |
| 3 | Language | 20s |
| 4 | The opening screen | 30s |
| 5 | Check stock | 45s |
| 6 | Add stock | 45s |
| 7 | Add a new product | 45s |
| 8-12 | A multi-item sale | 3m |
| 13 | Stock has moved | 30s |
| 14 | What is selling | 45s |
| 15 | Profit | 45s |
| 16 | A WhatsApp advert | 45s |
| 17 | CIPC / SARS | 45s |
| 18 | A refusal | 45s |
| 19-20 | Value and what is next | 1m |

---

## C. Presenter script

### Step 1 — The problem

**Say:**
> "A spaza shop owner runs everything from memory and a notebook. They know
> roughly what sells and roughly what they make. They find out they are out of
> paraffin when a customer asks for it. There are over 150,000 of these shops in
> South Africa."

**Do:** nothing. Just talk.

---

### Step 2 — What KasiBiz is

**Say:**
> "KasiBiz is an assistant they talk to in their own language, that answers from
> their own records. One rule runs through the whole thing: Python does the
> arithmetic, the AI does the language. The model never touches a number."

**Shows:** the design principle everything else follows.

---

### Step 3 — Choose a language

**Click:** the sidebar dropdown — **Language / Ulimi / Puo**
**Select:** **isiZulu**

**Say:**
> "English, isiZulu and Sesotho on the MVP. Six are supported underneath."

**Expect:** the dropdown shows isiZulu.

**If it does not:** carry on in English. Not worth stopping for.

---

### Step 4 — The opening screen

**Say:**
> "One chat box and six quick actions. The owner never picks which part of the
> system answers — that is worked out from what they type."

**Point at:** the sidebar — *20 products | N sales recorded*.

**Shows:** the screen is reading live from the database, not a mock-up.

---

### Step 5 — Check what is low

**Click:** **Check Stock**

**Say:**
> "That went to the Stock Agent. Nothing was typed — but watch what it says."

**Expect:** three products, most urgent first:
- **Paraffin 1L** — 0 left, OUT OF STOCK
- **Candles 6-pack** — 1 left, CRITICAL
- **Milk 1L** — 4 left, LOW

plus what to reorder and what it will cost.

**Point at:** the caption *"Answered using your shop's records"*.

**If nothing appears:** you did not seed. Stop and run `python
scripts/seed_demo.py --reset`.

---

### Step 6 — Add stock to an existing product

**Click:** **Stock** in the sidebar
**Expand:** *Add a new product, or add stock to one you already have*
**Select:** **Paraffin 1L**
**Type:** `12` into *How many did you receive?*
**Click:** **Add to the shelf**

**Expect:** *"Paraffin 1L is now 12."* and it disappears from the low-stock
warning.

**Say:**
> "A delivery arrived. The table updated immediately because it is reading the
> database, not a cached copy."

---

### Step 7 — Add a new product

**Select:** `-- a new product --`

**Type:**
- Product name: `Lucky Star Pilchards 400g`
- Unit: `tin`
- You pay: `18.50`
- You sell for: `25.00`
- How many now: `24`
- Warn me below: `6`

**Click:** **Add product**

**Expect:** *"Lucky Star Pilchards 400g added."* and a new row in the table with
**Profit each R6.50** — calculated, not typed.

**Say:**
> "I never told it the profit. That is the first of many numbers that comes from
> Python, not from me and not from the model."

---

### Step 8 — Start a sale

**Click:** **New Sale**
**Select:** **White Bread**
**Quantity:** `2`
**Click:** **Add to basket**

**Expect:** *2 x White Bread, R20.00 each = R40.00*, **TOTAL TO PAY R40.00**.

---

### Step 9 — Add more items

Repeat for:
- **Milk 1L** — quantity `1`
- **Simba Chips 36g** — quantity `3`

**Expect:** **TOTAL TO PAY R93.00**
(R40.00 + R23.00 + R30.00)

**Say:**
> "Three products, one basket. Every price came out of the database — I have not
> typed a single one."

---

### Step 10 — Take the payment

**Type:** `100` into *How much did the customer give you?*

**Expect:** **CHANGE TO GIVE R7.00** in large orange text.

**Say:**
> "R7.00. That is integer arithmetic in cents, not a language model, and not a
> decimal that can lose a cent when you add it up a hundred times."

---

### Step 11 — Nothing has been saved yet

**Point at:** the sidebar, still showing the old sales count.

**Say:**
> "The basket is on screen, the change is worked out — and not one thing has
> been written to the database. That is deliberate."

**Shows:** the confirmation gate. **This is the most important 15 seconds of the
demo.**

---

### Step 12 — Confirm

**Click:** **Save this sale**

**Expect:** a warning: *"Save 6 item(s) for R93.00 and take the stock off the
shelf?"*

**Say:**
> "It asks twice. Money and stock move together or not at all."

**Click:** **Yes, save it**

**Expect:**
- *Sale #N saved. Stock has been updated.*
- a printed receipt showing TOTAL R93.00, PAID R100.00, CHANGE R7.00
- three metrics: **Total**, **Change given**, **Profit on this sale**
- the sidebar sales count goes **up by one**

---

### Step 13 — The shelf has moved

**Click:** **Stock**

**Expect:** White Bread down by 2, Milk 1L down by 1, Simba Chips down by 3.

**Say:**
> "One transaction. If the power had cut halfway through, the shop would be
> exactly where it started — never half a sale."

---

### Step 14 — What is selling

**Click:** **Insights**
**Click:** **This week**

**Expect:** Money taken, Gross profit with a margin percentage, Sales count,
Items sold — then **Selling best** and **Moving slowest**.

**Say:**
> "Counted from recorded sales. If this shop had no sales, it would say so
> instead of guessing — a made-up best seller makes someone order the wrong
> stock with real money."

**Optional, if you have a spare 20 seconds:** click **Today** to show a smaller,
honest number rather than a padded one.

---

### Step 15 — Profit

**Click:** **Assistant**
**Type:** `Am I making enough profit on White Bread?`

**Expect:**
> White Bread: costs R15.00, sells for R20.00, profit R5.00 each (33.33% markup,
> 25.00% margin) - HEALTHY.

**Say:**
> "Markup and margin are not the same number and shop owners lose money on that
> confusion. Markup is measured against what you paid; margin against what you
> charge. It shows both, every time."

---

### Step 16 — A WhatsApp advert

**Type:** `Write a WhatsApp advert for Simba Chips 36g`

**Expect:** a short advert with the real price, a discount, and the real stock
level, signed with the shop name.

**Say:**
> "The copywriter is given the price and the stock level. It is never given the
> cost price — there is no version of this where the shop's margin ends up in a
> customer's WhatsApp."

---

### Step 17 — A business question

**Type:** `How do I register with CIPC?`

**Expect:** steps from the guides, and **Source: Cipc Overview…; Cipc
Registration…** underneath, plus the educational disclaimer.

**Say:**
> "That did not come from the model's memory. It was retrieved from documents we
> approved, and it tells you which one. If it finds nothing relevant, it says so
> rather than inventing an answer about company law."

---

### Step 18 — The refusal

**Type:** `20 Candles 6-pack`

**Expect:**
> Cannot sell 20 x Candles 6-pack: only 1 in stock.

**Say:**
> "Refusing is a feature. It will not sell stock that is not there, and it will
> not advertise a product that is about to run out. The safest answer is often
> no."

**Optional second refusal, if time allows:**
Type `Write an advert for Paraffin 1L` — before step 6 it refuses outright. If
you already restocked it in step 6, skip this one.

---

### Step 19 — The value

**Say:**
> "Six specialists, one chat box, six languages. Every figure calculated in
> Python and checked against its own source before the owner sees it. The whole
> thing runs offline if the internet goes down, and the entire test suite —
> about 1,200 tests — runs without spending a cent on the AI."

---

### Step 20 — What is next

**Say:**
> "Next: native-speaker review of the five non-English languages, then hosting
> with a spend cap, then multi-shop support. Speech input is in the plan and
> deliberately not half-built — you will not find a microphone button that does
> not work."

---

## D. Prompts that work with this seed data

Copy these exactly. Every product named here exists.

### English

| Purpose | Type this |
|---|---|
| Stock | `What is low in stock?` |
| Reorder | `What should I reorder?` |
| Sale | `2 White Bread` then `and 1 Milk 1L` then `they paid R100` then `yes` |
| Profit | `Am I making enough profit on White Bread?` |
| What-if | `What if I sell Milk 1L for R25?` |
| Insight | `What is selling well this week?` |
| Slow movers | `Which products are moving slowly?` |
| Takings | `How much did I take this week?` |
| Marketing | `Write a WhatsApp advert for Simba Chips 36g` |
| What to promote | `What should I promote this week?` |
| CIPC | `How do I register with CIPC?` |
| SARS | `What records must I keep for SARS?` |
| **Insufficient stock** | `20 Candles 6-pack` |
| Unknown product | `2 Caviar` |
| Ambiguous name | `2 Bread` |

### isiZulu

| Purpose | Type this | Means |
|---|---|---|
| Greeting | `Sawubona` | Hello |
| Stock | `Yini esiphelile?` | What has run out? |
| Price | `Ngingayithengisa ngamalini i-White Bread?` | What can I sell it for? |
| Confirm a sale | `Yebo` | Yes |

### Sesotho

| Purpose | Type this | Means |
|---|---|---|
| Greeting | `Dumela` | Hello |
| Price | `Ke reke ka bokae?` | What should I charge? |

> **Note on languages:** with **Use AI wording off**, the greeting comes back in
> isiZulu but the detailed answers stay in English, because those are fixed
> English sentences. **Turn AI wording on** to demonstrate full translation.
> Rehearse whichever one you intend to show.

### Products you can safely name

White Bread · Brown Bread · Milk 1L · Maize Meal 2.5kg · Rice 2kg ·
Cooking Oil 750ml · Sugar 1kg · Eggs 6-pack · Coca-Cola 500ml ·
Fanta Orange 500ml · Airtime R12 · Airtime R29 · Simba Chips 36g ·
Nik Naks 55g · Paraffin 1L · Candles 6-pack · Washing Powder 1kg ·
Bar Soap · Tea Bags 26s · Peanut Butter 400g

> Say **"Bread"** on its own and it will ask which one — White or Brown. That is
> correct behaviour and worth showing on purpose.

---

## E. Closing statement

> "KasiBiz takes the three things a spaza shop owner does every day — serve a
> customer, watch the shelf, work out whether they are actually making money —
> and puts them behind one chat box in their own language.
>
> The engineering decision underneath it is this: **the AI never touches a
> number.** Every total, every cent of change, every profit figure is ordinary
> Python that can be tested, and it is. Roughly 1,200 automated tests run
> without spending anything on the model, because the parts that matter do not
> need it. The language model writes sentences. It does not decide what is true.
>
> That is also why it refuses things. It will not sell stock that is not there.
> It will not advertise a product about to run out. It will not name a best
> seller in a shop with no recorded sales. For someone whose entire livelihood
> is in that shop, an assistant that admits what it does not know is worth more
> than one that always has an answer.
>
> It runs today, on one laptop, with no internet required for the parts that
> count."

---

## F. If something breaks mid-demo

| What happens | Do this | Say this |
|---|---|---|
| A page hangs | Press **R** in the browser | "Let me refresh that." |
| An answer looks wrong | Sidebar → **Start over** | "I'll start a fresh conversation." |
| AI wording fails | Toggle **Use AI wording** off | "That is the model being slow. The figures are local, so it keeps working." |
| Streamlit crashes | `python scripts/demo_journey.py --pause` | "Here is the same journey from the terminal." |
| The basket is stuck | Type `cancel` | "Cancelling writes nothing — the shelf is untouched." |
| Everything is broken | `python scripts/seed_demo.py --reset` then restart | "One command puts the demo shop back." |

**Never** open a terminal showing a stack trace on camera. Switch tabs first.
