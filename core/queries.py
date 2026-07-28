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
Core analytical queries for LASSO Visual Analytics.
Fully Thread-Safe implementation utilizing independent DuckDB cursors.
"""
import pandas as pd

def behavioral_clustering(conn, problem_id: str, run_id: str = None):
    cursor = conn.cursor()
    try:
        if run_id is None:
            row = cursor.execute(f"""
                SELECT run_id FROM observations
                WHERE problem_id = '{problem_id}'
                LIMIT 1
            """).fetchone()
            if row is None:
                return pd.DataFrame(columns=['members', 'fingerprint', 'cluster_size', 'test_size'])
            run_id = row[0]

        df = cursor.execute(f"""
            WITH sigs AS (
                SELECT test_id, implementation_id,
                       to_json(list(output ORDER BY step_id)) AS sig
                FROM observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{run_id}'
                GROUP BY test_id, implementation_id
            ),
            fps AS (
                SELECT implementation_id,
                       array_agg(sig ORDER BY test_id) AS fingerprint,
                       count(test_id) AS test_size
                FROM sigs
                GROUP BY implementation_id
            )
            SELECT
                array_agg(implementation_id) AS members,
                fingerprint,
                count(*) AS cluster_size,
                MAX(test_size) AS test_size
            FROM fps
            GROUP BY fingerprint
            ORDER BY cluster_size DESC
        """).fetchdf()
        
        return df if df is not None and not df.empty else pd.DataFrame(columns=['members', 'fingerprint', 'cluster_size', 'test_size'])
    finally:
        cursor.close()


def srm_pivot(conn, problem_id: str, run_id: str = None):
    cursor = conn.cursor()
    try:
        if run_id is None:
            row = cursor.execute(f"""
                SELECT run_id FROM observations
                WHERE problem_id = '{problem_id}' LIMIT 1
            """).fetchone()
            run_id = row[0] if row else None
            
        if run_id is None:
            return pd.DataFrame()

        df = cursor.execute(f"""
            WITH t AS (
                SELECT test_id, step_id, implementation_id, output
                FROM observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{run_id}'
            )
            PIVOT t ON implementation_id
            USING FIRST(output)
            GROUP BY test_id, step_id
            ORDER BY test_id, step_id
        """).fetchdf()
        
        return df if df is not None else pd.DataFrame()
    finally:
        cursor.close()


def problem_list(conn):
    cursor = conn.cursor()
    try:
        df = cursor.execute("""
            SELECT problem_id, COUNT(DISTINCT implementation_id) AS impl_count
            FROM observations
            GROUP BY problem_id
            ORDER BY impl_count DESC
        """).fetchdf()
        return df["problem_id"].tolist() if df is not None and not df.empty else []
    finally:
        cursor.close()


def run_list(conn, problem_id: str):
    cursor = conn.cursor()
    try:
        df = cursor.execute(f"""
            SELECT DISTINCT run_id
            FROM observations
            WHERE problem_id = '{problem_id}'
            ORDER BY run_id
        """).fetchdf()
        return df["run_id"].tolist() if df is not None and not df.empty else []
    finally:
        cursor.close()


def be_cluster_per_run(conn, problem_id: str, run_ids: list):
    empty_return = pd.DataFrame(columns=['run_id', 'implementation_id', 'cluster_label'])
    
    if not run_ids:
        return empty_return

    cursor = conn.cursor()
    try:
        first_run = run_ids[0]

        baseline_fps = cursor.execute(f"""
            WITH sigs AS (
                SELECT test_id, implementation_id,
                       to_json(list(output ORDER BY step_id)) AS sig
                FROM be_observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{first_run}'
                GROUP BY test_id, implementation_id
            ),
            fps AS (
                SELECT implementation_id,
                       array_agg(sig ORDER BY test_id) AS fingerprint
                FROM sigs GROUP BY implementation_id
            ),
            fp_cast AS (
                SELECT implementation_id, CAST(fingerprint AS VARCHAR) AS fp
                FROM fps
            )
            SELECT implementation_id, fp,
                   count(*) OVER (PARTITION BY fp) AS cluster_size
            FROM fp_cast
            ORDER BY cluster_size DESC
        """).fetchdf()

        if baseline_fps is None or len(baseline_fps) == 0:
            return empty_return

        # 强制规范化列名以防 DuckDB 别名解析出错
        if len(baseline_fps.columns) >= 3:
            baseline_fps.columns = ['implementation_id', 'fp', 'cluster_size'] + baseline_fps.columns.tolist()[3:]

        fp_to_label = {}
        cluster_order = baseline_fps.drop_duplicates('fp').sort_values('cluster_size', ascending=False)
        for i, (_, row) in enumerate(cluster_order.iterrows()):
            letter = chr(ord('A') + i) if i < 26 else 'Z'
            fp_to_label[row['fp']] = letter

        results = []
        for run_id in run_ids:
            run_fps = cursor.execute(f"""
                WITH sigs AS (
                    SELECT test_id, implementation_id,
                           to_json(list(output ORDER BY step_id)) AS sig
                    FROM be_observations
                    WHERE problem_id = '{problem_id}'
                      AND run_id = '{run_id}'
                    GROUP BY test_id, implementation_id
                ),
                fps AS (
                    SELECT implementation_id,
                           array_agg(sig ORDER BY test_id) AS fingerprint
                    FROM sigs GROUP BY implementation_id
                )
                SELECT implementation_id, CAST(fingerprint AS VARCHAR) AS fp
                FROM fps
            """).fetchdf()

            if run_fps is None or len(run_fps) == 0:
                continue
                
            if len(run_fps.columns) >= 2:
                run_fps.columns = ['implementation_id', 'fp'] + run_fps.columns.tolist()[2:]
            else:
                continue

            for _, row in run_fps.iterrows():
                fp_str = str(row['fp'])
                label = fp_to_label.get(fp_str)
                if label is None:
                    existing = set(fp_to_label.values())
                    for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                        if c not in existing:
                            fp_to_label[fp_str] = c
                            label = c
                            break
                results.append({
                    'run_id': run_id,
                    'implementation_id': row['implementation_id'],
                    'cluster_label': f"State {label}" if label else "State ?"
                })

        return pd.DataFrame(results) if results else empty_return
    finally:
        cursor.close()


def be_transition_detail(conn, problem_id: str, implementation_id: str,
                         run_before: str, run_after: str):
    cursor = conn.cursor()
    try:
        df = cursor.execute(f"""
            WITH before AS (
                SELECT test_id, step_id, CAST(output AS VARCHAR) AS before_output
                FROM be_observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{run_before}'
                  AND implementation_id = '{implementation_id}'
            ),
            after AS (
                SELECT test_id, step_id, CAST(output AS VARCHAR) AS after_output
                FROM be_observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{run_after}'
                  AND implementation_id = '{implementation_id}'
            )
            SELECT a.test_id, a.step_id,
                   b.before_output, a.after_output,
                   CASE WHEN b.before_output = a.after_output THEN 'STABLE'
                        ELSE 'CHANGED' END AS status
            FROM after a
            LEFT JOIN before b ON a.test_id = b.test_id AND a.step_id = b.step_id
            WHERE b.before_output != a.after_output OR b.before_output IS NULL
            ORDER BY a.test_id, a.step_id
            LIMIT 10
        """).fetchdf()
        
        return df if df is not None and not df.empty else pd.DataFrame(columns=['test_id', 'step_id', 'before_output', 'after_output', 'status'])
    finally:
        cursor.close()


def diff_view(conn, problem_id: str, baseline_run: str, target_run: str,
              oracle_members: list):
    if not oracle_members:
        return pd.DataFrame(columns=['implementation_id', 'test_id', 'step_id', 'baseline_output', 'target_output', 'oracle_output', 'status'])
        
    cursor = conn.cursor()
    try:
        oracle_list = ", ".join(f"'{m}'" for m in oracle_members)

        df = cursor.execute(f"""
            WITH base AS (
                SELECT implementation_id, test_id, step_id,
                       CAST(output AS VARCHAR) AS baseline_output
                FROM observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{baseline_run}'
            ),
            tgt AS (
                SELECT implementation_id, test_id, step_id,
                       CAST(output AS VARCHAR) AS target_output
                FROM observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{target_run}'
            ),
            oracle_vals AS (
                SELECT test_id, step_id, mode(CAST(output AS VARCHAR)) AS oracle_output
                FROM observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{target_run}'
                  AND implementation_id IN ({oracle_list})
                GROUP BY test_id, step_id
            )
            SELECT
                t.implementation_id,
                t.test_id,
                t.step_id,
                b.baseline_output,
                t.target_output,
                ov.oracle_output,
                CASE
                    WHEN b.baseline_output = t.target_output
                        THEN 'STABLE'
                    WHEN b.baseline_output = ov.oracle_output
                     AND t.target_output   != ov.oracle_output
                        THEN 'REGRESSION'
                    WHEN b.baseline_output != ov.oracle_output
                     AND t.target_output   = ov.oracle_output
                        THEN 'FIX'
                    ELSE 'DRIFT'
                END AS status
            FROM tgt t
            LEFT JOIN base b
                ON t.implementation_id = b.implementation_id
                AND t.test_id = b.test_id
                AND t.step_id = b.step_id
            LEFT JOIN oracle_vals ov
                ON t.test_id = ov.test_id
                AND t.step_id = ov.step_id
        """).fetchdf()
        
        return df if df is not None and not df.empty else pd.DataFrame(columns=['implementation_id', 'test_id', 'step_id', 'baseline_output', 'target_output', 'oracle_output', 'status'])
    finally:
        cursor.close()


def step_vulnerability(conn, problem_id: str, run_id: str, oracle_members: list):
    if not oracle_members:
        return pd.DataFrame(columns=['test_id', 'step_id', 'deviant_count'])
        
    cursor = conn.cursor()
    try:
        oracle_list = ", ".join(f"'{m}'" for m in oracle_members)
        df = cursor.execute(f"""
            WITH oracle_vals AS (
                SELECT test_id, step_id,
                       mode(CAST(output AS VARCHAR)) AS oracle_output
                FROM observations
                WHERE problem_id = '{problem_id}'
                  AND run_id = '{run_id}' -- 【修复1】加上特定 Run 的过滤
                  AND implementation_id IN ({oracle_list})
                GROUP BY test_id, step_id
            ),
            all_vals AS (
                SELECT o.test_id, o.step_id, o.implementation_id, 
                       CAST(o.output AS VARCHAR) AS output,
                       ov.oracle_output
                FROM observations o
                JOIN oracle_vals ov
                  ON o.test_id = ov.test_id AND o.step_id = ov.step_id
                WHERE o.problem_id = '{problem_id}'
                  AND o.run_id = '{run_id}' -- 【修复2】加上特定 Run 的过滤
                  AND o.implementation_id NOT IN ({oracle_list})
            )
            SELECT test_id, step_id,
                   COUNT(*) FILTER (
                       -- 【修复3】严谨处理 NULL 值的差异比对
                       WHERE output != oracle_output 
                          OR (output IS NULL AND oracle_output IS NOT NULL)
                          OR (output IS NOT NULL AND oracle_output IS NULL)
                   ) AS deviant_count
            FROM all_vals
            GROUP BY test_id, step_id
            HAVING deviant_count > 0
            ORDER BY deviant_count DESC
            LIMIT 10
        """).fetchdf()
        
        return df if df is not None and not df.empty else pd.DataFrame(columns=['test_id', 'step_id', 'deviant_count'])
    finally:
        cursor.close()