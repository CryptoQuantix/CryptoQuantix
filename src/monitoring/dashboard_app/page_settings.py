"""
Pagina "Impostazioni" — editor .env con guardrail (Fase 3).

Flusso: widget tipizzati coi range validati -> diff prima/dopo ->
conferma -> backup .env.bak.<ts> -> scrittura chirurgica -> validazione
in subprocess (ripristino automatico se fallisce) -> avviso riavvio.
"""
import os

import pandas as pd
import streamlit as st

from src.monitoring.dashboard_app import data_access as da
from src.monitoring.dashboard_app import env_editor
from src.monitoring.dashboard_app.audit import audit
from src.monitoring.dashboard_app.settings_registry import (
    GROUPS, SECRET_KEYS, SETTINGS, format_value,
)


def render():
    st.header("Impostazioni (.env)")
    st.caption(
        "Il bot legge il .env SOLO all'avvio: ogni modifica richiede un "
        "riavvio. Backup automatico prima di ogni scrittura; se il file "
        "modificato non passa la validazione viene ripristinato da solo."
    )

    if not os.path.exists(env_editor.ENV_PATH):
        st.error(".env non trovato nella root del progetto.")
        return

    current = env_editor.parse_env()

    # ------------------------------------------------------------------
    # Secrets: solo stato, mai il valore
    # ------------------------------------------------------------------
    with st.expander("Credenziali (sola lettura)"):
        for key in SECRET_KEYS:
            is_set = bool(current.get(key, "").strip())
            st.markdown(f"- `{key}`: {'impostata' if is_set else 'NON impostata'}")
        st.caption("Le credenziali non sono editabili dalla dashboard.")

    # ------------------------------------------------------------------
    # Widget per gruppo -> raccolta modifiche pendenti
    # ------------------------------------------------------------------
    changes = {}        # key -> nuovo valore (stringa .env)
    display_rows = []   # per la tabella diff
    tabs = st.tabs(GROUPS)
    for tab, group in zip(tabs, GROUPS):
        with tab:
            if group == "Strategie disattivate":
                st.warning(
                    "Strategie BOCCIATE dalla validazione multi-ciclo. "
                    "Non riattivare senza ripassare la pipeline "
                    "(microevolutive/PLAN_BULL_EVOLUTION.md §1)."
                )
            for entry in (e for e in SETTINGS if e["group"] == group):
                new_str = _render_widget(entry, current)
                old_str = current.get(entry["key"], "")
                if new_str is not None and _is_changed(entry, old_str, new_str):
                    changes[entry["key"]] = new_str
                    display_rows.append({
                        "Chiave": entry["key"],
                        "Prima": old_str or "(assente)",
                        "Dopo": new_str,
                        "Parametro strategia": "SI" if entry.get("strategy_param") else "no",
                    })

    st.divider()

    # ------------------------------------------------------------------
    # Diff + conferma + applicazione
    # ------------------------------------------------------------------
    if not changes:
        st.info("Nessuna modifica pendente: i widget riflettono il .env attuale.")
    else:
        st.subheader(f"Modifiche pendenti ({len(changes)})")
        st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")

        if any(r["Parametro strategia"] == "SI" for r in display_rows):
            st.error(
                "Stai modificando PARAMETRI DI STRATEGIA: i numeri di "
                "backtest non valgono piu' per la nuova configurazione — "
                "rivalidare con la pipeline prima di fidarsi dei risultati."
            )
        if changes.get("DERIBIT_ENV") == "prod":
            st.error("Stai passando a PROD: denaro reale.")

        confirmed = st.checkbox(
            "Ho letto il diff e confermo la scrittura sul .env reale")
        if st.button("Applica modifiche", type="primary", disabled=not confirmed):
            ok, msg, backup = env_editor.apply_changes_safely(changes)
            audit("env_edit", {"changes": changes, "backup": backup},
                  "ok" if ok else f"fail: {msg}")
            if ok:
                st.success(f"{msg} — backup: `{backup}`")
                st.warning(
                    "Le modifiche saranno attive SOLO dopo il riavvio del bot "
                    "(richiedibile qui sotto)."
                )
                st.rerun()
            else:
                st.error(msg)

    # ------------------------------------------------------------------
    # Richiesta riavvio (flag onorata dal management loop del bot)
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("Riavvio bot")
    from src.core import flags
    if flags.flag_active(flags.RESTART_REQUEST_FLAG):
        info = flags.flag_info(flags.RESTART_REQUEST_FLAG) or {}
        st.warning(
            f"Richiesta di riavvio GIA' in coda ({info.get('created_utc', '?')}). "
            "Il bot la onora entro ~30s con uno shutdown pulito."
        )
        if st.button("Annulla richiesta di riavvio"):
            flags.clear_flag(flags.RESTART_REQUEST_FLAG)
            audit("restart_request_cancel", {}, "ok")
            st.rerun()
    else:
        ask = st.checkbox("Confermo: chiedo al bot uno shutdown pulito "
                          "(il supervisor esterno deve riavviarlo)")
        if st.button("Richiedi riavvio bot", disabled=not ask):
            flags.set_flag(flags.RESTART_REQUEST_FLAG,
                           reason="riavvio richiesto da dashboard impostazioni")
            audit("restart_request", {}, "ok")
            st.success("Richiesta scritta: il bot esce entro ~30s.")
            st.rerun()

    # ------------------------------------------------------------------
    # Backup esistenti
    # ------------------------------------------------------------------
    backups = env_editor.list_backups()
    if backups:
        with st.expander(f"Backup .env disponibili ({len(backups)})"):
            for b in backups[:15]:
                st.markdown(f"- `{b}`")


def _is_changed(entry, old_str: str, new_str: str) -> bool:
    """Confronto canonico: '0.30' nel file e '0.3' dal widget NON sono una
    modifica. Per i numerici confronta i valori, non le stringhe."""
    if old_str == new_str:
        return False
    if entry["kind"] in ("int", "float"):
        try:
            return abs(float(old_str) - float(new_str)) > 1e-12
        except (TypeError, ValueError):
            return True
    if entry["kind"] == "bool":
        return old_str.strip().lower() != new_str.strip().lower()
    return old_str.strip() != new_str.strip()


def _render_widget(entry, current):
    """Renderizza il widget di una voce. Ritorna la stringa .env del valore
    corrente del widget (None se il valore non e' interpretabile)."""
    key = entry["key"]
    raw = current.get(key, "")
    label = entry["label"]
    if entry.get("validated") is not None:
        label += f"  · validato: {entry['validated']}"
    help_txt = entry.get("help")
    if entry.get("verdict"):
        help_txt = f"VERDETTO: {entry['verdict']}"
    wkey = f"set_{key}"

    try:
        if entry["kind"] == "bool":
            val = st.toggle(label, value=raw.lower() == "true",
                            key=wkey, help=help_txt)
        elif entry["kind"] == "select":
            options = entry["options"]
            idx = options.index(raw) if raw in options else 0
            val = st.selectbox(label, options, index=idx, key=wkey, help=help_txt)
        elif entry["kind"] == "int":
            cur = int(float(raw)) if raw else int(entry["min"])
            cur = max(entry["min"], min(entry["max"], cur))
            val = st.slider(label, entry["min"], entry["max"], cur,
                            step=entry.get("step", 1), key=wkey, help=help_txt)
        elif entry["kind"] == "float":
            cur = float(raw) if raw else float(entry["min"])
            cur = max(entry["min"], min(entry["max"], cur))
            val = st.slider(label, float(entry["min"]), float(entry["max"]),
                            float(cur), step=float(entry.get("step", 0.01)),
                            format=entry.get("format", "%.4f"),
                            key=wkey, help=help_txt)
        else:  # text
            val = st.text_input(label, value=raw, key=wkey, help=help_txt)
        return format_value(entry, val)
    except Exception as e:
        st.warning(f"`{key}`: valore corrente '{raw}' non interpretabile ({e})")
        return None
