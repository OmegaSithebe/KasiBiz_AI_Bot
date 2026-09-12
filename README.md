"# KasiBiz_AI_Bot" 

KasiBiz AI Business Assistant
Overview
KasiBiz is an AI-powered business assistant built for South African spaza shops and
tuck shop owners.
The goal of KasiBiz is to simplify daily business operations by helping shop owners:
 Manage inventory
 Calculate sales totals and customer change
 Understand what products sell best
 Monitor profit
 Generate marketing content
 Receive practical business guidance
 Track business progress over time
The solution is designed to support business owners at any stage:
 New businesses
 Growing businesses
 Established businesses

Project Vision
To provide a simple multilingual AI assistant that helps township entrepreneurs make
better business decisions using their own data.
Supported MVP Languages:
 English
 isiZulu
 Sesotho

Core Features
Inventory Management
 Add products
 Update stock
 View stock levels

 Low stock alerts

Sales Assistance
 Record customer purchases
 Calculate totals
 Calculate customer change
 Auto-update inventory

Business Insights
 Best-selling products
 Slow-moving products
 Inventory trends

Profit Tracking
 Product profit calculations
 Margin analysis

Marketing Assistant
Generate:
 WhatsApp adverts
 Promotions
 Product campaigns

Business Advisor
Provide business guidance using:
 Business knowledge resources
 User business data
 Retrieval-Augmented Generation (RAG)

Technology Stack
Frontend
 Streamlit
AI
 OpenAI
 LangChain
Knowledge Base
 ChromaDB
Database
 SQLite
Programming Language
 Python

Project Structure
app/
data/
docs/
streamlit_app/
tests/

Installation
Clone the repository:
git clone https://github.com/your-org/KasiBiz.git
Create virtual environment:
python -m venv venv
Activate environment:
venv\Scripts\activate
Install dependencies:
pip install -r requirements.txt

Create .env:
Create a file named .env in the project root (same folder as requirements.txt)
with these settings:

OPENAI_API_KEY=sk-your-real-key-here
MODEL_NAME=gpt-4o-mini
CHROMA_DB_PATH=chroma_db
DATABASE_URL=sqlite:///kasibiz.db
SHOP_NAME=KasiBiz Spaza

Only OPENAI_API_KEY is a real secret. Get one from
https://platform.openai.com/api-keys (billing must be enabled).
CHROMA_DB_PATH and DATABASE_URL are local file paths - they need no key,
no password and no account, and the folder/file is created automatically
on first use. SHOP_NAME is optional and just signs the marketing adverts.

.env is git-ignored. Never commit it and never paste a real key into any
file that is tracked by git.

Test the OpenAI connection (Day 4):
python scripts/hello_llm.py
Or ask your own question:
python scripts/hello_llm.py "Ngingayithengisa ngamalini i-bread?"
Or run the test suite:
pytest tests/test_llm_connection.py -v -s

Run Streamlit:
streamlit run streamlit_app/app.py

Current MVP Scope
✅ Inventory Tracking
✅ Sales Tracking
✅ Profit Calculator
✅ Marketing Assistant
✅ Business Advisor
✅ Progress Tracking

Future Features
 WhatsApp integration
 Multi-language expansion
 Voice-first interaction
 Supplier recommendations
 Smart reorder suggestions
 Mobile app

GitHub Workflow for Your 5-Man Team
Create these branches:
main
develop

feature/inventory

feature/sales

feature/marketing

feature/rag

feature/ui