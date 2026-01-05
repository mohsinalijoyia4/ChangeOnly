# 🚀 ChangeOnly: SEC Filing Intelligence Service

**ChangeOnly** is a specialized fintech micro-SaaS that provides real-time, section-by-section intelligence on SEC filings (10-K, 10-Q, and 8-K). It eliminates the noise by showing you **only what changed** between consecutive filings, highlighting critical updates in risk factors, financial conditions, and more.

---

## 📸 Preview

### 🏠 Home Page - Instant Search
Discover any public company's filing history with our high-speed search.
![Home Page](./screenshots/home.png)

### 📊 Ticker Intelligence
A dedicated SEO-friendly page for every ticker, displaying recent filings and detected changes.
![Ticker Page](./screenshots/ticker.png)

### 🔍 Deep Dive: Section-by-Section Diffs
See exactly what changed in the text. We chunk filings by "Items" and compute precise deltas.
![Filing Page](./screenshots/filing.png)

---

## ✨ Core Features

- **🎯 Smart Diff Engine**: Automatically chunks complex SEC filings into logical items and performs a sequence-matching analysis to find meaningful changes.
- **⚡ HTMX-Powered Performance**: Lazy-loads heavy diff data for a lightning-fast browsing experience.
- **📧 Watchlist & Alerts**: Track your portfolio and get email notifications **only** when a filing contains a detected change.
- **🔑 Magic Link Authentication**: Simple, secure, and passwordless login.
- **🛡️ SEC Compliant**: Built-in global throttling and exponential backoff to respect SEC EDGAR API limits.
- **📈 SEO Ready**: Dynamic, crawlable pages for every ticker to drive organic traffic.

---

## 🛠️ Technology Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11+)
- **Database**: [SQLModel](https://sqlmodel.tiangolo.com/) + SQLAlchemy
- **Frontend**: Vanilla CSS + [HTMX](https://htmx.org/) (High Performance, No Bloat)
- **Scheduling**: [APScheduler](https://apscheduler.agron.io/) for automated background polling.
- **Deployment**: Ready for any Python-capable host (Vercel, Render, Railway, etc.)

---

## 🚀 Getting Started

### Local Setup

1. **Clone and Install**:
```bash
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure Environment**:
```bash
cp .env.example .env
# Edit .env and set:
# SEC_USER_AGENT=YourProjectName (contact: your@email.com)
```

3. **Run the App**:
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 🏛️ Disclaimer
ChangeOnly is an informational tool only. It does not provide investment advice, financial planning, or tax guidance. Always perform your own due diligence before making investment decisions.

---

## 📄 License
MIT License. See [LICENSE](LICENSE) for details.
