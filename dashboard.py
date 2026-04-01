"""
BESS Energy Use Simulation — Interactive Results Dashboard
Run with:  streamlit run dashboard.py
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
SCHEDULE_FILE  = _HERE / "output/schedule_15min_2025.csv"
BASELINE_FILE  = _HERE / "output/schedule_15min_baseline_2025.csv"
CONFIG_FILE    = _HERE / "config.yaml"
ENERGY_MWH     = 400.0

COLOURS = {
    "da":        "#2196F3",
    "afrr_up":   "#4CAF50",
    "afrr_dn":   "#F44336",
    "id":        "#FF9800",
    "soc":       "#9C27B0",
    "cap":       "#00BCD4",
    "net":       "#607D8B",
    "exp_res":   "#FF5722",
    "imp_res":   "#3F51B5",
}

DT = 0.25  # hours per 15-min interval

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="BESS Energy Use Simulation – Germany",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------
def _check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.title("🔋 BESS Energy Use Simulation – Germany")
    pw = st.text_input("Enter password to continue", type="password")
    if pw:
        correct = st.secrets.get("password", "")
        if pw == correct:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False

if not _check_password():
    st.stop()

st.title("🔋 BESS Energy Use Simulation – Germany")

# ---------------------------------------------------------------------------
# Load data (cached)
# ---------------------------------------------------------------------------
@st.cache_data
def load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Europe/Berlin")
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["date"] = df["timestamp"].dt.date
    return df

@st.cache_data
def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f)

@st.cache_data
def load_baseline(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Europe/Berlin")
    return df.sort_values("timestamp").reset_index(drop=True)

if not SCHEDULE_FILE.exists():
    st.error(f"Output file not found: `{SCHEDULE_FILE}`. Run `python main.py` first.")
    st.stop()

df       = load_data(SCHEDULE_FILE)
baseline = load_baseline(BASELINE_FILE)
cfg      = load_config(CONFIG_FILE)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_results, tab_restrictions, tab_assumptions = st.tabs([
    "📊 Results",
    "🔌 Grid Restrictions",
    "⚙️ Assumptions & Parameters",
])

# ============================================================================
# SHARED LAYOUT HELPER
# ============================================================================
LAYOUT = dict(
    plot_bgcolor  = "white",
    paper_bgcolor = "white",
    hovermode     = "x unified",
    legend        = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin        = dict(l=60, r=20, t=40, b=40),
    xaxis         = dict(showgrid=True, gridcolor="#eee", tickformat="%b %d"),
    yaxis         = dict(showgrid=True, gridcolor="#eee"),
)

def fig_base(title: str, y_title: str, height: int = 320) -> go.Figure:
    f = go.Figure()
    f.update_layout(**LAYOUT, title=title, height=height,
                    yaxis_title=y_title, xaxis_title="")
    return f

st.markdown("""
<style>
[data-testid="stMetricLabel"] { font-size: 0.78rem !important; }
[data-testid="stMetricValue"] { font-size: 1.1rem !important; }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# TAB 3 — Assumptions & Parameters
# ============================================================================
with tab_assumptions:
    b  = cfg.get("battery", {})
    a  = cfg.get("afrr", {})
    cy = cfg.get("cycling", {})
    si = cfg.get("simulation", {})
    gc = cfg.get("grid_connection", {})

    rte    = b.get("rte", 0.9)
    eta_1w = math.sqrt(rte)

    st.markdown("## Simulation Assumptions")

    st.markdown("### 🔋 Battery")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rated Power",    f"{b.get('power_mw', '—')} MW")
    c2.metric("Energy Capacity",f"{b.get('energy_mwh', '—')} MWh")
    c3.metric("Round-Trip Eff.",f"{rte*100:.0f}%")
    c4.metric("One-way Eff.",   f"{eta_1w*100:.1f}%  (each direction)")
    c5.metric("Initial SoC",    f"{b.get('soc_initial_mwh', '—')} MWh")

    st.markdown("### ♻️ Cycling")
    c1, c2 = st.columns(2)
    c1.metric("Max Cycles / Day", f"{cy.get('max_cycles_per_day', '—')}  (1 cycle = {b.get('energy_mwh','400')} MWh throughput)")
    c2.metric("Max Daily Throughput", f"{cy.get('max_cycles_per_day', 3) * b.get('energy_mwh', 400):,.0f} MWh/day")

    st.markdown("### ⚡ aFRR Capacity Strategy")
    opt_mode = a.get("optimize_reservation", False)
    mode_str = "Joint LP optimisation (per 4h block)" if opt_mode else "Fixed reservation"
    st.info(f"**Mode:** {mode_str}")

    c1, c2 = st.columns(2)
    label = "Max bound (LP)" if opt_mode else "Fixed bid"
    c1.metric(f"Upward reservation — {label}",   f"{a.get('pos_reserved_mw','—')} MW")
    c2.metric(f"Downward reservation — {label}", f"{a.get('neg_reserved_mw','—')} MW")

    if not opt_mode:
        soc_min = a.get("neg_reserved_mw", 0)
        soc_max = b.get("energy_mwh", 400) - a.get("pos_reserved_mw", 0)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("SoC Floor (derived)",   f"{soc_min} MWh")
        c2.metric("SoC Ceiling (derived)", f"{soc_max} MWh")
        c3.metric("DA max discharge",      f"{b.get('power_mw',100) - a.get('pos_reserved_mw',0)} MW")
        c4.metric("DA max charge",         f"{b.get('power_mw',100) - a.get('neg_reserved_mw',0)} MW")

    st.markdown("### 📋 aFRR Energy Activation Bid Rules")
    thr = a.get("activation_da_low_threshold", 30)
    bid_table = pd.DataFrame([
        {"Direction": "Upward (discharge)", "DA regime": "DA < 0",
         "Bid formula": f"Fixed {a.get('activation_bid_pos_neg_da_eur','—')} €/MWh", "Activate when": "DAME_pos ≥ bid"},
        {"Direction": "Upward (discharge)", "DA regime": f"0 ≤ DA < {thr} €/MWh",
         "Bid formula": f"{a.get('activation_bid_factor_pos_low','—')} × DA", "Activate when": "DAME_pos ≥ bid"},
        {"Direction": "Upward (discharge)", "DA regime": f"DA ≥ {thr} €/MWh",
         "Bid formula": f"{a.get('activation_bid_factor_pos','—')} × DA", "Activate when": "DAME_pos ≥ bid"},
        {"Direction": "Downward (charge)", "DA regime": "DA < 0",
         "Bid formula": f"{a.get('activation_bid_factor_neg_neg_da','—')} × DA", "Activate when": "bid ≥ DAME_neg"},
        {"Direction": "Downward (charge)", "DA regime": f"0 ≤ DA < {thr} €/MWh",
         "Bid formula": f"{a.get('activation_bid_factor_neg_low','—')} × DA", "Activate when": "bid ≥ DAME_neg"},
        {"Direction": "Downward (charge)", "DA regime": f"DA ≥ {thr} €/MWh",
         "Bid formula": f"{a.get('activation_bid_factor_neg','—')} × DA", "Activate when": "bid ≥ DAME_neg"},
    ])
    st.dataframe(bid_table, use_container_width=True, hide_index=True)

    st.markdown("### 🗓️ Simulation Period")
    c1, c2, c3 = st.columns(3)
    c1.metric("Start",    si.get("start_date", "—"))
    c2.metric("End",      si.get("end_date",   "—"))
    c3.metric("Timezone", si.get("timezone",   "—"))

    st.markdown("---")
    st.markdown("## 📈 Full-Year Computed Results")

    n_days      = max((df["timestamp"].dt.date.max() - df["timestamp"].dt.date.min()).days + 1, 1)
    total_cyc   = (df["p_net_mw"].clip(lower=0) * DT).sum() / b.get("energy_mwh", 400)
    throughput  = (df["p_net_mw"].clip(lower=0) * DT).sum()
    avg_soc     = df["soc_mwh"].mean()
    act_pos_mwh = (df["p_afrr_pos_activated_mw"] * DT).sum()
    act_neg_mwh = (df["p_afrr_neg_activated_mw"] * DT).sum()
    avg_r_pos   = df["p_afrr_pos_reserved_mw"].mean()
    avg_r_neg   = df["p_afrr_neg_reserved_mw"].mean()

    st.markdown("#### Cycling & Utilisation")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Cycles",        f"{total_cyc:.1f}")
    c2.metric("Avg Cycles / Day",    f"{total_cyc/n_days:.2f}  (limit {cy.get('max_cycles_per_day','—')})")
    c3.metric("Total Throughput",    f"{throughput:,.0f} MWh")
    c4.metric("Avg SoC",             f"{avg_soc:.0f} MWh  ({avg_soc/b.get('energy_mwh',400)*100:.0f}%)")

    st.markdown("#### Revenue")
    total_rev  = df["revenue_total_eur"].sum()
    rev_da     = df["revenue_da_eur"].sum()
    rev_cap    = df["revenue_afrr_cap_eur"].sum()
    rev_energy = df["revenue_afrr_energy_eur"].sum()
    rev_id     = df["revenue_id_eur"].sum()
    rev_per_mw = total_rev / b.get("power_mw", 100)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Revenue",       f"€{total_rev:,.0f}")
    c2.metric("Revenue / MW / year", f"€{rev_per_mw:,.0f}")
    c3.metric("Revenue / MWh thput", f"€{total_rev/throughput:.1f}" if throughput > 0 else "—")

    rev_table = pd.DataFrame([
        {"Market": "Day-Ahead",     "Revenue (€)": f"{rev_da:>14,.0f}", "Share": f"{rev_da/total_rev*100:.1f}%"},
        {"Market": "aFRR Capacity", "Revenue (€)": f"{rev_cap:>14,.0f}", "Share": f"{rev_cap/total_rev*100:.1f}%"},
        {"Market": "aFRR Energy",   "Revenue (€)": f"{rev_energy:>14,.0f}", "Share": f"{rev_energy/total_rev*100:.1f}%"},
        {"Market": "ID Correction", "Revenue (€)": f"{rev_id:>14,.0f}", "Share": f"{rev_id/total_rev*100:.1f}%"},
        {"Market": "TOTAL",         "Revenue (€)": f"{total_rev:>14,.0f}", "Share": "100.0%"},
    ])
    st.dataframe(rev_table, use_container_width=True, hide_index=True)


# ============================================================================
# TAB 2 — Grid Restrictions
# ============================================================================
with tab_restrictions:
    gc = cfg.get("grid_connection", {})
    b  = cfg.get("battery", {})
    a  = cfg.get("afrr", {})

    power_mw    = float(b.get("power_mw", 100))
    ramp_pct    = float(gc.get("ramp_rate_pct_per_min", 100))
    deliverable = min(ramp_pct * 5.0, 100.0)
    ramp_cap_mw = power_mw * deliverable / 100.0
    pos_max_cfg = float(a.get("pos_reserved_mw", 50))
    neg_max_cfg = float(a.get("neg_reserved_mw", 50))
    pos_cap_eff = min(pos_max_cfg, ramp_cap_mw)
    neg_cap_eff = min(neg_max_cfg, ramp_cap_mw)
    ramp_limited = ramp_pct < 100

    exp_max_mw  = float(gc.get("export_restriction_max_mw", 0))
    imp_max_mw  = float(gc.get("import_restriction_max_mw", 0))

    exp_mask = df["grid_export_restricted"].astype(bool)
    imp_mask = df["grid_import_restricted"].astype(bool)
    n_exp    = int(exp_mask.sum())
    n_imp    = int(imp_mask.sum())
    h_exp    = n_exp * DT
    h_imp    = n_imp * DT
    n_total  = len(df)
    neither  = ~(exp_mask | imp_mask)

    # Derive scenario labels from actual data (config.yaml may be stale)
    exp_scenario_label = gc.get("export_scenario", "none").upper()
    imp_scenario_label = gc.get("import_scenario", "none").upper()
    if n_exp > 0 and exp_scenario_label == "NONE":
        exp_scenario_label = "ACTIVE"
    if n_imp > 0 and imp_scenario_label == "NONE":
        imp_scenario_label = "ACTIVE"

    any_restriction = (n_exp > 0 or n_imp > 0 or ramp_limited)

    st.markdown("## Grid Connection Restrictions")

    # ── Configuration summary ─────────────────────────────────────────────────
    st.markdown("### Configuration")
    c1, c2, c3 = st.columns(3)
    c1.metric("Export scenario", exp_scenario_label,
              help="solar = Apr–Sep 09–16h weekdays; constant = top-N DA-price hours; none = no restriction")
    c2.metric("Import scenario", imp_scenario_label,
              help="demand = Nov–Mar 17–20h (+ Dec/Jan 11–14h) weekdays; constant = top-N; none = no restriction")
    c3.metric("Ramp rate",
              f"{ramp_pct:.0f}% / min",
              delta=f"→ {ramp_cap_mw:.0f} MW aFRR cap in 5 min" if ramp_limited else "No cap",
              delta_color="off")

    c1, c2, c3 = st.columns(3)
    c1.metric("Export max power (restricted)", f"{exp_max_mw:.0f} MW",
              delta="Full curtailment" if exp_max_mw == 0 and n_exp > 0 else None, delta_color="off")
    c2.metric("Import max power (restricted)", f"{imp_max_mw:.0f} MW",
              delta="Full curtailment" if imp_max_mw == 0 and n_imp > 0 else None, delta_color="off")
    c3.metric("aFRR cap (pos / neg)",
              f"{pos_cap_eff:.0f} / {neg_cap_eff:.0f} MW",
              delta=f"Config: {pos_max_cfg:.0f}/{neg_max_cfg:.0f} MW" if ramp_limited else "Unrestricted",
              delta_color="off")

    if not any_restriction:
        st.info("No restrictions are active. Set `export_scenario`, `import_scenario`, "
                "or reduce `ramp_rate_pct_per_min` in config.yaml.")
        st.stop()

    st.markdown("---")
    st.markdown("### Coverage")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Export-restricted hours",
              f"{h_exp:,.0f} h",
              delta=f"{n_exp/n_total*100:.1f}% of year", delta_color="off")
    c2.metric("Import-restricted hours",
              f"{h_imp:,.0f} h",
              delta=f"{n_imp/n_total*100:.1f}% of year", delta_color="off")

    # Average DA price in restricted vs free slots
    da_exp  = df.loc[exp_mask, "da_price_eur_mwh"].mean() if n_exp > 0 else float("nan")
    da_imp  = df.loc[imp_mask, "da_price_eur_mwh"].mean() if n_imp > 0 else float("nan")
    da_free = df.loc[neither,  "da_price_eur_mwh"].mean()  if neither.any() else float("nan")

    c3.metric("Avg DA price — export-restr.",
              f"{da_exp:.1f} €/MWh" if not np.isnan(da_exp) else "—",
              delta=f"vs {da_free:.1f} free" if not np.isnan(da_free) else None,
              delta_color="off")
    c4.metric("Avg DA price — import-restr.",
              f"{da_imp:.1f} €/MWh" if not np.isnan(da_imp) else "—",
              delta=f"vs {da_free:.1f} free" if not np.isnan(da_free) else None,
              delta_color="off")

    # ── Restriction timeline ───────────────────────────────────────────────────
    st.markdown("### Restriction Timeline")
    df_ts = df.set_index("timestamp")
    daily_exp = (df_ts["grid_export_restricted"].resample("D").sum() * DT).reset_index()
    daily_imp = (df_ts["grid_import_restricted"].resample("D").sum() * DT).reset_index()

    fig = go.Figure()
    if n_exp > 0:
        fig.add_trace(go.Bar(
            x=daily_exp["timestamp"], y=daily_exp["grid_export_restricted"],
            name="Export-restricted (h/day)", marker_color=COLOURS["exp_res"], opacity=0.8,
        ))
    if n_imp > 0:
        fig.add_trace(go.Bar(
            x=daily_imp["timestamp"], y=daily_imp["grid_import_restricted"],
            name="Import-restricted (h/day)", marker_color=COLOURS["imp_res"], opacity=0.8,
        ))
    fig.update_layout(**LAYOUT, title="Restriction Hours per Day", height=280, barmode="overlay", yaxis_title="h/day")
    st.plotly_chart(fig, use_container_width=True)

    # ── Hour-of-day profile ───────────────────────────────────────────────────
    if n_exp > 0 or n_imp > 0:
        st.markdown("### Hour-of-Day Profile")
        df["hour"] = df["timestamp"].dt.hour
        hourly_exp_pct = df.groupby("hour")["grid_export_restricted"].mean() * 100
        hourly_imp_pct = df.groupby("hour")["grid_import_restricted"].mean() * 100

        fig = go.Figure()
        if n_exp > 0:
            fig.add_trace(go.Bar(x=hourly_exp_pct.index, y=hourly_exp_pct.values,
                name="Export restricted (%)", marker_color=COLOURS["exp_res"], opacity=0.8))
        if n_imp > 0:
            fig.add_trace(go.Bar(x=hourly_imp_pct.index, y=hourly_imp_pct.values,
                name="Import restricted (%)", marker_color=COLOURS["imp_res"], opacity=0.8))
        fig.update_layout(**LAYOUT, title="% of Slots Restricted — by Hour of Day",
                          height=280, barmode="group", yaxis_title="% of slots restricted")
        fig.update_xaxes(showgrid=True, gridcolor="#eee", tickmode="linear", dtick=2, title="Hour (CET)")
        st.plotly_chart(fig, use_container_width=True)

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    st.markdown("### Monthly Breakdown")
    df["month"] = df["timestamp"].dt.to_period("M").astype(str)
    monthly_exp_h = df.groupby("month")["grid_export_restricted"].sum() * DT
    monthly_imp_h = df.groupby("month")["grid_import_restricted"].sum() * DT

    fig = go.Figure()
    if n_exp > 0:
        fig.add_trace(go.Bar(x=monthly_exp_h.index, y=monthly_exp_h.values,
            name="Export-restricted (h)", marker_color=COLOURS["exp_res"], opacity=0.85))
    if n_imp > 0:
        fig.add_trace(go.Bar(x=monthly_imp_h.index, y=monthly_imp_h.values,
            name="Import-restricted (h)", marker_color=COLOURS["imp_res"], opacity=0.85))
    fig.update_layout(**LAYOUT, title="Monthly Restriction Hours", height=300, barmode="group", yaxis_title="Hours")
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    st.plotly_chart(fig, use_container_width=True)

    # ── Revenue impact vs baseline ────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Revenue Impact vs Unrestricted Baseline")

    if baseline is None:
        st.info("No baseline file found. Re-run `python main.py` — it now automatically saves "
                "`schedule_15min_baseline_2025.csv` when restrictions are active.")
    else:
        rev_restricted = df["revenue_total_eur"].sum()
        rev_baseline   = baseline["revenue_total_eur"].sum()
        delta_total    = rev_restricted - rev_baseline

        streams = [
            ("revenue_da_eur",          "Day-Ahead",    COLOURS["da"]),
            ("revenue_afrr_cap_eur",    "aFRR Capacity",COLOURS["cap"]),
            ("revenue_afrr_energy_eur", "aFRR Energy",  COLOURS["afrr_up"]),
            ("revenue_id_eur",          "ID Correction",COLOURS["id"]),
        ]

        # Top KPIs
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Baseline revenue (no restrictions)", f"€{rev_baseline:,.0f}")
        c2.metric("Restricted revenue",                  f"€{rev_restricted:,.0f}")
        c3.metric("Revenue impact",
                  f"€{delta_total:,.0f}",
                  delta=f"{delta_total/rev_baseline*100:.1f}% vs baseline",
                  delta_color="normal")
        c4.metric("Revenue / MW impact",
                  f"€{delta_total/power_mw:,.0f} /MW")

        # Per-stream comparison bar chart
        stream_names  = [s[1] for s in streams]
        vals_base     = [baseline[s[0]].sum() for s in streams]
        vals_restr    = [df[s[0]].sum() for s in streams]
        deltas        = [r - b_ for r, b_ in zip(vals_restr, vals_base)]
        colours_list  = [s[2] for s in streams]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=stream_names, y=vals_base,
            name="Baseline", marker_color=["rgba(33,150,243,0.4)", "rgba(0,188,212,0.4)",
                                            "rgba(76,175,80,0.4)", "rgba(255,152,0,0.4)"],
            text=[f"€{v:,.0f}" for v in vals_base], textposition="outside",
        ))
        fig.add_trace(go.Bar(
            x=stream_names, y=vals_restr,
            name="With restrictions", marker_color=colours_list,
            text=[f"€{v:,.0f}" for v in vals_restr], textposition="outside",
        ))
        fig.update_layout(**LAYOUT, title="Revenue by Stream: Baseline vs Restricted",
                          height=360, barmode="group", yaxis_title="€")
        fig.update_xaxes(showgrid=False)
        st.plotly_chart(fig, use_container_width=True)

        # Delta table
        delta_table = pd.DataFrame([
            {"Stream": name, "Baseline (€)": f"{b_:,.0f}", "Restricted (€)": f"{r:,.0f}",
             "Delta (€)": f"{d:+,.0f}", "Delta (%)": f"{d/b_*100:+.1f}%" if b_ != 0 else "—"}
            for (_, name, _), b_, r, d in zip(streams, vals_base, vals_restr, deltas)
        ] + [{"Stream": "TOTAL",
              "Baseline (€)": f"{rev_baseline:,.0f}",
              "Restricted (€)": f"{rev_restricted:,.0f}",
              "Delta (€)": f"{delta_total:+,.0f}",
              "Delta (%)": f"{delta_total/rev_baseline*100:+.1f}%"}])
        st.dataframe(delta_table, use_container_width=True, hide_index=True)

        # ── 15-min schedule deviation chart ───────────────────────────────────
        st.markdown("### 15-min Schedule: Restricted vs Baseline")
        st.caption("Select a date range to zoom in on specific restriction periods.")

        date_min_r = df["timestamp"].dt.date.min()
        date_max_r = df["timestamp"].dt.date.max()
        dev_range  = st.date_input("Date range (deviation chart)",
                                   value=(date_min_r, date_max_r),
                                   min_value=date_min_r, max_value=date_max_r,
                                   key="dev_range")
        if isinstance(dev_range, (list, tuple)) and len(dev_range) == 2:
            dr_start, dr_end = dev_range
        else:
            dr_start = dr_end = dev_range[0] if dev_range else date_min_r

        mask_r  = (df["timestamp"].dt.date >= dr_start) & (df["timestamp"].dt.date <= dr_end)
        mask_b  = (baseline["timestamp"].dt.date >= dr_start) & (baseline["timestamp"].dt.date <= dr_end)
        df_r    = df[mask_r].copy()
        df_b    = baseline[mask_b].copy()

        ts_r   = df_r["timestamp"]
        p_restr = df_r["p_net_mw"].values
        p_base  = df_b["p_net_mw"].values[:len(p_restr)]
        p_delta = p_restr - p_base

        # Shade restriction periods
        exp_r = df_r["grid_export_restricted"].astype(bool).values
        imp_r = df_r["grid_import_restricted"].astype(bool).values

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                            subplot_titles=("Net Power: Restricted vs Baseline (MW)",
                                            "Deviation: Restricted − Baseline (MW)"))

        fig.add_trace(go.Scatter(x=ts_r, y=p_base,  name="Baseline",    line=dict(color="#aaa", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=ts_r, y=p_restr, name="Restricted",  line=dict(color=COLOURS["da"],  width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=ts_r, y=p_delta, name="Δ power",
                                 fill="tozeroy",
                                 line=dict(color=COLOURS["exp_res"], width=1),
                                 fillcolor="rgba(255,87,34,0.15)"), row=2, col=1)
        fig.add_hline(y=0, line_color="#999", line_width=0.8, row=2, col=1)

        fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                          margin=dict(l=60, r=20, t=60, b=40), height=520)
        fig.update_yaxes(showgrid=True, gridcolor="#eee")
        fig.update_xaxes(showgrid=True, gridcolor="#eee", tickformat="%b %d")
        st.plotly_chart(fig, use_container_width=True)

    # ── aFRR ramp-rate cap section ────────────────────────────────────────────
    if ramp_limited:
        st.markdown("---")
        st.markdown("### aFRR Capacity — Ramp Rate Impact")
        st.info(
            f"Ramp rate {ramp_pct:.0f}%/min → max deliverable in 5 min = "
            f"{deliverable:.0f}% = **{ramp_cap_mw:.1f} MW**  "
            f"(config max: {pos_max_cfg:.0f}/{neg_max_cfg:.0f} MW pos/neg)"
        )

        avg_r_pos    = df["p_afrr_pos_reserved_mw"].mean()
        avg_r_neg    = df["p_afrr_neg_reserved_mw"].mean()
        afrr_cap_rev = df["revenue_afrr_cap_eur"].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("Avg pos reserved (actual)", f"{avg_r_pos:.1f} MW",
                  delta=f"cap at {pos_cap_eff:.0f} MW", delta_color="off")
        c2.metric("Avg neg reserved (actual)", f"{avg_r_neg:.1f} MW",
                  delta=f"cap at {neg_cap_eff:.0f} MW", delta_color="off")
        c3.metric("aFRR capacity revenue", f"€{afrr_cap_rev:,.0f}")

        daily_rpos = (df_ts["p_afrr_pos_reserved_mw"].resample("D").mean()).reset_index()
        daily_rneg = (df_ts["p_afrr_neg_reserved_mw"].resample("D").mean()).reset_index()

        fig = fig_base("Daily Avg aFRR Reservation (MW)", "MW", height=280)
        fig.add_trace(go.Scatter(x=daily_rpos["timestamp"], y=daily_rpos["p_afrr_pos_reserved_mw"],
            name="Pos reserved", line=dict(color=COLOURS["afrr_up"], width=1.5)))
        fig.add_trace(go.Scatter(x=daily_rneg["timestamp"], y=daily_rneg["p_afrr_neg_reserved_mw"],
            name="Neg reserved", line=dict(color=COLOURS["afrr_dn"], width=1.5)))
        fig.add_hline(y=ramp_cap_mw, line_dash="dash", line_color="#FF9800",
                      annotation_text=f"Ramp cap {ramp_cap_mw:.0f} MW")
        fig.add_hline(y=pos_max_cfg, line_dash="dot", line_color="#aaa",
                      annotation_text=f"Config max {pos_max_cfg:.0f} MW")
        st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# TAB 1 — Results
# ============================================================================
with tab_results:

    # Sidebar
    st.sidebar.header("⚙️ Filters")
    date_min = df["timestamp"].dt.date.min()
    date_max = df["timestamp"].dt.date.max()

    date_range = st.sidebar.date_input(
        "Date range",
        value=(date_min, date_max),
        min_value=date_min,
        max_value=date_max,
    )

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        d_start, d_end = date_range
    else:
        d_start = d_end = date_range[0] if date_range else date_min

    resolution = st.sidebar.radio(
        "Chart resolution",
        options=["15-min (raw)", "Hourly avg", "Daily avg"],
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.header("📊 Panels")
    show_soc     = st.sidebar.checkbox("State of Charge",        value=True)
    show_power   = st.sidebar.checkbox("Net active power",       value=True)
    show_markets = st.sidebar.checkbox("Power by market",        value=True)
    show_afrr    = st.sidebar.checkbox("aFRR activation detail", value=True)

    st.sidebar.markdown("---")
    st.sidebar.header("💰 Revenue")
    show_rev_kpi = st.sidebar.checkbox("Revenue summary (top)",    value=False)
    show_rev_cum = st.sidebar.checkbox("Cumulative revenue chart", value=False)
    show_rev_day = st.sidebar.checkbox("Daily revenue by market",  value=False)

    # Filter & resample
    mask = (df["timestamp"].dt.date >= d_start) & (df["timestamp"].dt.date <= d_end)
    dff  = df[mask].copy()

    if dff.empty:
        st.warning("No data for selected range.")
        st.stop()

    def resample(dff: pd.DataFrame, res: str) -> pd.DataFrame:
        if res == "15-min (raw)":
            return dff
        freq = "h" if res == "Hourly avg" else "D"
        num_cols = dff.select_dtypes("number").columns
        r = dff.set_index("timestamp")[num_cols].resample(freq).mean().reset_index()
        return r

    plot_df = resample(dff, resolution)
    ts = plot_df["timestamp"]
    n_days = max((d_end - d_start).days + 1, 1)

    # Schedule Summary strip
    total_cyc_sel  = (dff["p_net_mw"].clip(lower=0) * DT).sum() / ENERGY_MWH
    avg_cycles_day = total_cyc_sel / n_days
    avg_afrr_pos_res = dff["p_afrr_pos_reserved_mw"].mean()
    avg_afrr_neg_res = dff["p_afrr_neg_reserved_mw"].mean()
    act_pos_mwh_day  = (dff["p_afrr_pos_activated_mw"] * DT).sum() / n_days
    act_neg_mwh_day  = (dff["p_afrr_neg_activated_mw"] * DT).sum() / n_days

    _b = cfg.get("battery", {})
    _power_mw   = _b.get("power_mw", "—")
    _energy_mwh = _b.get("energy_mwh", "—")

    st.markdown("#### Schedule Summary")
    col0a, col0b, col1, col2, col3, col4, col5 = st.columns(7)
    col0a.metric("Installed power",      f"{_power_mw} MW")
    col0b.metric("Installed capacity",   f"{_energy_mwh} MWh")
    col1.metric("Avg cycles / day",      f"{avg_cycles_day:.2f}")
    col2.metric("Avg aFRR ↑ reserved",   f"{avg_afrr_pos_res:.1f} MW")
    col3.metric("Avg aFRR ↓ reserved",   f"{avg_afrr_neg_res:.1f} MW")
    col4.metric("Avg aFRR ↑ activation", f"{act_pos_mwh_day:.1f} MWh/day")
    col5.metric("Avg aFRR ↓ activation", f"{act_neg_mwh_day:.1f} MWh/day")

    st.markdown("---")

    if show_rev_kpi:
        total_rev_sel = dff["revenue_total_eur"].sum()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Revenue",    f"€{total_rev_sel:,.0f}")
        c2.metric("DA Revenue",       f"€{dff['revenue_da_eur'].sum():,.0f}")
        c3.metric("aFRR Cap Revenue", f"€{dff['revenue_afrr_cap_eur'].sum():,.0f}")
        c4.metric("aFRR Energy Rev.", f"€{dff['revenue_afrr_energy_eur'].sum():,.0f}")
        c5.metric("ID Revenue",       f"€{dff['revenue_id_eur'].sum():,.0f}")
        st.markdown("---")

    # 1 — State of Charge
    if show_soc:
        fig = fig_base("State of Charge (MWh)", "MWh", height=300)
        fig.add_trace(go.Scatter(
            x=ts, y=plot_df["soc_mwh"],
            name="SoC", line=dict(color=COLOURS["soc"], width=1.5),
            fill="tozeroy", fillcolor="rgba(156,39,176,0.08)",
        ))
        fig.add_hline(y=ENERGY_MWH,       line_dash="dash", line_color="#aaa", annotation_text="100%")
        fig.add_hline(y=ENERGY_MWH * 0.5, line_dash="dot",  line_color="#ccc", annotation_text="50%")
        fig.add_hline(y=0,                line_dash="dash",  line_color="#aaa", annotation_text="0%")
        st.plotly_chart(fig, use_container_width=True)

    # 2 — Net active power
    if show_power:
        fig = fig_base("Net Active Power (MW)", "MW", height=280)
        fig.add_trace(go.Scatter(
            x=ts, y=plot_df["p_net_mw"],
            name="Net power", line=dict(color=COLOURS["net"], width=1),
            fill="tozeroy", fillcolor="rgba(96,125,139,0.1)",
        ))
        fig.add_hline(y=0, line_color="#999", line_width=0.8)
        st.plotly_chart(fig, use_container_width=True)

    # 3 — Power by market
    if show_markets:
        fig = fig_base("Active Power by Market (MW)", "MW", height=340)
        fig.add_trace(go.Scatter(
            x=ts, y=plot_df["p_da_mw"],
            name="DA", line=dict(color=COLOURS["da"], width=1),
        ))
        afrr_net = plot_df["p_afrr_pos_activated_mw"] - plot_df["p_afrr_neg_activated_mw"]
        fig.add_trace(go.Scatter(
            x=ts, y=afrr_net,
            name="aFRR net (up−dn)", line=dict(color=COLOURS["afrr_up"], width=1),
        ))
        fig.add_trace(go.Scatter(
            x=ts, y=-plot_df["p_id_correction_mw"],
            name="ID restoration", line=dict(color=COLOURS["id"], width=1, dash="dot"),
        ))
        fig.add_hline(y=0, line_color="#999", line_width=0.8)
        st.plotly_chart(fig, use_container_width=True)

    # 4 — Cumulative revenue
    if show_rev_cum:
        fig = fig_base("Cumulative Revenue by Market (€)", "€", height=320)
        for col, name, colour in [
            ("revenue_da_eur",          "DA",           COLOURS["da"]),
            ("revenue_afrr_cap_eur",    "aFRR Capacity",COLOURS["cap"]),
            ("revenue_afrr_energy_eur", "aFRR Energy",  COLOURS["afrr_up"]),
            ("revenue_id_eur",          "ID",           COLOURS["id"]),
            ("revenue_total_eur",       "Total",        "#333"),
        ]:
            lw = 2.5 if col == "revenue_total_eur" else 2
            ld = "dash" if col == "revenue_total_eur" else "solid"
            fig.add_trace(go.Scatter(
                x=ts, y=dff[col].cumsum().values[:len(ts)],
                name=name, line=dict(color=colour, width=lw, dash=ld),
            ))
        st.plotly_chart(fig, use_container_width=True)

    # 5 — Daily revenue stacked bar
    if show_rev_day:
        daily_rev = (
            dff.groupby("date")[
                ["revenue_da_eur", "revenue_afrr_cap_eur",
                 "revenue_afrr_energy_eur", "revenue_id_eur"]
            ].sum().reset_index()
        )
        fig = go.Figure()
        for col, name, colour in [
            ("revenue_da_eur",          "DA",           COLOURS["da"]),
            ("revenue_afrr_cap_eur",    "aFRR Capacity",COLOURS["cap"]),
            ("revenue_afrr_energy_eur", "aFRR Energy",  COLOURS["afrr_up"]),
            ("revenue_id_eur",          "ID",           COLOURS["id"]),
        ]:
            fig.add_trace(go.Bar(x=daily_rev["date"], y=daily_rev[col], name=name, marker_color=colour))
        fig.update_layout(**LAYOUT, title="Daily Revenue by Market (€)",
                          barmode="relative", height=340, yaxis_title="€/day", bargap=0.15)
        fig.update_xaxes(showgrid=True, gridcolor="#eee", tickformat="%b %d")
        st.plotly_chart(fig, use_container_width=True)

    # 6 — aFRR activation detail
    if show_afrr:
        st.markdown("### aFRR Activation Detail")
        col_l, col_r = st.columns(2)

        with col_l:
            fig = fig_base("aFRR Upward — bid vs DAME (€/MWh)", "€/MWh", height=280)
            fig.add_trace(go.Scatter(x=ts, y=plot_df["dame_pos_eur_mwh"],
                name="DAME pos", line=dict(color=COLOURS["afrr_up"], width=1)))
            fig.add_trace(go.Scatter(x=ts, y=plot_df["bid_afrr_up_eur_mwh"],
                name="Our bid (up)", line=dict(color=COLOURS["da"], width=1, dash="dash")))
            fig.add_trace(go.Scatter(x=ts, y=plot_df["da_price_eur_mwh"],
                name="DA price", line=dict(color="#aaa", width=1, dash="dot")))
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            fig = fig_base("aFRR Downward — bid vs DAME (€/MWh)", "€/MWh", height=280)
            fig.add_trace(go.Scatter(x=ts, y=plot_df["dame_neg_eur_mwh"],
                name="DAME neg", line=dict(color=COLOURS["afrr_dn"], width=1)))
            fig.add_trace(go.Scatter(x=ts, y=plot_df["bid_afrr_dn_eur_mwh"],
                name="Our bid (dn)", line=dict(color=COLOURS["id"], width=1, dash="dash")))
            fig.add_trace(go.Scatter(x=ts, y=plot_df["da_price_eur_mwh"],
                name="DA price", line=dict(color="#aaa", width=1, dash="dot")))
            st.plotly_chart(fig, use_container_width=True)

        col_l2, col_r2 = st.columns(2)
        with col_l2:
            fig = fig_base("TSO Activation Volume — Upward (MW)", "MW", height=260)
            fig.add_trace(go.Scatter(x=ts, y=plot_df["tso_activation_pos_mw"],
                name="TSO pos", line=dict(color=COLOURS["afrr_up"], width=1),
                fill="tozeroy", fillcolor="rgba(76,175,80,0.1)"))
            fig.add_trace(go.Scatter(x=ts, y=plot_df["p_afrr_pos_activated_mw"],
                name="Our activation", line=dict(color=COLOURS["da"], width=1.5)))
            st.plotly_chart(fig, use_container_width=True)

        with col_r2:
            fig = fig_base("TSO Activation Volume — Downward (MW)", "MW", height=260)
            fig.add_trace(go.Scatter(x=ts, y=plot_df["tso_activation_neg_mw"],
                name="TSO neg", line=dict(color=COLOURS["afrr_dn"], width=1),
                fill="tozeroy", fillcolor="rgba(244,67,54,0.1)"))
            fig.add_trace(go.Scatter(x=ts, y=plot_df["p_afrr_neg_activated_mw"],
                name="Our activation", line=dict(color=COLOURS["id"], width=1.5)))
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.caption(f"Showing {len(dff):,} intervals  |  Resolution: {resolution}")
