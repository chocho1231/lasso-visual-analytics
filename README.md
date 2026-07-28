# Lasso Visual Analytics 

This repository contains the visual analytics prototype for my thesis. The system leverages an "Observation Lakehouse" architecture to analyze and visualize the behavioral evolution of code implementations across multiple test runs.

## 🚀 Features
* **Behavioral Clustering**: Groups similar code behaviors.
* **Diff View**: Highlights fine-grained changes across versions.
* **Evolution Timeline**: Tracks behavioral changes across testing iterations.

## 🛠 Tech Stack
* **Frontend**: Dash / Plotly
* **Backend Lakehouse**: DuckDB (for high-performance OLAP queries)
* **Package Management**: `uv`

## 📦 How to Run

1. **Install `uv`** (if not already installed):
   ```bash
   curl -LsSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) | sh

2. **Clone the repository:**
   git clone https://github.com/YourUsername/your-repo-name.git
   cd your-repo-name

3. **Run the application:**
   uv run app.py

The application will automatically install dependencies and start the server at `http://127.0.0.1:8050` in your browser.