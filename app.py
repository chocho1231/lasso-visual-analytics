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

import dash
import plotly.colors
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, dcc, html

from core.lakehouse_client import LassoDataClient
from core.queries import (
    be_cluster_per_run,
    be_transition_detail,
    behavioral_clustering,
    diff_view,
    problem_list,
    run_list,
    srm_pivot,
    step_vulnerability,
)

# ── Init ─────────────────────────────────────────────────────────────────────
client   = LassoDataClient()
conn     = client.conn

# Load BE and SRM parquets as separate views in the same DuckDB connection
import duckdb as _duckdb
from pathlib import Path as _Path

# 1. 挂载 SRM / Diff 数据到 observations 视图 (补充遗漏的底层数据源)
_srm_path = _Path(__file__).parent / "data" / "mbpp_798__sum_two_runs.parquet"
print(f"SRM path: {_srm_path}, exists: {_srm_path.exists()}")
if _srm_path.exists():
    conn.execute(f"""
        CREATE OR REPLACE VIEW observations AS
        SELECT * FROM read_parquet('{_srm_path}')
    """)

# 2. 挂载 BE 数据到 be_observations 视图 (您原有的逻辑)
_be_path = _Path(__file__).parent / "data" / "mbpp_798__sum_be_runs.parquet"
print(f"BE path: {_be_path}, exists: {_be_path.exists()}")
if _be_path.exists():
    conn.execute(f"""
        CREATE OR REPLACE VIEW be_observations AS
        SELECT * FROM read_parquet('{_be_path}')
    """)
    BE_AVAILABLE = True
else:
    BE_AVAILABLE = False

PROBLEMS = problem_list(conn)
BE_PROBLEMS = ["mbpp_798__sum"] if BE_AVAILABLE else []

# BE run IDs in display order
BE_RUN_IDS = [
    "14c387a3-dde2-4b9a-b1ee-deae5f8ac0de",
    "be-run-2-stable",
    "be-run-3-fix",
    "be-run-4-regression",
    "be-run-5-banana",
]
BE_RUN_LABELS = {
    "14c387a3-dde2-4b9a-b1ee-deae5f8ac0de": "Run 1 (Jan 15)",
    "be-run-2-stable":      "Run 2 (Feb 08)",
    "be-run-3-fix":         "Run 3 (Mar 01)",
    "be-run-4-regression":  "Run 4 (Apr 12)",
    "be-run-5-banana":      "Run 5 (May 20)",
}

# Pre-load run options at startup so dropdowns are populated on first render
_default_runs = run_list(conn, PROBLEMS[0]) if PROBLEMS else []
_run_options  = [{"label": r[:20] + "..." if len(r) > 20 else r, "value": r}
                 for r in _default_runs]
_baseline_default = _default_runs[0] if len(_default_runs) > 0 else None
_target_default   = _default_runs[1] if len(_default_runs) > 1 else None

_SAFE        = plotly.colors.qualitative.Safe
ORACLE_COLOR = "#14b8a6"


def make_color_map(n_clusters: int) -> dict:
    result = {}
    for i in range(n_clusters):
        letter = chr(ord("A") + i) if i < 26 else "Z"
        result[letter] = ORACLE_COLOR if letter == "A" else _SAFE[(i - 1) % len(_SAFE)]
    return result


def short_label(impl_id: str) -> str:
    base = impl_id.split("_")[0]
    return base[:10] + ".." if len(base) > 10 else base


def get_outputs_for_step(problem_id: str, test_id: str, step_id: int):
    return conn.execute(f"""
        SELECT implementation_id, CAST(output AS VARCHAR) AS output
        FROM observations
        WHERE problem_id = '{problem_id}'
          AND test_id    = '{test_id}'
          AND step_id    = {step_id}
    """).fetchdf()


DIFF_COLORS = {
    "REGRESSION": "#ef4444",
    "FIX":        "#22c55e",
    "DRIFT":      "#f97316",
    "STABLE":     "#e5e7eb",
}

def build_diff_heatmap(problem_id, baseline_run, target_run):
    clusters_df = behavioral_clustering(conn, problem_id, baseline_run)
    if clusters_df.empty:
        return go.Figure(), {}, 0, 0, 0, 0

    impl_label = {}
    for i, row in clusters_df.iterrows():
        letter = chr(ord("A") + i) if i < 26 else "Z"
        for impl in row["members"]:
            impl_label[impl] = letter

    oracle_members = sorted(list(clusters_df.iloc[0]["members"]))
    df = diff_view(conn, problem_id, baseline_run, target_run, oracle_members)

    if df.empty:
        return go.Figure(), {}, 0, 0, 0, 0

    # Counts for summary chips
    reg_count   = int((df["status"] == "REGRESSION").sum())
    fix_count   = int((df["status"] == "FIX").sum())
    drift_count = int((df["status"] == "DRIFT").sum())
    stable_count= int((df["status"] == "STABLE").sum())

    # Pivot to wide format
    impls = sorted(df["implementation_id"].unique().tolist())
    tests = df[["test_id","step_id"]].drop_duplicates().sort_values(["test_id","step_id"])

    color_map_status = {
        "REGRESSION": 3,
        "FIX":        2,
        "DRIFT":      1,
        "STABLE":     0,
    }
    colorscale = [
        [0.00, "#e5e7eb"],  # STABLE gray
        [0.33, "#f97316"],  # DRIFT orange
        [0.66, "#22c55e"],  # FIX green
        [1.00, "#ef4444"],  # REGRESSION red
    ]

    y_labels = [f"{r.test_id}·s{r.step_id}" for r in tests.itertuples()]
    x_labels = [short_label(i) for i in impls]

    # Build lookup
    status_lookup = {}
    for _, row in df.iterrows():
        status_lookup[(row["implementation_id"], row["test_id"], row["step_id"])] = row

    z, hover = [], []
    visible_tests = tests["test_id"].unique().tolist()

    for _, trow in tests.iterrows():
        row_z, row_h = [], []
        for impl in impls:
            entry = status_lookup.get((impl, trow.test_id, trow.step_id))
            if entry is None:
                row_z.append(0)
                row_h.append(f"<b>{impl}</b><br>No data")
            else:
                s = entry["status"]
                row_z.append(color_map_status.get(s, 0))
                row_h.append(
                    f"<b>{impl}</b><br>"
                    f"Status: <b>{s}</b><br>"
                    f"Before: {entry['baseline_output']}<br>"
                    f"After:  {entry['target_output']}"
                )
        z.append(row_z)
        hover.append(row_h)

    fig = go.Figure(go.Heatmap(
        z=z, x=x_labels, y=y_labels,
        text=hover, hovertemplate="%{text}<extra></extra>",
        colorscale=colorscale, zmin=0, zmax=3,
        showscale=False, xgap=1, ygap=1,
    ))

    # Separator lines between tests
    test_counts = tests.groupby("test_id", sort=False).size().to_dict()
    sep_y = -0.5
    for i, t in enumerate(visible_tests):
        sep_y += test_counts.get(t, 0)
        if i < len(visible_tests) - 1:
            fig.add_hline(y=sep_y, line_width=1, line_color="#d1d5db")

    n_cols = len(impls)
    fig.update_layout(
        margin=dict(l=160, r=20, t=40, b=60),
        width=max(800, n_cols * 24 + 200),
        height=max(420, len(y_labels) * 18 + 80),
        plot_bgcolor="#f9fafb", paper_bgcolor="#fff",
        xaxis=dict(side="top", tickfont=dict(size=9)),
        yaxis=dict(tickfont=dict(size=9), autorange="reversed"),
        clickmode="event",
    )

    return fig, impl_label, reg_count, fix_count, drift_count, stable_count


# ── Build heatmap ─────────────────────────────────────────────────────────────

def build_heatmap(problem_id, selected_clusters, deviant_only, focused_test=None):
    """
    focused_test: if set, show only rows for that test_id (used when SV item clicked).
    Uses the first available run_id for clustering (baseline run).
    """
    runs = run_list(conn, problem_id)
    baseline_run = runs[0] if runs else None

    clusters_df = behavioral_clustering(conn, problem_id, baseline_run)
    srm_df      = srm_pivot(conn, problem_id, baseline_run)

    if clusters_df.empty or srm_df.empty:
        return go.Figure(), {}, {}, {}

    impl_label = {}
    for i, row in clusters_df.iterrows():
        letter = chr(ord("A") + i) if i < 26 else "Z"
        for impl in row["members"]:
            impl_label[impl] = letter

    color_map      = make_color_map(len(clusters_df))
    oracle_members = list(clusters_df.iloc[0]["members"])
    cluster_sizes  = {chr(ord("A") + i): int(r["cluster_size"])
                      for i, r in clusters_df.iterrows()}

    impl_cols   = [c for c in srm_df.columns if c not in ("test_id", "step_id")]
    oracle_cols = [c for c in impl_cols if impl_label.get(c) == "A"]
    if selected_clusters:
        deviant_cols = [c for c in impl_cols if impl_label.get(c) in selected_clusters]
    else:
        deviant_cols = [c for c in impl_cols if impl_label.get(c) != "A"]
    ordered = oracle_cols + deviant_cols

    all_colors   = ["#ffffff", ORACLE_COLOR] + _SAFE
    color_to_num = {c: i for i, c in enumerate(all_colors)}
    n            = len(all_colors)
    colorscale   = [[i / (n - 1), c] for i, c in enumerate(all_colors)]

    # If the SRM DataFrame is empty or missing the "test_id" column, return an empty heatmap and empty structures for labels and cluster sizes.
    if srm_df is None or srm_df.empty or "test_id" not in srm_df.columns:
        # import plotly.graph_objects as go
        return go.Figure(), [], {}, {}

    all_tests = srm_df["test_id"].unique().tolist()
    all_steps = sorted(srm_df["step_id"].unique().tolist())

    def test_has_deviant(test):
        subset = srm_df[srm_df["test_id"] == test]
        oc = oracle_cols[0] if oracle_cols else None
        if not oc:
            return False
        for _, row in subset.iterrows():
            oracle_val = row.get(oc)
            for impl in deviant_cols:
                if row.get(impl) != oracle_val:
                    return True
        return False

    # Determine visible tests
    if focused_test:
        visible_tests = [focused_test] if focused_test in all_tests else all_tests
    elif deviant_only:
        visible_tests = [t for t in all_tests if test_has_deviant(t)]
    else:
        visible_tests = all_tests

    rows     = [(t, s) for t in visible_tests for s in all_steps]
    y_labels = [f"{t}·s{s}" for t, s in rows]
    x_labels = [short_label(i) for i in ordered]
    x_full   = ordered  # full impl IDs for tooltip

    def cell_color(impl, row_dict):
        cluster = impl_label.get(impl, "A")
        if cluster == "A":
            return ORACLE_COLOR
        oc = oracle_cols[0] if oracle_cols else None
        oracle_val = row_dict.get(oc) if oc else None
        val = row_dict.get(impl)
        return color_map.get(cluster, _SAFE[0]) if val != oracle_val else "#ffffff"

    z, hover = [], []
    custom = []  # customdata1 (full impl IDs) in hover
    for test, step in rows:
        rd = srm_df[(srm_df["test_id"] == test) & (srm_df["step_id"] == step)]
        row_dict = rd.iloc[0].to_dict() if not rd.empty else {}
        row_z, row_h, row_c = [], [], []  # customdata2: add row_c 
        for impl in ordered:
            c = cell_color(impl, row_dict)
            val = row_dict.get(impl, "N/A")
            row_z.append(color_to_num.get(c, 0))
            # Full impl ID in tooltip
            row_h.append(f"<b>{impl}</b><br>{val}")
            row_c.append([test, step, impl]) # customdata3: fit the real test_id, step_id, and complete impl_id 
        z.append(row_z)
        hover.append(row_h)
        custom.append(row_c) # customdata4: add to custom

    fig = go.Figure(go.Heatmap(
        z=z, x=x_labels, y=y_labels,
        text=hover, hovertemplate="%{text}<extra></extra>",
        customdata=custom,  # customdata5: Pass the customdata to the heatmap
        colorscale=colorscale, zmin=0, zmax=n - 1,
        showscale=False, xgap=1, ygap=1,
    ))
    if oracle_cols and deviant_cols:
        fig.add_vline(x=len(oracle_cols) - 0.5, line_width=2, line_color="#374151")

    # Add horizontal separator lines between different tests
    test_step_counts = {}
    for t, s in rows:
        test_step_counts[t] = test_step_counts.get(t, 0) + 1

    separator_y = -0.5
    for i, test in enumerate(visible_tests):
        separator_y += test_step_counts.get(test, 0)
        if i < len(visible_tests) - 1:
            fig.add_hline(
                y=separator_y,
                line_width=1, line_color="#d1d5db",
                line_dash="solid",
            )

    n_cols = len(ordered)
    fig_width = max(800, n_cols * 24 + 200)

    fig.update_layout(
        margin=dict(l=160, r=20, t=40, b=60),
        width=fig_width,
        height=max(420, len(y_labels) * 18 + 80),
        plot_bgcolor="#f9fafb", paper_bgcolor="#fff",
        xaxis=dict(side="top", tickfont=dict(size=9)),
        yaxis=dict(tickfont=dict(size=9), autorange="reversed"),
        clickmode="event",
        activeselection=dict(fillcolor="rgba(0,0,0,0)", opacity=1.0),
    )

    return fig, impl_label, color_map, cluster_sizes


# ── BE heatmap builder ────────────────────────────────────────────────────────

def build_be_heatmap(problem_id, n_runs, selected_impl=None):
    """Build the behavioral evolution matrix."""
    run_ids = BE_RUN_IDS[-n_runs:]
    run_labels = [BE_RUN_LABELS[r] for r in run_ids]

    df = be_cluster_per_run(conn, problem_id, run_ids)

    if df.empty:
        return go.Figure(), {}, {}

    impls = sorted(df['implementation_id'].unique().tolist())

    pivot = {}
    for _, row in df.iterrows():
        lbl = str(row['cluster_label']).replace("State ", "").replace("Cluster ", "").strip()
        pivot[(row['implementation_id'], row['run_id'])] = lbl

    clusters_df = behavioral_clustering(conn, problem_id, run_ids[0])
    global_color_map = make_color_map(len(clusters_df)) if not clusters_df.empty else {}

    ORACLE_COLOR = "#14b8a6" 
    TAILWIND_COLORS = [
        "#ef4444", "#3b82f6", "#f97316", "#10b981", 
        "#8b5cf6", "#ec4899", "#6366f1", "#f59e0b"
    ]

    unique_labels = sorted(list(set(pivot.values())))
    local_color_map = {}
    color_idx = 0
    for lbl in unique_labels:
        if lbl == "A" or lbl == "0" or lbl.lower() == "oracle":
            local_color_map[lbl] = ORACLE_COLOR
        else:
            local_color_map[lbl] = global_color_map.get(lbl, TAILWIND_COLORS[color_idx % len(TAILWIND_COLORS)])
            color_idx += 1

    unique_colors = ["#f9fafb"] + list(local_color_map.values())
    unique_colors = list(dict.fromkeys(unique_colors))
    color_to_num = {c: i for i, c in enumerate(unique_colors)}
    
    n = len(unique_colors)
    colorscale = []
    for i, c in enumerate(unique_colors):
        colorscale.append([i / n, c])
        colorscale.append([(i + 1) / n, c])

    z, hover, shapes = [], [], []
    x_labels = run_labels
    y_labels = [short_label(impl) for impl in impls]

    for row_i, impl in enumerate(impls):
        row_z, row_h = [], []
        for col_i, run_id in enumerate(run_ids):
            label = pivot.get((impl, run_id))
            if label is None:
                row_z.append(color_to_num["#f9fafb"])
                row_h.append(f"<b>{impl}</b><br>N/A")
            else:
                c = local_color_map.get(label, "#9ca3af")
                row_z.append(color_to_num.get(c, 0))
                row_h.append(f"<b>{impl}</b><br>Cluster {label}")
        z.append(row_z)
        hover.append(row_h)

    fig = go.Figure(go.Heatmap(
        z=z, x=x_labels, y=y_labels,
        customdata=hover,
        hovertemplate="%{customdata}<extra></extra>",
        colorscale=colorscale,
        # FIX：to avoid color change after clicking
        zmin=-0.5, zmax=n - 0.5,
        showscale=False,
        xgap=2, ygap=2,
    ))

    if selected_impl and selected_impl in impls:
        row_i = impls.index(selected_impl)
        shapes.append(dict(
            type="rect",
            x0=-0.5, x1=len(run_ids) - 0.5,
            y0=row_i - 0.5, y1=row_i + 0.5,
            line=dict(color="#000000", width=2),
            fillcolor="rgba(0,0,0,0)",
        ))

    fig.update_layout(
        shapes=shapes,
        margin=dict(l=100, r=20, t=60, b=40),
        height=max(400, len(impls) * 36 + 80),
        autosize=True,
        plot_bgcolor="#fff", paper_bgcolor="#fff",
        xaxis=dict(side="top", tickfont=dict(size=11, color="#6b7280")),
        yaxis=dict(tickfont=dict(size=10, color="#374151"), autorange="reversed"),
        clickmode="event",
        dragmode=False,
    )

    impl_cluster_map = {impl: pivot.get((impl, run_ids[0]), '?') for impl in impls}
    return fig, impl_cluster_map, local_color_map 

def build_be_right_panel(problem_id, selected_impl, n_runs, impl_cluster_map, color_map):
    panel = []
    run_ids = BE_RUN_IDS[-n_runs:]

    if selected_impl:
        panel.append(
            html.Div([
                html.Div("STEP DETAIL", style={"fontWeight": 700, "fontSize": 11, "color": "#6b7280"}),
                html.Button(
                    "✕ Close",
                    id="be-close-btn",
                    style={
                        "background": "transparent",
                        "border": "none",
                        "color": "#9ca3af",
                        "cursor": "pointer",
                        "fontSize": 10,
                        "fontWeight": 600,
                    }
                )
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "8px"})
        )
        all_states_df = be_cluster_per_run(conn, problem_id, run_ids)
        states = []
        for run_id in run_ids:
            row = all_states_df[
                (all_states_df['implementation_id'] == selected_impl) &
                (all_states_df['run_id'] == run_id)
            ]
            if not row.empty:
                val = str(row.iloc[0]['cluster_label']).replace("State ", "").replace("Cluster ", "").strip()
                states.append(val)
            else:
                states.append(None)

        ORACLE_COLOR = "#14b8a6"
        SAFE_COLORS = ["#ef4444", "#3b82f6", "#f97316", "#10b981", "#8b5cf6", "#ec4899", "#6366f1"]
        unique_states = sorted(list(set([s for s in states if s])))
        for i, s in enumerate(unique_states):
            if s not in color_map:
                color_map[s] = ORACLE_COLOR if s == "A" else SAFE_COLORS[i % len(SAFE_COLORS)]

        # Behavioral Journey
        panel.append(_section("BEHAVIORAL JOURNEY"))
        journey_items = []
        for i, (state, run_id) in enumerate(zip(states, run_ids)):
            if i > 0:
                journey_items.append(html.Span("→", style={"color": "#9ca3af", "fontSize": 10, "margin": "0 3px"}))
            
            bg_color = color_map.get(state, "#e5e7eb") if state else "#f3f4f6"
            journey_items.append(
                html.Div(
                    f"Cluster {state}" if state else "N/A",
                    style={
                        "padding": "5px 10px", "borderRadius": 6,
                        "background": bg_color,
                        "color": "#fff" if state else "#9ca3af",
                        "fontSize": 10, "fontWeight": 600,
                    },
                    title=BE_RUN_LABELS[run_id],
                )
            )
        
        panel.append(html.Div(journey_items, style={
            "display": "flex", "alignItems": "center", "flexWrap": "wrap",
            "gap": 2, "marginBottom": 16
        }))

        # Behavioral Shifts
        shifts = [
            (run_ids[i], states[i-1], states[i])
            for i in range(1, len(states))
            if states[i] and states[i-1] and states[i] != states[i-1]
        ]
        
        if shifts:
            panel.append(_section(f"BEHAVIORAL SHIFTS ({len(shifts)})"))
            for run_id, from_s, to_s in shifts:
                panel.append(html.Div([
                    html.Span(BE_RUN_LABELS[run_id],
                              style={"fontSize": 10, "color": "#6b7280", "marginRight": 8, "fontWeight": 600}),
                    html.Span(f"Cluster {from_s} → Cluster {to_s}",
                              style={"fontSize": 11, "color": "#374151", "fontWeight": 500}),
                ], style={"display": "flex", "alignItems": "center",
                          "padding": "6px 8px", "background": "#fff7ed",
                          "borderRadius": 5, "marginBottom": 4}))

            # Transition detail (use Timeline Accordion Cards)
            shift_run_id, shift_from, shift_to = shifts[0]
            shift_idx = run_ids.index(shift_run_id)
            run_before = run_ids[shift_idx - 1]

            detail_df = be_transition_detail(
                conn, problem_id, selected_impl, run_before, shift_run_id
            )

            if not detail_df.empty:
                panel += [
                    _divider(),
                    _section("TRANSITION DETAIL"),
                ]
                
                cards = []
                for _, r in detail_df.iterrows():
                    before_str = str(r.before_output)
                    after_str = str(r.after_output)
                    
                    status_is_changed = (r.status == "CHANGED")
                    status_bg = "#fff7ed" if status_is_changed else "#f0fdf4"
                    status_color = "#f97316" if status_is_changed else "#14b8a6"

                    cards.append(
                        html.Details([
                            html.Summary(
                                html.Div([
                                    html.Div(
                                        f"{r.test_id} · s{int(r.step_id)}",
                                        style={"fontWeight": 600, "fontSize": 11, "color": "#1f2937", "fontFamily": "Menlo,monospace"}
                                    ),
                                    html.Div(
                                        r.status,
                                        style={
                                            "background": status_bg,
                                            "color": status_color,
                                            "padding": "2px 8px",
                                            "borderRadius": "12px",
                                            "fontWeight": 700,
                                            "fontSize": "9px",
                                            "border": f"1px solid {status_color}33"
                                        }
                                    ),
                                ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}),
                                style={"cursor": "pointer", "padding": "10px", "userSelect": "none"}
                            ),
                            html.Div([
                                html.Div("Before", style={"fontWeight": 600, "color": "#6b7280", "marginBottom": "4px", "fontSize": 10}),
                                html.Pre(
                                    before_str,
                                    style={
                                        "whiteSpace": "pre-wrap",
                                        "wordBreak": "break-all",
                                        "background": "#f9fafb",
                                        "padding": "8px",
                                        "borderRadius": "4px",
                                        "fontSize": 9,
                                        "fontFamily": "Menlo,monospace",
                                        "color": "#374151",
                                        "margin": "0 0 10px 0"
                                    }
                                ),
                                html.Div("After", style={"fontWeight": 600, "marginBottom": "4px", "color": "#f97316", "fontSize": 10}),
                                html.Pre(
                                    after_str,
                                    style={
                                        "whiteSpace": "pre-wrap",
                                        "wordBreak": "break-all",
                                        "background": "#fff7ed",
                                        "padding": "8px",
                                        "borderRadius": "4px",
                                        "fontSize": 9,
                                        "fontFamily": "Menlo,monospace",
                                        "color": "#f97316",
                                        "margin": "0"
                                    }
                                ),
                            ], style={"padding": "0 10px 10px 10px", "borderTop": "1px solid #f3f4f6"})
                        ], className="be-transition-card", style={
                            "border": "1px solid #e5e7eb",
                            "borderRadius": "6px",
                            "marginBottom": "8px",
                            "background": "white",
                        })
                    )

                changed = len(detail_df[detail_df['status'] == 'CHANGED'])
                stable  = len(detail_df[detail_df['status'] == 'STABLE'])
                
                panel.append(html.Div(
                    cards,
                    style={"maxHeight": "280px", "overflowY": "auto", "paddingRight": "4px"}
                ))
                
                panel.append(html.Div(
                    f"{changed} CHANGED · {stable} STABLE",
                    style={"fontSize": 10, "color": "#6b7280", "marginTop": 6}
                ))
        else:
            panel.append(html.Div(
                "No behavioral shifts — stable across all runs.",
                style={"fontSize": 11, "color": "#9ca3af", "marginBottom": 12}
            ))

        panel.append(_divider())

    # Evolution Summary
    total = len(impl_cluster_map)
    run_ids = BE_RUN_IDS[-n_runs:]
    all_states_df = be_cluster_per_run(conn, problem_id, run_ids)

    stable_count = 0
    if not all_states_df.empty:
        for impl in impl_cluster_map:
            impl_df = all_states_df[all_states_df['implementation_id'] == impl]
            if len(impl_df) == n_runs and impl_df['cluster_label'].nunique() == 1:
                stable_count += 1

    pct = round(stable_count / total * 100) if total else 0
    na_count = sum(
        1 for impl in impl_cluster_map
        if any(
            all_states_df[
                (all_states_df['implementation_id'] == impl) &
                (all_states_df['run_id'] == r)
            ].empty
            for r in run_ids
        ) if not all_states_df.empty
    )

    panel += [
        _section("EVOLUTION SUMMARY"),
        html.Div(f"{pct}%", style={
            "fontSize": 28, "fontWeight": 700,
            "color": "#14b8a6" if pct >= 75 else "#f97316",
        }),
        html.Div(f"{stable_count} of {total} implementations stable across all runs",
                 style={"fontSize": 11, "color": "#6b7280", "marginBottom": 8}),
        html.Div(html.Div(style={
            "height": 8, "borderRadius": 4, "background": "#14b8a6",
            "width": f"{pct}%",
        }), style={"height": 8, "borderRadius": 4, "background": "#e5e7eb",
                   "marginBottom": 12}),
    ]

    if na_count > 0:
        panel.append(html.Div(
            f"⚠ {na_count} implementation{'s' if na_count > 1 else ''} "
            "not found in latest run (N/A)",
            style={"fontSize": 11, "color": "#6b7280", "padding": "6px 8px",
                   "background": "#f9fafb", "borderRadius": 5,
                   "border": "1px solid #e5e7eb", "marginBottom": 12}
        ))

    # Cluster Legend
    panel.append(_divider())
    panel.append(_section("CLUSTER LEGEND"))
    
    sorted_legend_clusters = sorted(color_map.keys(), key=lambda x: (x != "A", x))
    for cl in sorted_legend_clusters:
        cl_color = color_map.get(cl, "#9ca3af")
        is_oracle = (cl == "A")
        label = f"Cluster {cl}" + ("  —  ORACLE" if is_oracle else "")
        panel.append(html.Div([
            html.Span("■ ", style={"color": cl_color, "fontSize": 14, "marginRight": 4}),
            html.Span(label, style={"fontSize": 12, "fontWeight": 600 if is_oracle else 400, "color": "#374151"}),
        ], style={"marginBottom": 4, "display": "flex", "alignItems": "center"}))

    return panel

# ── Panel helpers ─────────────────────────────────────────────────────────────

def _section(title, note=None):
    children = [title]
    if note:
        children.append(
            html.Span(note, style={"fontSize": 9, "color": "#9ca3af",
                                   "marginLeft": 4, "fontWeight": 400})
        )
    return html.Div(children, style={
        "fontSize": 10, "color": "#9ca3af", "letterSpacing": "0.08em",
        "fontWeight": 600, "marginBottom": 8,
    })

def _divider():
    return html.Hr(style={"borderColor": "#e5e7eb", "margin": "12px 0"})

def _chip(value, label, color):
    return html.Div([
        html.Div(value, style={"fontSize": 20, "fontWeight": 700, "color": color}),
        html.Div(label, style={"fontSize": 10, "color": "#6b7280"}),
    ], style={"flex": 1, "background": "#f9fafb", "borderRadius": 6,
              "padding": "8px 10px", "border": "1px solid #e5e7eb"})


def build_right_panel(problem_id, selected_step, selected_clusters,
                      impl_label, color_map, cluster_sizes, sv_df):
    panel = [html.Div(id="click-detail-container")]

    """
    # ── Step output comparison ────────────────────────────────────────────────
    if selected_step:
        test    = selected_step.get("test")
        step_id = selected_step.get("step")
        if test is not None and step_id is not None:
            df = get_outputs_for_step(problem_id, test, int(step_id))

            # Group outputs by cluster (first value per cluster)
            cluster_outputs = {}
            for _, row in df.iterrows():
                cl = impl_label.get(row["implementation_id"], "?")
                if cl not in cluster_outputs:
                    cluster_outputs[cl] = str(row["output"]) if row["output"] is not None else "null"

            oracle_val = cluster_outputs.get("A", "—")
            all_same   = all(v == oracle_val for v in cluster_outputs.values())

            panel += [
                _section("STEP OUTPUT"),
                html.Div(f"{test}() · s{step_id}",
                         style={"fontWeight": 600, "fontSize": 11, "marginBottom": 4}),
            ]
            if all_same:
                panel.append(
                    html.Div("All implementations match oracle at this step.",
                             style={"fontSize": 11, "color": "#9ca3af"})
                )
            else:
                for letter in sorted(cluster_outputs.keys()):
                    val      = cluster_outputs[letter]
                    is_oracle = letter == "A"
                    size     = cluster_sizes.get(letter, 0)
                    shown    = (not selected_clusters or
                                letter in selected_clusters or letter == "A")
                    if not shown:
                        continue
                    panel.append(html.Div([
                        html.Div([
                            html.Div(style={
                                "width": 7, "height": 7, "borderRadius": 2,
                                "background": color_map.get(letter, "#9ca3af"),
                                "flexShrink": 0,
                            }),
                            html.Span("Oracle" if is_oracle else f"Cluster {letter}",
                                      style={"fontSize": 10, "color": "#6b7280",
                                             "minWidth": 65}),
                        ], style={"display": "flex", "alignItems": "center", "gap": 4}),
                        html.Span(val, style={
                            "fontFamily": "Menlo, Consolas, monospace",
                            "fontSize": 11, "color": "#111827",
                            "wordBreak": "break-all", "flex": 1,
                        }),
                        html.Span(str(size), style={"fontSize": 10, "color": "#9ca3af",
                                                     "flexShrink": 0}),
                    ], style={
                        "display": "flex", "alignItems": "baseline", "gap": 8,
                        "padding": "5px 8px", "borderRadius": 5, "marginBottom": 3,
                        "background": "#f0fdfa" if is_oracle else "#fff7ed",
                    }))

            panel.append(_divider())
    """
    
    # ── Cluster overview ──────────────────────────────────────────────────────
    total         = sum(cluster_sizes.values())
    oracle_count  = cluster_sizes.get("A", 0)
    deviant_count = total - oracle_count
    deviant_score = deviant_count / total if total else 0.0

    panel += [
        _section("CLUSTER OVERVIEW"),
        html.Div([
            _chip(str(total),         "Total",  "#111827"),
            _chip(str(oracle_count),  "Oracle", "#14b8a6"),
            _chip(str(deviant_count), "Deviant", "#f97316"),
        ], style={"display": "flex", "gap": 8, "marginBottom": 16}),
        _divider(),
        _section("CLUSTER LEGEND"),
    ]
    for letter, size in sorted(cluster_sizes.items()):
        shown = (not selected_clusters or letter in selected_clusters or letter == "A")
        label = f"Cluster {letter}" + ("  —  ORACLE" if letter == "A" else "")
        panel.append(html.Div([
            html.Span("■ ", style={"color": color_map.get(letter, "#9ca3af")}),
            html.Span(label, style={"fontSize": 12}),
            html.Span(f"  {size}", style={"fontSize": 11, "color": "#6b7280"}),
        ], style={"marginBottom": 3, "opacity": "1" if shown else "0.3"}))

    panel += [
        _divider(),
        _section("DEVIANT SCORE"),
        html.Div(f"{deviant_score:.1%}", style={
            "fontSize": 28, "fontWeight": 700,
            "color": "#f97316" if deviant_score > 0.3 else "#374151",
        }),
        html.Div(f"{deviant_count} of {total} implementations deviate",
                 style={"fontSize": 11, "color": "#6b7280", "marginBottom": 16}),
        _divider(),
        _section("STEP VULNERABILITY", "click to inspect"),
    ]

    if not sv_df.empty:
        for _, r in sv_df.head(5).iterrows():
            is_active = (selected_step and
                         selected_step.get("test") == r.test_id and
                         selected_step.get("step") == int(r.step_id))
            w = min(100, int(r.deviant_count) * 20)
            
            import pandas as pd
            

            panel.append(html.Div([
                html.Div(f"{r.test_id}·s{int(r.step_id)}",
                         style={"fontSize": 11, "marginBottom": 2}),
                html.Div(html.Div(style={
                    "height": 6, "borderRadius": 3,
                    "background": "#f97316", "width": f"{w}%",
                }), style={"background": "#f3f4f6", "borderRadius": 3, "marginBottom": 2}),
                html.Div(f"{int(r.deviant_count)} deviants",
                         style={"fontSize": 10, "color": "#6b7280"}),
            ],
            id={"type": "sv-item", "test": r.test_id, "step": int(r.step_id)},
            style={
                "marginBottom": 4, "cursor": "pointer",
                "padding": "5px 6px", "borderRadius": 5,
                "background": "#fff7ed" if is_active else "transparent",
                "border": f"1px solid {'#f97316' if is_active else 'transparent'}",
            }))
    else:
        panel.append(html.Div("No deviant steps.",
                              style={"fontSize": 11, "color": "#9ca3af"}))

    return panel


# ── Layout ────────────────────────────────────────────────────────────────────

app = dash.Dash(__name__, title="LASSO Visual Analytics",
                suppress_callback_exceptions=True)

def _nav():
    return html.Div([
        html.Span("LASSO", style={"fontWeight": 700, "color": "#14b8a6", "fontSize": 17}),
        html.Span(" · Visual Analytics", style={"color": "#374151", "fontSize": 15}),
        html.Div([
            html.Span("VISUAL ANALYTICS", id="tab-va-nav", style={
                "color": "#14b8a6", "fontSize": 11, "fontWeight": 700,
                "borderBottom": "2px solid #14b8a6", "paddingBottom": 2,
                "cursor": "pointer", "marginRight": 16,
            }),
            html.Span("BEHAVIORAL EVOLUTION", id="tab-be-nav", style={
                "color": "#9ca3af", "fontSize": 11, "cursor": "pointer",
            }),
        ], style={"marginLeft": "auto", "display": "flex", "alignItems": "center"}),
    ], style={"display": "flex", "alignItems": "center", "gap": 8,
              "padding": "10px 20px", "borderBottom": "1px solid #e5e7eb",
              "background": "#fff"})

app.layout = html.Div([
    dcc.Store(id="selected-step-store", data=None),
    dcc.Store(id="focused-test-store",  data=None),
    dcc.Store(id="active-tab",          data="va"),
    dcc.Store(id="be-selected-impl",    data=None),

    _nav(),

    # ── VA TAB ────────────────────────────────────────────────────────────────
    html.Div(id="panel-va", children=[
        html.Div([
            html.Div([
                # Card header
                html.Div([
                    html.Div([
                        html.Div("SRM Visual Analytics",
                                 style={"fontWeight": 600, "fontSize": 15}),
                        html.Div(id="mode-subtitle",
                                 style={"fontSize": 12, "color": "#6b7280"}),
                    ]),
                    dcc.RadioItems(
                        id="mode-toggle",
                        options=[
                            {"label": " Diff", "value": "developer"},
                            {"label": " Cluster", "value": "researcher"},
                        ],
                        value="researcher", inline=True,
                        inputStyle={"marginRight": 4},
                        labelStyle={"fontSize": 12, "padding": "4px 10px",
                                    "cursor": "pointer"},
                    ),
                ], style={"display": "flex", "justifyContent": "space-between",
                          "alignItems": "flex-start", "padding": "16px 20px",
                          "borderBottom": "1px solid #e5e7eb", "flexShrink": 0}),

                # Filter bar
                html.Div([
                    html.Div([
                        html.Label("Problem", style={"fontSize": 11, "color": "#6b7280"}),
                        dcc.Dropdown(
                            id="problem-dd",
                            options=[{"label": p, "value": p} for p in PROBLEMS],
                            value=PROBLEMS[0] if PROBLEMS else None,
                            clearable=False, style={"width": 300, "fontSize": 12},
                        ),
                    ], style={"display": "flex", "flexDirection": "column", "gap": 2}),

                    html.Div(id="cluster-filters", children=[
                        html.Div([
                            html.Label("Cluster", style={"fontSize": 11, "color": "#6b7280"}),
                            dcc.Dropdown(
                                id="cluster-dd", options=[], value=None,
                                multi=True, placeholder="All clusters",
                                style={"width": 260, "fontSize": 12},
                            ),
                        ], style={"display": "flex", "flexDirection": "column", "gap": 2}),
                        html.Div([
                            dcc.Checklist(
                                id="deviant-only",
                                options=[{"label": " Deviant Tests Only", "value": "yes"}],
                                value=[],
                                inputStyle={"accentColor": "#14b8a6",
                                            "width": 13, "height": 13, "marginRight": 4},
                                labelStyle={"fontSize": 12, "color": "#374151",
                                            "cursor": "pointer"},
                            ),
                        ], style={"display": "flex", "alignItems": "flex-end",
                                  "paddingBottom": 3}),
                    ], style={"display": "flex", "gap": 16, "alignItems": "flex-end"}),

                    html.Div([
                        html.Div([
                            html.Label("Baseline run (auto-detected previous run)",
                                       id="baseline-label",
                                       style={"fontSize": 11, "color": "#6b7280"}),
                            dcc.Dropdown(
                                id="baseline-dd", options=_run_options,
                                value=_baseline_default,
                                clearable=False, style={"width": 300, "fontSize": 12},
                            ),
                        ], style={"display": "flex", "flexDirection": "column", "gap": 2}),
                        html.Div([
                            html.Label("Target run (current)",
                                       style={"fontSize": 11, "color": "#6b7280"}),
                            dcc.Dropdown(
                                id="target-dd", options=_run_options,
                                value=_target_default,
                                clearable=False, style={"width": 300, "fontSize": 12},
                            ),
                        ], style={"display": "flex", "flexDirection": "column", "gap": 2}),
                    ], id="diff-filters",
                       style={"display": "flex", "gap": 16, "alignItems": "flex-end",
                              "visibility": "hidden", "height": 0, "overflow": "hidden",
                              "padding": 0, "margin": 0, "pointerEvents": "none"}),

                ], style={"padding": "10px 20px", "borderBottom": "1px solid #e5e7eb",
                          "display": "flex", "gap": 16, "alignItems": "flex-end",
                          "flexWrap": "wrap", "flexShrink": 0}),

                html.Div(
                    dcc.Loading(
                        dcc.Graph(id="heatmap", config={"displayModeBar": False}),
                        type="circle", color="#14b8a6",
                    ),
                    style={"overflow": "auto", "flex": 1},
                ),

            ], style={"flex": 1, "background": "#fff", "borderRadius": 8,
                      "border": "1px solid #e5e7eb", "minWidth": 0,
                      "display": "flex", "flexDirection": "column",
                      "overflow": "hidden"}),

            html.Div(id="right-panel", style={
                "width": "25vw", "flexShrink": 0, "background": "#fff",
                "borderRadius": 8, "border": "1px solid #e5e7eb",
                "padding": 16, "overflowY": "auto",
            }),
        ], style={"display": "flex", "gap": 12, "padding": 16,
                  "background": "#f3f4f6",
                  "height": "calc(100vh - 48px)",
                  "overflow": "hidden"}),
    ]),

    # ── BE TAB ────────────────────────────────────────────────────────────────
    html.Div(id="panel-be", style={"display": "none"}, children=[
        
        html.Div([
            html.Div([
                html.Div([
                    html.Div([
                        html.Div("Behavioral Evolution Matrix",
                                 style={"fontWeight": 600, "fontSize": 15}),
                        html.Div("Click an implementation row to inspect its behavioral state timeline",
                                 style={"fontSize": 12, "color": "#6b7280"}),
                    ]),
                ], style={"display": "flex", "justifyContent": "space-between",
                          "alignItems": "flex-start", "padding": "16px 20px",
                          "borderBottom": "1px solid #e5e7eb", "flexShrink": 0}),

                html.Div([
                    html.Div([
                        html.Label("Problem", style={"fontSize": 11, "color": "#6b7280"}),
                        dcc.Dropdown(
                            id="be-problem-dd",
                            options=[{"label": p, "value": p} for p in BE_PROBLEMS],
                            value=BE_PROBLEMS[0] if BE_PROBLEMS else None,
                            clearable=False, style={"width": 280, "fontSize": 12},
                        ),
                    ], style={"display": "flex", "flexDirection": "column", "gap": 2}),
                    html.Div([
                        html.Label("Recent Runs", style={"fontSize": 11, "color": "#6b7280"}),
                        dcc.Dropdown(
                            id="be-runs-dd",
                            options=[
                                {"label": "Last 5", "value": 5},
                                {"label": "Last 3", "value": 3},
                            ],
                            value=5, clearable=False,
                            style={"width": 120, "fontSize": 12},
                        ),
                    ], style={"display": "flex", "flexDirection": "column", "gap": 2}),
                ], style={"padding": "10px 20px", "borderBottom": "1px solid #e5e7eb",
                          "display": "flex", "gap": 16, "alignItems": "flex-end",
                          "flexShrink": 0}),

                html.Div(
                    dcc.Loading(
                        dcc.Graph(
                            id="be-heatmap", 
                            config={"displayModeBar": False}, 
                            style={"height": "100%", "width": "100%"} 
                        ),
                        type="circle", color="#14b8a6",
                    ),
                    style={"overflow": "auto", "flex": 1, "cursor": "pointer"},
                ),

            ], style={"flex": 1, "background": "#fff", "borderRadius": 8,
                      "border": "1px solid #e5e7eb", "minWidth": 0,
                      "display": "flex", "flexDirection": "column",
                      "overflow": "hidden"}),

            html.Div(id="be-right-panel", style={
                "width": "33vw", "flexShrink": 0, "background": "#fff",
                "borderRadius": 8, "border": "1px solid #e5e7eb",
                "padding": 16, "overflowY": "auto",
            }, children=[
                html.Div("Click an implementation row to view its behavioral journey.",
                         style={"fontSize": 12, "color": "#9ca3af"}),
            ]),
            
        
        ], style={"display": "flex", "gap": 12, "padding": 16,
                  "background": "#f3f4f6",
                  "height": "calc(100vh - 48px)",
                  "overflow": "hidden"})
    ]),

], style={"fontFamily": "'Inter', 'Segoe UI', sans-serif"})


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("cluster-filters", "style"),
    Output("diff-filters",    "style"),
    Input("mode-toggle", "value"),
)
def toggle_filters(mode):
    show = {"display": "flex", "gap": 16, "alignItems": "flex-end"}
    hide = {"display": "flex", "gap": 16, "alignItems": "flex-end",
            "visibility": "hidden", "height": 0, "overflow": "hidden",
            "padding": 0, "margin": 0, "pointerEvents": "none"}
    if mode == "developer":
        return hide, show
    return show, hide


@callback(
    Output("baseline-dd", "options"),
    Output("baseline-dd", "value"),
    Output("target-dd",   "options"),
    Output("target-dd",   "value"),
    Input("problem-dd", "value"),
)
def update_run_options(problem_id):
    if not problem_id:
        return [], None, [], None
    runs = run_list(conn, problem_id)
    options = [{"label": r[:20] + "..." if len(r) > 20 else r, "value": r}
               for r in runs]
    baseline = runs[0] if len(runs) > 0 else None
    target   = runs[1] if len(runs) > 1 else None
    return options, baseline, options, target


@callback(
    Output("mode-subtitle", "children"),
    Input("mode-toggle", "value"),
)
def update_subtitle(mode):
    if mode == "developer":
        return "Diff view — identify regressions and fixes between two execution runs"
    return "Cluster view — visualize SRM behavior patterns and cluster implementations"


@callback(
    Output("cluster-dd", "options"),
    Output("cluster-dd", "value"),
    Input("problem-dd", "value"),
)
def update_cluster_options(problem_id):
    if not problem_id:
        return [], None
    clusters_df = behavioral_clustering(conn, problem_id)
    options = []
    for i, row in clusters_df.iterrows():
        letter = chr(ord("A") + i) if i < 26 else "Z"
        label = (f"Cluster A — ORACLE ({int(row['cluster_size'])} impls)"
                 if letter == "A"
                 else f"Cluster {letter} ({int(row['cluster_size'])} impls)")
        options.append({"label": label, "value": letter})
    return options, None


@callback(
    Output("selected-step-store", "data"),
    Output("focused-test-store",  "data"),
    Input("heatmap", "clickData"),
    Input({"type": "sv-item", "test": ALL, "step": ALL}, "n_clicks"),
    Input("problem-dd", "value"),
    Input("cluster-dd", "value"),
    Input("deviant-only", "value"),
)
def update_selected_step(click_data, sv_clicks, problem_id, cluster_val, deviant_only):
    from dash import ctx
    triggered = ctx.triggered_id

    # Reset on filter changes
    if triggered in ("problem-dd", "cluster-dd", "deviant-only"):
        return None, None

    # SV item clicked → focus heatmap on that test, show step output
    if isinstance(triggered, dict) and triggered.get("type") == "sv-item":
        return ({"test": triggered["test"], "step": triggered["step"]},
                triggered["test"])

    # Heatmap cell clicked → 双重保险解析
    if click_data:
        point = click_data["points"][0]
        custom = point.get("customdata", [])
        x_label = point.get("x")
        if len(custom) >= 3:
            return {"test": custom[0], "step": int(custom[1]), "impl": x_label}, None
        # 兜底：直接从 y 轴文字解析（例如 "testSumNullList()·s0"）
        y_val = point.get("y", "")
        if "·s" in y_val:
            parts = y_val.rsplit("·s", 1)
            try:
                return {"test": parts[0], "step": int(parts[1]), "impl": x_label}, None
            except ValueError:
                pass

    return None, None


@callback(
    Output("focused-test-store", "data", allow_duplicate=True),
    Output("selected-step-store", "data", allow_duplicate=True),
    Input("clear-focus-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_focus(n):
    return None, None


@callback(
    Output("heatmap", "figure"),
    Output("right-panel", "children"),
    Input("problem-dd", "value"),
    Input("mode-toggle", "value"),
    Input("cluster-dd", "value"),
    Input("deviant-only", "value"),
    Input("selected-step-store", "data"),
    Input("focused-test-store",  "data"),
    Input("baseline-dd", "value"),
    Input("target-dd",   "value"),
)
def update(problem_id, mode, cluster_val, deviant_only_val,
           selected_step, focused_test, baseline_run, target_run):
    if not problem_id:
        return go.Figure(), html.Div("Select a problem.")

    from dash import ctx
    import pandas as pd
    triggered_id = ctx.triggered_id

    # Core fix 1: Clear selected_step immediately when mode toggles to prevent highlight carry-over
    if triggered_id == "mode-toggle":
        selected_step = None

    # ==========================
    # 1. DEVELOPER (DIFF) MODE
    # ==========================
    if mode == "developer":
        if not baseline_run or not target_run:
            empty = go.Figure()
            empty.update_layout(
                plot_bgcolor="#f9fafb", paper_bgcolor="#fff",
                xaxis=dict(visible=False), yaxis=dict(visible=False),
                annotations=[dict(text="Select baseline and target runs above.",
                                  xref="paper", yref="paper", x=0.5, y=0.5,
                                  showarrow=False, font=dict(size=13, color="#6b7280"))],
                height=400,
            )
            return empty, [_section("DIFF VIEW"), html.Div("Select two runs to compare.",
                           style={"fontSize": 12, "color": "#6b7280"})]

        if baseline_run == target_run:
            empty = go.Figure()
            empty.update_layout(plot_bgcolor="#f9fafb", paper_bgcolor="#fff",
                                 height=200, xaxis=dict(visible=False),
                                 yaxis=dict(visible=False))
            return empty, [_section("DIFF VIEW"),
                           html.Div("Baseline and target must be different runs.",
                                    style={"fontSize": 12, "color": "#f97316"})]

        fig, impl_label, reg, fix, drift, stable = build_diff_heatmap(
            problem_id, baseline_run, target_run
        )

        panel = []

        # ==========================================
        # 1. 选中状态处理（Step Detail 放在最上面）
        # ==========================================
        if selected_step and isinstance(selected_step, dict):
            test_val = selected_step.get("test")
            step_val = selected_step.get("step")
            impl_val = selected_step.get("impl")
            
            if test_val is not None and step_val is not None:
                # --- 图表高亮：仅高亮行和特定 Cell，取消列高亮 ---
                y_val = f"{test_val}·s{step_val}"
                if "data" in fig and len(fig["data"]) > 0:
                    trace = fig["data"][0]
                    x_labels_current = getattr(trace, "x", [])
                    y_labels_current = getattr(trace, "y", [])
                    
                    try:
                        row_idx = list(y_labels_current).index(y_val) if y_labels_current else None
                        col_idx = list(x_labels_current).index(impl_val) if impl_val and impl_val in x_labels_current else None
                        
                        if row_idx is not None and col_idx is not None:
                            import numpy as np
                            z_matrix = getattr(trace, "z", [])
                            rows_len = len(z_matrix)
                            cols_len = len(z_matrix[0]) if rows_len > 0 else 0
                            
                            highlight_z = np.zeros((rows_len, cols_len))
                            highlight_z[row_idx, :] = 1  # 仅高亮当前行
                            # highlight_z[:, col_idx] = 1  # <-- 已注释掉：不再高亮当前列
                            highlight_z[row_idx, col_idx] = 2 # 加深焦点 Cell
                            
                            fig.add_trace(
                                go.Heatmap(
                                    z=highlight_z.tolist(),
                                    x=x_labels_current,
                                    y=y_labels_current,
                                    colorscale=[
                                        [0, "rgba(0,0,0,0)"],
                                        [0.5, "rgba(253, 224, 71, 0.25)"],  # 行高亮
                                        [1.0, "rgba(250, 204, 21, 0.45)"],  # Cell 高亮
                                    ],
                                    showscale=False,
                                    hoverinfo="skip",
                                    xgap=1,
                                    ygap=1,
                                )
                            )
                    except (ValueError, IndexError):
                        pass

                # --- 渲染右侧 STEP DETAIL（位于顶部）---
                try:
                    clusters_df = behavioral_clustering(conn, problem_id, baseline_run)
                    oracle_members = sorted(list(clusters_df.iloc[0]["members"])) if not clusters_df.empty else []
                    full_diff_df = diff_view(conn, problem_id, baseline_run, target_run, oracle_members)
                    
                    detail_df = full_diff_df[
                        (full_diff_df["test_id"] == test_val) & 
                        (full_diff_df["step_id"] == int(step_val))
                    ]
                    
                    step_reg_count = 0
                    step_fix_count = 0
                    rows = []
                    
                    if not detail_df.empty:
                        # 统计当前 Step 的 Regression 和 Fix 数量
                        step_reg_count = int((detail_df["status"] == "REGRESSION").sum())
                        step_fix_count = int((detail_df["status"] == "FIX").sum())

                        for _, r in detail_df.iterrows():
                            status_color = {
                                "FIX": "#22c55e",
                                "REGRESSION": "#ef4444",
                                "DRIFT": "#f97316",
                                "STABLE": "#9ca3af"
                            }.get(r.status, "#9ca3af")
                            
                            rows.append(html.Tr([
                                html.Td(str(r.implementation_id),
                                        style={"fontSize": 10, "padding": "3px 4px", "fontWeight": 600}),
                                html.Td(str(r.baseline_output)[:20],
                                        style={"fontFamily": "Menlo,monospace", "fontSize": 9,
                                               "padding": "3px 4px", "color": "#374151"}),
                                html.Td(str(r.target_output)[:20],
                                        style={"fontFamily": "Menlo,monospace", "fontSize": 9,
                                               "padding": "3px 4px", "color": status_color}),
                                html.Td(r.status,
                                        style={"fontSize": 9, "padding": "3px 4px",
                                               "color": status_color, "fontWeight": 600}),
                            ]))

                    # 带有统计数据和关闭按钮的表头
                    header_ui = html.Div([
                        html.Div([
                            html.Div(f"{test_val}() · s{step_val}", style={"fontWeight": 600, "fontSize": 12}),
                            html.Div([
                                html.Span(f"{step_reg_count} Regressions", style={"color": "#ef4444", "fontSize": 10, "marginRight": 8}),
                                html.Span(f"{step_fix_count} Fixes", style={"color": "#22c55e", "fontSize": 10}),
                            ], style={"marginTop": 2})
                        ]),
                        html.Button("✖ Close", id="clear-diff-selection-btn", 
                                    style={"border": "none", "background": "transparent", "cursor": "pointer", 
                                           "color": "#9ca3af", "fontSize": 10, "padding": 0})
                    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start", "marginBottom": 8})

                    panel.extend([
                        _section("STEP DETAIL"),
                        header_ui
                    ])

                    if rows:
                        panel.append(html.Table(
                            [html.Tr([html.Th(h, style={"fontSize": 9, "color": "#9ca3af",
                                                         "padding": "3px 4px", "textAlign": "left",
                                                         "borderBottom": "1px solid #e5e7eb"})
                                       for h in ["Impl", "Baseline", "Target", "Status"]])]
                            + rows,
                            style={"width": "100%", "borderCollapse": "collapse"}
                        ))
                    else:
                        panel.append(html.Div("No output data available for this step.", style={"fontSize": 10, "color": "#6b7280"}))
                    
                    panel.append(_divider())

                except Exception as e:
                    panel.append(html.Div("Error loading detail data.", style={"fontSize": 10, "color": "#ef4444"}))
                    panel.append(_divider())

        # ==========================================
        # 2. DIFF SUMMARY 和 LEGEND (常规内容)
        # ==========================================
        panel.extend([
            _section("DIFF SUMMARY"),
            html.Div([
                _chip(str(reg),    "REGRESSION", "#ef4444"),
                _chip(str(fix),    "FIX",        "#22c55e"),
                _chip(str(drift),  "DRIFT",      "#f97316"),
                _chip(str(stable), "STABLE",     "#9ca3af"),
            ], style={"display": "flex", "gap": 6, "marginBottom": 16, "flexWrap": "wrap"}),
            
            _divider(),
            _section("LEGEND"),
            *[html.Div([
                html.Span("■ ", style={"color": DIFF_COLORS[s]}),
                html.Span(s, style={"fontSize": 12}),
                html.Span({"REGRESSION": " — oracle output lost",
                           "FIX":        " — oracle output gained",
                           "DRIFT":      " — output changed, no oracle shift",
                           "STABLE":     " — unchanged"}[s],
                          style={"fontSize": 10, "color": "#6b7280"}),
            ], style={"marginBottom": 4}) for s in ["REGRESSION","FIX","DRIFT","STABLE"]],
            _divider(),
            
            # --- 3. 修改为4行布局，完整显示 Hash ---
            html.Div("Baseline:", style={"fontSize": 11, "color": "#6b7280"}),
            html.Div(baseline_run, style={"fontSize": 11, "color": "#374151", "wordBreak": "break-all", "fontFamily": "Menlo,monospace", "marginBottom": 6}),
            
            html.Div("Target:", style={"fontSize": 11, "color": "#6b7280"}),
            html.Div(target_run, style={"fontSize": 11, "color": "#374151", "wordBreak": "break-all", "fontFamily": "Menlo,monospace"}),
        ])
        
        return fig, panel

    # ==========================
    # 2. CLUSTER MODE
    # ==========================
    selected_clusters = set(cluster_val) if cluster_val else None
    deviant_only      = bool(deviant_only_val)

    runs = run_list(conn, problem_id)
    baseline_run_for_sv = runs[0] if runs else None
    clusters_df_full = behavioral_clustering(conn, problem_id, baseline_run_for_sv)
    if clusters_df_full.empty:
        return go.Figure(), []
    oracle_members = sorted(list(clusters_df_full.iloc[0]["members"]))
    sv_df = step_vulnerability(conn, problem_id, baseline_run_for_sv, oracle_members)

    fig, impl_label, color_map, cluster_sizes = build_heatmap(
        problem_id, selected_clusters, deviant_only, focused_test
    )
    # Generate basic right panel content（Overview and Legend）
    panel = build_right_panel(
        problem_id, selected_step, selected_clusters,
        impl_label, color_map, cluster_sizes, sv_df
    )
    
    # ==========================================
    # 核心修改：Cluster 模式下的图表高亮与右侧面板注入
    # ==========================================
    if selected_step and isinstance(selected_step, dict):
        test_val = selected_step.get("test")
        step_val = selected_step.get("step")
        impl_val = selected_step.get("impl")
        
        if test_val is not None and step_val is not None:
            y_val = f"{test_val}·s{step_val}"
            
            # --- 1. 图表高亮（仅高亮当前行和焦点 Cell，取消列高亮） ---
            if "data" in fig and len(fig["data"]) > 0:
                trace = fig["data"][0]
                x_labels_current = getattr(trace, "x", [])
                y_labels_current = getattr(trace, "y", [])
                
                try:
                    row_idx = list(y_labels_current).index(y_val) if y_labels_current else None
                    col_idx = list(x_labels_current).index(impl_val) if impl_val and impl_val in x_labels_current else None
                    
                    if row_idx is not None and col_idx is not None:
                        import numpy as np
                        z_matrix = getattr(trace, "z", [])
                        rows_len = len(z_matrix)
                        cols_len = len(z_matrix[0]) if rows_len > 0 else 0
                        
                        highlight_z = np.zeros((rows_len, cols_len))
                        highlight_z[row_idx, :] = 1  # 仅高亮当前行
                        highlight_z[row_idx, col_idx] = 2 # 加深焦点 Cell
                        
                        fig.add_trace(
                            go.Heatmap(
                                z=highlight_z.tolist(),
                                x=x_labels_current,
                                y=y_labels_current,
                                colorscale=[
                                    [0, "rgba(0,0,0,0)"],
                                    [0.5, "rgba(253, 224, 71, 0.25)"],  # 行高亮浅黄
                                    [1.0, "rgba(250, 204, 21, 0.45)"],  # Cell 焦点深黄
                                ],
                                showscale=False,
                                hoverinfo="skip",
                                xgap=1,
                                ygap=1,
                            )
                        )
                except (ValueError, IndexError):
                    pass

            # --- 2. Detail Content：group by Cluster ---
            try:
                cursor = conn.cursor()
                query = f"""
                    SELECT implementation_id, CAST(output AS VARCHAR) AS output
                    FROM observations 
                    WHERE problem_id = '{problem_id}'
                      AND run_id = '{baseline_run_for_sv}' 
                      AND test_id = '{test_val}' 
                      AND step_id = {int(step_val)}
                """
                step_df = cursor.execute(query).fetchdf()
                cursor.close()
                
                if step_df is None or step_df.empty:
                    import pandas as pd
                    step_df = pd.DataFrame(columns=["implementation_id", "output"])

                cluster_data = {}
                for _, row in step_df.iterrows():
                    impl_id = row["implementation_id"]
                    out_val = row["output"]
                    cl_letter = impl_label.get(impl_id, "?")
                    
                    if cl_letter not in cluster_data:
                        cluster_data[cl_letter] = {
                            "output": out_val,
                            "count": 0
                        }
                    cluster_data[cl_letter]["count"] += 1

                # 1. Extract the Oracle output of the current step for reference
                oracle_output = cluster_data.get("A", {}).get("output", None)

                # 2. Determine the clicked cluster based on the impl_val (implementation abbreviation) 
                clicked_cluster = None
                if impl_val:
                    for full_impl, cl_letter in impl_label.items():
                        if short_label(full_impl) == impl_val:
                            clicked_cluster = cl_letter
                            break

                sorted_clusters = sorted(cluster_data.keys(), key=lambda x: (x != "A", x))
                rows = []
                
                for cl in sorted_clusters:
                    data = cluster_data[cl]
                    out_val = data["output"]
                    is_oracle = (cl == "A")
                    is_clicked = (cl == clicked_cluster)
                    
                    # 3. 核心过滤逻辑：如果不是 Oracle，且没有点中它，且它的输出跟 Oracle 一模一样（没有偏离），则不显示
                    if not is_oracle and not is_clicked and out_val == oracle_output:
                        continue
                        
                    count = data["count"]
                    cl_color = color_map.get(cl, "#9ca3af") if not is_oracle else "#0ea5e9"
                    label = "Oracle" if is_oracle else f"Cluster {cl}"
                    
                    # 4. 视觉样式判定：为点击的卡片增加显眼的高亮色
                    if is_oracle:
                        bg_color = "#f0fdfa"
                        border_color = "#ccfbf1"
                    elif is_clicked:
                        bg_color = "#fef3c7"      # 选中的卡片背景：浅黄色
                        border_color = "#fde68a"  # 选中的卡片边框：深黄色
                    else:
                        bg_color = "#fff7ed"
                        border_color = "#ffedd5"
                    
                    # 组装 Summary 的标题栏
                    summary_elements = [
                        html.Span("■ ", style={"color": cl_color, "fontSize": 12, "marginRight": 4, "verticalAlign": "middle"}),
                        html.Span(label, style={"fontWeight": 600, "fontSize": 11, "color": "#374151", "marginRight": 8, "verticalAlign": "middle"}),
                        html.Span(f"{count} impls", style={"fontSize": 10, "color": "#6b7280", "verticalAlign": "middle"}),
                    ]
                    
                    # 5. 给用户点中的 Cluster 加上专属徽标
                    if is_clicked:
                        summary_elements.append(
                            html.Span("SELECTED", style={
                                "fontSize": 9, "color": "#d97706", "fontWeight": 700, 
                                "marginLeft": 8, "backgroundColor": "#fef3c7", 
                                "padding": "2px 6px", "borderRadius": "10px",
                                "verticalAlign": "middle"
                            })
                        )

                    display_val = "null" if pd.isna(out_val) or out_val is None else str(out_val)
                    
                    rows.append(html.Details([
                        html.Summary(summary_elements, style={"cursor": "pointer", "outline": "none", "marginBottom": 4, "userSelect": "none"}),
                        
                        html.Div(display_val, style={
                            "fontFamily": "Menlo,monospace", "fontSize": 10, 
                            "color": "#4b5563", "backgroundColor": bg_color, 
                            "padding": "6px", "borderRadius": "4px", "wordBreak": "break-all",
                            "border": f"1px solid {border_color}",
                            "maxHeight": "200px",  
                            "overflowY": "auto",   
                            "marginTop": "4px",
                            "marginLeft": "18px"  
                        })
                    ], 
                    className="custom-fold",
                    open=True,               
                    style={"marginBottom": 12}))
                """
                for cl in sorted_clusters:
                    data = cluster_data[cl]
                    out_val = data["output"]
                    count = data["count"]
                    is_oracle = (cl == "A")
                    
                    # Extract the colors of the specific Clusters
                    cl_color = color_map.get(cl, "#9ca3af") if not is_oracle else "#0ea5e9"
                    
                    label = "Oracle" if is_oracle else f"Cluster {cl}"
                    bg_color = "#f0fdfa" if is_oracle else "#fff7ed" 
                    border_color = "#ccfbf1" if is_oracle else "#ffedd5"
                    
                    display_val = "null" if pd.isna(out_val) or out_val is None else str(out_val)
                    
                    rows.append(html.Div([
                        html.Div([
                            html.Div(style={
                                "width": 8, "height": 8, "borderRadius": 2, 
                                "backgroundColor": cl_color, "marginRight": 6
                            }),
                            html.Span(label, style={"fontWeight": 600, "fontSize": 11, "color": "#374151", "marginRight": 8}),
                            html.Span(f"{count} impls", style={"fontSize": 10, "color": "#6b7280"}),
                        ], style={"display": "flex", "alignItems": "center", "marginBottom": 4}),
                        
                        html.Div(display_val, style={
                            "fontFamily": "Menlo,monospace", "fontSize": 10, 
                            "color": "#4b5563", "backgroundColor": bg_color, 
                            "padding": "6px", "borderRadius": "4px", "wordBreak": "break-all",
                            "border": f"1px solid {border_color}"
                        })
                    ], style={"marginBottom": 12}))
                """

                header_ui = html.Div([
                    html.Div(f"{test_val}() · s{step_val}", style={"fontWeight": 600, "fontSize": 12}),
                    html.Button("✖ Close", id="clear-cluster-selection-btn", 
                                style={"border": "none", "background": "transparent", "cursor": "pointer", 
                                       "color": "#9ca3af", "fontSize": 10, "padding": 0})
                ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start", "marginBottom": 12})

                detail_ui = [
                    _section("STEP DETAIL"),
                    header_ui,
                    *rows,
                    _divider()
                ]
                panel = detail_ui + panel

            except Exception as e:
                error_ui = [
                    _section("STEP DETAIL"),
                    html.Div(f"Could not load step details. Error: {str(e)}", style={"fontSize": 10, "color": "#ef4444"}),
                    _divider()
                ]
                panel = error_ui + panel

            except Exception as e:
                error_ui = [
                    _section("STEP DETAIL"),
                    html.Div(f"Could not load step details. Error: {str(e)}", style={"fontSize": 10, "color": "#ef4444"}),
                    _divider()
                ]
                panel = error_ui + panel

            except Exception as e:
                # 友好的错误提示，防止程序崩溃
                error_ui = [
                    _section("STEP DETAIL"),
                    html.Div(f"Could not load step details. Error: {str(e)}", style={"fontSize": 10, "color": "#ef4444"}),
                    _divider()
                ]
                panel = error_ui + panel

            except Exception as e:
                # 友好的错误提示，防止程序崩溃
                error_ui = [
                    _section("STEP DETAIL"),
                    html.Div(f"Could not load step details. Error: {str(e)}", style={"fontSize": 10, "color": "#ef4444"}),
                    _divider()
                ]
                panel = error_ui + panel

    # 渲染顶部返回 Focus 按钮的逻辑
    if focused_test:
        panel.insert(0, html.Div([
            html.Span(f"Focused: {focused_test[:20]}...",
                      style={"fontSize": 11, "color": "#374151", "flex": 1}),
            html.Button("✕ Back",
                        n_clicks=0,
                        id="clear-focus-btn",
                        style={"fontSize": 10, "border": "1px solid #14b8a6",
                               "background": "none", "borderRadius": 4,
                               "color": "#14b8a6", "cursor": "pointer",
                               "padding": "2px 6px", "flexShrink": 0}),
        ], style={"display": "flex", "alignItems": "center", "gap": 6,
                  "padding": "6px 8px", "background": "#f0fdfa",
                  "borderRadius": 5, "marginBottom": 10,
                  "border": "1px solid #99f6e4"}))

    return fig, panel

# ── Tab switching ─────────────────────────────────────────────────────────────

@callback(
    Output("panel-va", "style"),
    Output("panel-be", "style"),
    Output("tab-va-nav", "style"),
    Output("tab-be-nav", "style"),
    Input("tab-va-nav", "n_clicks"),
    Input("tab-be-nav", "n_clicks"),
    prevent_initial_call=False,
)
def switch_tab(va_clicks, be_clicks):
    from dash import ctx
    triggered = ctx.triggered_id
    is_be = triggered == "tab-be-nav"
    va_style = {"display": "block"} if not is_be else {"display": "none"}
    be_style = {"display": "block"} if is_be else {"display": "none"}
    va_nav = {"color": "#14b8a6", "fontSize": 11, "fontWeight": 700,
              "borderBottom": "2px solid #14b8a6", "paddingBottom": 2,
              "cursor": "pointer", "marginRight": 16}
    be_nav = {"color": "#9ca3af", "fontSize": 11, "cursor": "pointer"}
    if is_be:
        va_nav = {"color": "#9ca3af", "fontSize": 11, "cursor": "pointer",
                  "marginRight": 16}
        be_nav = {"color": "#14b8a6", "fontSize": 11, "fontWeight": 700,
                  "borderBottom": "2px solid #14b8a6", "paddingBottom": 2,
                  "cursor": "pointer"}
    return va_style, be_style, va_nav, be_nav


# ── BE callbacks ──────────────────────────────────────────────────────────────

@callback(
    Output("be-selected-impl", "data"),
    Input("be-heatmap", "clickData"),
    Input("be-problem-dd", "value"),
    Input("be-runs-dd", "value"),
    prevent_initial_call=True,
)
def update_be_selected(click_data, problem_id, n_runs):
    from dash import ctx
    if ctx.triggered_id in ("be-problem-dd", "be-runs-dd"):
        return None
    if click_data:
        y_label = click_data["points"][0].get("y", "")
        # y_label is short_label(impl_id) — find the full impl_id
        return y_label
    return None


@callback(
    Output("be-heatmap", "figure"),
    Output("be-right-panel", "children"),
    Input("be-problem-dd", "value"),
    Input("be-runs-dd", "value"),
    Input("be-selected-impl", "data"),
)
def update_be(problem_id, n_runs, selected_short):
    if not problem_id or not BE_AVAILABLE:
        empty = go.Figure()
        empty.update_layout(plot_bgcolor="#f9fafb", paper_bgcolor="#fff",
                            height=300, xaxis=dict(visible=False),
                            yaxis=dict(visible=False),
                            annotations=[dict(
                                text="Behavioral Evolution data not available.",
                                xref="paper", yref="paper", x=0.5, y=0.5,
                                showarrow=False, font=dict(size=13, color="#6b7280")
                            )])
        return empty, [html.Div("No BE data.", style={"fontSize": 12, "color": "#9ca3af"})]

    n_runs = int(n_runs)

    # Find full impl_id from short label
    selected_impl = None
    if selected_short:
        run_ids = BE_RUN_IDS[-n_runs:]
        all_impls_df = conn.execute(f"""
            SELECT DISTINCT implementation_id FROM be_observations
            WHERE problem_id = '{problem_id}'
              AND run_id = '{run_ids[0]}'
        """).fetchdf()
        for impl_id in all_impls_df['implementation_id'].tolist():
            if short_label(impl_id) == selected_short:
                selected_impl = impl_id
                break

    fig, impl_cluster_map, color_map = build_be_heatmap(problem_id, n_runs, selected_impl)

    clusters_df = behavioral_clustering(conn, problem_id, BE_RUN_IDS[0])
    color_map   = make_color_map(len(clusters_df)) if not clusters_df.empty else {}

    panel = build_be_right_panel(
        problem_id, selected_impl, n_runs, impl_cluster_map, color_map
    )
    return fig, panel



@app.callback(
    Output("heatmap", "clickData"), 
    Input("clear-diff-selection-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_diff_selection(n_clicks):
    if n_clicks:
        return None

@app.callback(
    Output("heatmap", "clickData", allow_duplicate=True), 
    Input("clear-cluster-selection-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_cluster_selection(n_clicks):
    if n_clicks:
        return None

@app.callback(
    Output("be-heatmap", "clickData", allow_duplicate=True), 
    Input("be-close-btn", "n_clicks"),
    prevent_initial_call=True
)
def clear_be_selection(n_clicks):
    if n_clicks:
        return None

if __name__ == "__main__":
    app.run(debug=True, port=8050)


