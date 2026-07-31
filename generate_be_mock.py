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

"""
Generate BE tab mock data: 5 runs of mbpp_798__sum with controlled behavioral changes.
Run: uv run python3 generate_be_mock.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from core.lakehouse_client import LassoDataClient
from core.queries import behavioral_clustering

print("Reading original data...")
client = LassoDataClient()
conn   = client.conn

df = conn.execute(f"""
    SELECT * FROM observations
    WHERE problem_id = 'mbpp_798__sum'
      AND run_id = (
        SELECT run_id FROM observations
        WHERE problem_id = 'mbpp_798__sum'
        LIMIT 1
      )
""").fetchdf()
original_run = df['run_id'].iloc[0]
print(f"  Original run: {original_run}")
print(f"  Rows: {len(df)}")

clusters = behavioral_clustering(conn, 'mbpp_798__sum', original_run)
oracle_members  = sorted(list(clusters.iloc[0]['members']))
deviant_members = sorted([m for members in clusters.iloc[1:]['members'] for m in members])
print(f"  Oracle: {len(oracle_members)}, Deviant: {len(deviant_members)}")

# Helper: get oracle output for a step
oracle_impl = oracle_members[0]
oracle_outputs = (
    df[df['implementation_id'] == oracle_impl]
    .set_index(['test_id', 'step_id'])['output']
    .to_dict()
)

def make_run(source_df, run_id, impls_to_fix=None, impls_to_break=None, impls_to_remove=None):
    d = source_df.copy()
    d['run_id'] = run_id

    if impls_to_fix:
        for impl in impls_to_fix:
            for idx in d[d['implementation_id'] == impl].index:
                row = d.loc[idx]
                oracle_val = oracle_outputs.get((row['test_id'], row['step_id']))
                if oracle_val is not None:
                    d.at[idx, 'output'] = oracle_val

    if impls_to_break:
        for impl in impls_to_break:
            mask = ((d['implementation_id'] == impl) & (d['step_id'] == 0))
            d.loc[mask, 'output'] = '$EXCEPTION@java.lang.IllegalStateException@regression_injected'

    if impls_to_remove:
        d = d[~d['implementation_id'].isin(impls_to_remove)]

    return d

print("Generating 5 runs...")

# Run 1 = original (baseline)
run1 = df.copy()

# Run 2 = stable (no changes)
run2 = make_run(df, 'be-run-2-stable')

# Run 3 = 3 deviant impls get FIXED (behavioral shift deviant→oracle)
run3 = make_run(df, 'be-run-3-fix',
                impls_to_fix=deviant_members[:3])

# Run 4 = 3 oracle impls get REGRESSION (behavioral shift oracle→deviant)
run4 = make_run(df, 'be-run-4-regression',
                impls_to_break=oracle_members[:3])

# Run 5 = same as run 4 but one impl disappears (Banana Problem)
run5 = make_run(df, 'be-run-5-banana',
                impls_to_break=oracle_members[:3],
                impls_to_remove=[oracle_members[4]])

all_runs = pd.concat([run1, run2, run3, run4, run5], ignore_index=True)

output_path = Path('data/mbpp_798__sum_be_runs.parquet')
output_path.parent.mkdir(exist_ok=True)
all_runs.to_parquet(output_path, index=False)

print(f"\nDone!")
print(f"  Saved: {output_path}")
print(f"  Total rows: {len(all_runs)}")
print(f"  Run IDs:")
for rid, cnt in all_runs.groupby('run_id').size().items():
    print(f"    {rid}: {cnt} rows")
print(f"\n  Run meanings:")
print(f"    {original_run[:20]}... → Run 1 (original baseline)")
print(f"    be-run-2-stable      → Run 2 (no changes)")
print(f"    be-run-3-fix         → Run 3 (3 deviant impls fixed)")
print(f"    be-run-4-regression  → Run 4 (3 oracle impls regressed)")
print(f"    be-run-5-banana      → Run 5 (same + 1 impl disappeared)")
