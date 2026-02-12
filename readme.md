# 🏆 FPL Elite Dashboard

A high-performance Streamlit application designed for Fantasy Premier League managers who want a data-driven edge. This dashboard syncs directly with your team to provide advanced analytics that the official app doesn't offer.

## 🚀 Key Features

* **💡 Intelligent Chip Planner:** Real-time logic that detects Double Gameweeks (DGW) and Blanks to recommend Triple Captain, Bench Boost, or Free Hit usage.
* **🧑‍✈️ Captaincy Predictor:** Ranks your top 3 assets based on a proprietary 'Cap Score' (Form + Fixture Difficulty).
* **🛡️ Rival Deep-Dive:** Compare your squad against any manager ID. Analyzes **Shield** (shared players), **Sword** (your differentials), and **Danger** (their differentials).
* **🔄 Transfer Optimizer:** Identifies your "weakest link" based on efficiency and suggests 8 high-ICT replacements within your budget.
* **📅 5-Week Ticker:** A color-coded fixture difficulty tracker that highlights Double Gameweeks in purple.
* **⚔️ Player VS Radar:** A visual comparison tool to weigh up two players side-by-side across xG, Form, and ICT Index.

## 🛠️ Installation & Deployment

1. **Clone the repo:**
   `git clone https://github.com/YOUR_USERNAME/fpl-dashboard.git`
2. **Install dependencies:**
   `pip install -r requirements.txt`
3. **Run locally:**
   `streamlit run app.py`

## 📊 Data Source
This app uses the official [FPL API](https://fantasy.premierleague.com/api/bootstrap-static/) for real-time player and fixture data.