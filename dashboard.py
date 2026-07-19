"""Streamlit dashboard for non-UCITS and UCITS NDX distortion snapshots."""

from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from database import SnapshotDatabase
from snapshot_service import recompute_all_snapshots, recompute_snapshot


load_dotenv()
st.set_page_config(page_title="NDX Weight Distortion Index", page_icon="⚖️", layout="wide")


def _database() -> SnapshotDatabase:
    return SnapshotDatabase(os.getenv("NDX_DB_PATH", "data/ndx_wdi.sqlite3"))


def _percent(value: float | None) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:.2%}"


def _component_table(frame: pd.DataFrame, weighting_basis: str) -> pd.DataFrame:
    columns = [
        "ticker",
        "company_name",
        "actual_weight",
        "counterfactual_weight",
        "weight_delta",
        "weight_ratio",
        "distortion_contribution",
        "price",
        "reference_shares",
        "data_status",
    ]
    result = frame.reindex(columns=columns).copy()
    for column in ["actual_weight", "counterfactual_weight", "weight_delta"]:
        result[column] = result[column].map(_percent)
    result["weight_ratio"] = result["weight_ratio"].map(
        lambda value: "—" if pd.isna(value) else f"{value:.2f}x"
    )
    result["distortion_contribution"] = result["distortion_contribution"].map(
        lambda value: "—" if pd.isna(value) else f"{value:.3f}"
    )
    result["price"] = result["price"].map(
        lambda value: "—" if pd.isna(value) else f"${value:,.2f}"
    )
    result["reference_shares"] = result["reference_shares"].map(
        lambda value: "—" if pd.isna(value) else f"{value:,.0f}"
    )
    if weighting_basis == "total":
        return result.rename(
            columns={
                "counterfactual_weight": "total_cap_weight",
                "reference_shares": "shares_outstanding",
            }
        )
    return result.rename(
        columns={
            "counterfactual_weight": "float_weight",
            "reference_shares": "float_shares",
        }
    )


def _render_source_status(snapshot: dict[str, object]) -> None:
    message = (
        f"Statut : **{snapshot['status']}** · Fonds de référence : "
        f"**{snapshot.get('reference_fund') or '—'}** · Source : "
        f"{snapshot.get('holdings_source') or '—'} · Holdings au : "
        f"{snapshot.get('holdings_as_of') or 'date non publiée'} · Snapshot UTC : "
        f"{snapshot['timestamp']}"
    )
    if snapshot["status"] == "complete":
        st.success(message)
    else:
        st.warning(message)
    if snapshot.get("source_failures"):
        with st.expander("Sources précédentes rejetées"):
            st.code(str(snapshot["source_failures"]))


def _render_universe(database: SnapshotDatabase, snapshot: dict[str, object]) -> None:
    components = pd.DataFrame(database.get_components(int(snapshot["snapshot_id"])))
    weighting_basis = str(snapshot.get("weighting_basis") or "float")
    metrics = st.columns(6 if weighting_basis == "float" else 5)
    metrics[0].metric("NDX_WDI", f"{snapshot['ndx_wdi']:.2f}")
    metrics[1].metric("Couverture", _percent(snapshot["coverage_ratio"]))
    metrics[2].metric("Titres", int(snapshot["constituent_count"]))
    if weighting_basis == "float":
        metrics[3].metric(
            "Flottants manquants", int(snapshot["missing_reference_shares_count"])
        )
        metrics[4].metric("Flottants invalides", int(snapshot.get("invalid_float_count", 0)))
        metrics[5].metric("Prix manquants", int(snapshot["missing_price_count"]))
    else:
        metrics[3].metric(
            "Actions totales manquantes", int(snapshot["missing_reference_shares_count"])
        )
        metrics[4].metric("Prix manquants", int(snapshot["missing_price_count"]))
    _render_source_status(snapshot)
    if weighting_basis == "float" and snapshot.get("invalid_float_count", 0):
        st.warning(
            "Les flottants incohérents avec les actions en circulation ou la capitalisation "
            "totale sont exclus sans être remplacés."
        )

    valid = components.loc[
        components["data_status"].astype("string").str.startswith("valid", na=False)
    ].copy()
    if not valid.empty:
        chart_frame = valid.nlargest(20, "distortion_contribution").sort_values("weight_delta")
        chart_frame["direction"] = chart_frame["weight_delta"].map(
            lambda value: "Surpondération" if value >= 0 else "Sous-pondération"
        )
        figure = px.bar(
            chart_frame,
            x="weight_delta",
            y="ticker",
            orientation="h",
            color="direction",
            color_discrete_map={"Surpondération": "#c44e52", "Sous-pondération": "#4c72b0"},
            labels={"weight_delta": "Écart de poids", "ticker": "Titre"},
            title="Principaux écarts de pondération",
            hover_data={
                "actual_weight": ":.2%",
                "counterfactual_weight": ":.2%",
                "weight_delta": ":.2%",
            },
        )
        figure.update_layout(legend_title_text="", xaxis_tickformat=".1%")
        st.plotly_chart(figure, width="stretch")

    st.subheader("Classements")
    overweights, underweights, contributors = st.tabs(
        ["Surpondérations", "Sous-pondérations", "Contributeurs"]
    )
    with overweights:
        st.dataframe(
            _component_table(
                valid.loc[valid["weight_delta"] > 0].nlargest(15, "weight_delta"),
                weighting_basis,
            ),
            hide_index=True,
            width="stretch",
        )
    with underweights:
        st.dataframe(
            _component_table(
                valid.loc[valid["weight_delta"] < 0].nsmallest(15, "weight_delta"),
                weighting_basis,
            ),
            hide_index=True,
            width="stretch",
        )
    with contributors:
        st.dataframe(
            _component_table(
                valid.nlargest(15, "distortion_contribution"), weighting_basis
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Tous les composants")
    st.dataframe(
        _component_table(components, weighting_basis),
        hide_index=True,
        width="stretch",
    )
    missing = components.loc[
        ~components["data_status"].astype("string").str.startswith("valid", na=False)
    ]
    if not missing.empty:
        st.subheader("Données exclues du calcul")
        st.dataframe(
            _component_table(missing, weighting_basis),
            hide_index=True,
            width="stretch",
        )


st.title("Nasdaq-100 Weight Distortion Index")
st.caption(
    "Deux lectures séparées des pondérations publiées : ETF américains non-UCITS "
    "(IQQ puis QQQ) et ETF européens UCITS (CNDX puis EQQQ ou sources configurées)."
)

with st.sidebar:
    st.header("Recalcul")
    mode = st.selectbox("Mode", ["auto", "live", "sample"], index=0)
    use_total_cap = st.toggle(
        "Capitalisation cotée totale",
        value=False,
        help="Désactivé : prix × flottant. Activé : prix × actions en circulation.",
    )
    weighting_basis = "total" if use_total_cap else "float"
    if weighting_basis == "total":
        st.caption("Contrefactuel : prix × `sharesOutstanding`, sans ajustement de flottant.")
    else:
        st.caption("Contrefactuel : prix × `floatShares`.")
    target_label = st.selectbox("Univers", ["Tous", "Non-UCITS", "UCITS"], index=0)
    target = {"Tous": "all", "Non-UCITS": "non_ucits", "UCITS": "ucits"}[target_label]
    st.caption(
        "Les pondérations sont lues telles que publiées. Une source incomplète ou un top 10 est rejeté."
    )
    if st.button("Recalculer maintenant", type="primary", width="stretch"):
        with st.spinner("Récupération des holdings et calcul en cours…"):
            try:
                if target == "all":
                    outcomes = recompute_all_snapshots(
                        mode=mode,
                        db_path=os.getenv("NDX_DB_PATH"),
                        weighting_basis=weighting_basis,
                    )
                else:
                    outcomes = [
                        recompute_snapshot(
                            mode=mode,
                            db_path=os.getenv("NDX_DB_PATH"),
                            universe=target,
                            weighting_basis=weighting_basis,
                        )
                    ]
                fallback_messages = [outcome.fallback_reason for outcome in outcomes if outcome.fallback_reason]
                if fallback_messages:
                    st.warning(" · ".join(fallback_messages))
                else:
                    st.success("Snapshot(s) enregistré(s).")
                st.rerun()
            except Exception as exc:
                st.error(f"Recalcul impossible : {exc}")

database = _database()
snapshots = database.get_current_by_universe(weighting_basis)
if not snapshots:
    st.info(
        "Aucun snapshot. Utilisez « Recalculer maintenant » ou lancez "
        f"`python run_snapshot.py --mode sample --universe all --basis {weighting_basis}`."
    )
    st.stop()

summary_columns = st.columns(2)
for column, universe, label in zip(
    summary_columns,
    ("non_ucits", "ucits"),
    ("Non-UCITS", "UCITS"),
):
    with column:
        with st.container(border=True):
            st.subheader(label)
            snapshot = snapshots.get(universe)
            if snapshot:
                st.metric("NDX_WDI", f"{snapshot['ndx_wdi']:.2f}")
                st.write(
                    f"Couverture {_percent(snapshot['coverage_ratio'])} · "
                    f"Référence {snapshot.get('reference_fund') or '—'} · "
                    f"Base {'capitalisation totale' if weighting_basis == 'total' else 'flottant'}"
                )
            else:
                st.info("Pas encore de snapshot.")

history = pd.DataFrame(database.get_history(limit=730, weighting_basis=weighting_basis))
if not history.empty:
    history = history.loc[
        ~history["status"].astype("string").str.startswith("invalidated", na=False)
    ].copy()
if len(history) > 1:
    history["Univers"] = history["universe"].map(
        {"non_ucits": "Non-UCITS", "ucits": "UCITS"}
    )
    history = history.sort_values("timestamp")
    trend = px.line(
        history,
        x="timestamp",
        y="ndx_wdi",
        color="Univers",
        markers=True,
        title="Historique comparé du NDX_WDI",
    )
    trend.update_layout(xaxis_title="Snapshot UTC", yaxis_title="NDX_WDI")
    st.plotly_chart(trend, width="stretch")

available = [(key, label) for key, label in (("non_ucits", "Non-UCITS"), ("ucits", "UCITS")) if key in snapshots]
tabs = st.tabs([label for _, label in available])
for tab, (universe, _) in zip(tabs, available):
    with tab:
        _render_universe(database, snapshots[universe])

st.caption(
    "Les univers ne sont jamais fusionnés ni moyennés. Chaque score conserve le fonds de référence "
    "et la source de pondérations effectivement retenus."
)
