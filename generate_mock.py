"""
Generate Diff View mock data: 5 runs of mbpp_798__sum with controlled behavioral changes.
under lasso-visual-analytics: uv run python3 generate_mock.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from core.lakehouse_client import LassoDataClient
from core.queries import behavioral_clustering

# ── Step 1: 读取现有数据 ──────────────────────────────────────────────────────
print("读取现有数据...")
client = LassoDataClient()
conn   = client.conn

df = conn.execute("SELECT * FROM observations").fetchdf()
original_run = df['run_id'].iloc[0]
print(f"  原始 run_id: {original_run}")
print(f"  数据行数: {len(df)}")

# ── Step 2: 找出oracle和deviant实现 ──────────────────────────────────────────
print("分析cluster结构...")
clusters = behavioral_clustering(conn, 'mbpp_798__sum')
oracle_members  = list(clusters.iloc[0]['members'])
deviant_members = [m for members in clusters.iloc[1:]['members'] for m in members]

print(f"  Oracle实现数: {len(oracle_members)}")
print(f"  Deviant实现数: {len(deviant_members)}")

# ── Step 3: 复制数据，给新run_id ──────────────────────────────────────────────
print("创建第二个run...")
df2 = df.copy()
df2['run_id'] = 'mock-run-regression-001'

# 拿到oracle第一个实现的输出，用来作为"正确答案"参考
oracle_impl = oracle_members[0]
oracle_outputs = (
    df[df['implementation_id'] == oracle_impl]
    [['test_id', 'step_id', 'output']]
    .set_index(['test_id', 'step_id'])['output']
    .to_dict()
)

# ── Step 4: 制造FIX ── 3个deviant实现在第二次run里变好了 ─────────────────────
impls_to_fix = deviant_members[:3]
fix_count = 0
for impl in impls_to_fix:
    mask = df2['implementation_id'] == impl
    for idx in df2[mask].index:
        row = df2.loc[idx]
        oracle_val = oracle_outputs.get((row['test_id'], row['step_id']))
        if oracle_val is not None:
            df2.at[idx, 'output'] = oracle_val
            fix_count += 1
print(f"  FIX: {len(impls_to_fix)} 个实现变好了 ({fix_count} 行输出值改变)")

# ── Step 5: 制造REGRESSION ── 3个oracle实现在第二次run里变差了 ───────────────
impls_to_break = oracle_members[:3]
reg_count = 0
for impl in impls_to_break:
    # 只改step_id=0的行，模拟一个特定输入场景下的regression
    mask = ((df2['implementation_id'] == impl) & (df2['step_id'] == 0))
    df2.loc[mask, 'output'] = '$EXCEPTION@java.lang.IllegalStateException@regression_injected'
    reg_count += mask.sum()
print(f"  REGRESSION: {len(impls_to_break)} 个实现变差了 ({reg_count} 行输出值改变)")

# ── Step 6: 合并保存 ──────────────────────────────────────────────────────────
print("保存合并数据...")
df_combined = pd.concat([df, df2], ignore_index=True)

output_path = Path("data/mbpp_798__sum_two_runs.parquet")
output_path.parent.mkdir(exist_ok=True)
df_combined.to_parquet(output_path, index=False)

print(f"\n完成！")
print(f"  保存路径: {output_path}")
print(f"  总行数: {len(df_combined)}")
print(f"  Run IDs: {df_combined['run_id'].unique().tolist()}")
print(f"\n下一步：把 core/lakehouse_client.py 的 data_path 改成 'data/mbpp_798__sum_two_runs.parquet'")
