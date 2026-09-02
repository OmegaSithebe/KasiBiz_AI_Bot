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
OPENAI_API_KEY=YOUR_API_KEY
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