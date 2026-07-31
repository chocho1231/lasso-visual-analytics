"""
Copyright (c) 2026, Chair of Software Technology
All rights reserved.
Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
• Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer. 
• Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution. 
• Neither the name of the University Mannheim nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission. 

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

"""
LASSO Visual Analytics — Dash app
Run: uv run python app.py  →  http://localhost:8050
"""

import time
import statistics
import duckdb
from pathlib import Path

# Import your actual query functions
from core.queries import (
    behavioral_clustering,
    srm_pivot,
    diff_view
)

# 1. Config
PROBLEM_ID = "mbpp_798__sum"
BASELINE_RUN_ID = "14c387a3-dde2-4b9a-b1ee-deae5f8ac0de"
TARGET_RUN_ID = "be-run-2-stable"
REPEATS = 10

# 2. Setup Database Connection (matching app.py exactly)
print("Initializing DuckDB and mounting Parquet views...")
conn = duckdb.connect(database=':memory:', read_only=False)

srm_path = Path(__file__).parent / "data" / "mbpp_798__sum_two_runs.parquet"
be_path = Path(__file__).parent / "data" / "mbpp_798__sum_be_runs.parquet"

if srm_path.exists():
    conn.execute(f"CREATE OR REPLACE VIEW observations AS SELECT * FROM read_parquet('{srm_path}')")
else:
    print(f"Warning SRM file not found at {srm_path}")

if be_path.exists():
    conn.execute(f"CREATE OR REPLACE VIEW be_observations AS SELECT * FROM read_parquet('{be_path}')")
else:
    print(f"Warning BE file not found at {be_path}")

print("Warmup done.\n")

# 3. Define Benchmark Tasks
# Using lambda functions to pass the connection and arguments lazily
QUERIES = {
    "Behavioral Clustering": lambda: behavioral_clustering(conn, PROBLEM_ID, BASELINE_RUN_ID),
    "SRM Pivot": lambda: srm_pivot(conn, PROBLEM_ID, BASELINE_RUN_ID),
    "Diff View": lambda: diff_view(conn, PROBLEM_ID, BASELINE_RUN_ID, TARGET_RUN_ID, [])
}

# 4. Execute Benchmark
results = {}

for name, query_func in QUERIES.items():
    times = []
    print(f"Benchmarking {name}")
    
    for i in range(REPEATS):
        start = time.perf_counter()
        
        # Execute the function which runs the query and returns a dataframe
        query_func()
        
        end = time.perf_counter()
        
        ms = (end - start) * 1000
        times.append(ms)
        print(f"  Run {i+1:>2} {ms:.1f} ms")
    
    median = statistics.median(times)
    maximum = max(times)
    minimum = min(times)
    
    results[name] = {
        "runs": times,
        "median": median,
        "min": minimum,
        "max": maximum
    }
    print(f"  Median {median:.1f} ms | Min {minimum:.1f} ms | Max {maximum:.1f} ms\n")

conn.close()

# 5. Summary Table
print("=" * 80)
print(f"{'Query':<25} | "
      f"{'R1':>6} {'R2':>6} {'R3':>6} {'R4':>6} "
      f"{'R5':>6} {'R6':>6} {'R7':>6} {'R8':>6} "
      f"{'R9':>6} {'R10':>6} | "
      f"{'Med':>6} {'Max':>6}")
print("=" * 80)

for name, data in results.items():
    runs_str = " ".join(f"{r:>6.1f}" for r in data["runs"])
    print(f"{name:<25} | {runs_str} | "
          f"{data['median']:>6.1f} {data['max']:>6.1f}")