"""
Ad Ingestion MVP — Streamlit Application
Peak Ventures · Media Buying Ops

Screens:
  1. Scrape        → URL/CSV input, scrape + cluster
  2. Topic Wall    → Select topics/angles to generate
  3. Asset Library → View generated creatives, approve, launch
"""

import json
import logging
import math
import os
import threading
import streamlit as st
import yaml
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Config + init
# ──────────────────────────────────────────────

ASSET_DIR = Path("output")
ASSET_FILE = ASSET_DIR / "asset_library.json"


@st.cache_resource
def load_config():
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)


@st.cache_resource
def get_client():
    from utils.claude_client import get_claude_client
    return get_claude_client()


def init_session():
    defaults = {
        "stage": "input",
        "raw_ads": [],
        "clusters": None,
        "selections": None,
        "pv_domain": "",
        "buyer_initials": "",
        "source_url": "",
        "network": "facebook",
        "generating_run_id": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ──────────────────────────────────────────────
# Asset library (persistent JSON storage)
# ──────────────────────────────────────────────

def load_asset_library():
    if ASSET_FILE.exists():
        try:
            with open(ASSET_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"runs": []}
    return {"runs": []}


def save_asset_library(data):
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    with open(ASSET_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def save_run(run_data):
    lib = load_asset_library()
    existing = [i for i, r in enumerate(lib["runs"]) if r.get("id") == run_data["id"]]
    if existing:
        lib["runs"][existing[0]] = run_data
    else:
        lib["runs"].insert(0, run_data)
    save_asset_library(lib)


def get_run(run_id):
    lib = load_asset_library()
    for run in lib["runs"]:
        if run.get("id") == run_id:
            return run
    return None


# ──────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="PV Ad Ingestion",
    page_icon="assets/favicon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_session()
config = load_config()

# ──────────────────────────────────────────────
# Brand CSS
# ──────────────────────────────────────────────

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons+Round" rel="stylesheet">
<style>
    /* ── Design tokens ── */
    :root {
        --pv-accent: #7C6BFF;
        --pv-accent-hover: #6B5BFF;
        --pv-accent-muted: rgba(124, 107, 255, 0.15);
        --pv-bg: #12141A;
        --pv-surface: #1E2028;
        --pv-surface-hover: #252730;
        --pv-border: #2E3140;
        --pv-border-light: #3A3D4E;
        --pv-text: #F0F2F5;
        --pv-text-secondary: #A0A6B4;
        --pv-text-muted: #727A8C;
        --pv-green: #4ADE80;
        --pv-yellow: #FACC15;
        --pv-red: #FB7185;
        --pv-blue: #60A5FA;
        --radius-sm: 6px;
        --radius-md: 8px;
        --radius-lg: 12px;
    }

    /* ── Global ── */
    html, body, [data-testid="stApp"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    }
    .block-container {
        padding: 0.75rem 2rem 2rem 2rem !important;
        max-width: 1280px;
    }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background-color: #0D0F14 !important;
        border-right: 1px solid var(--pv-border) !important;
        min-width: 240px !important;
        max-width: 240px !important;
        width: 240px !important;
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        font-size: 13px;
        font-family: 'Inter', sans-serif;
    }

    /* Sidebar nav buttons */
    [data-testid="stSidebar"] .stButton > button {
        text-align: left !important;
        padding: 9px 14px !important;
        margin: 2px 0 !important;
        border: none !important;
        border-radius: var(--radius-sm) !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        background: transparent !important;
        color: var(--pv-text-secondary) !important;
        box-shadow: none !important;
        letter-spacing: 0 !important;
        transition: all 0.12s ease !important;
        position: relative !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(124, 107, 255, 0.08) !important;
        color: var(--pv-text) !important;
    }
    /* Active nav item — accent left bar */
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
        background: rgba(124, 107, 255, 0.12) !important;
        color: #C4BAFF !important;
        font-weight: 600 !important;
        border-left: 3px solid var(--pv-accent) !important;
        padding-left: 11px !important;
        border-radius: 0 var(--radius-sm) var(--radius-sm) 0 !important;
    }

    /* Sidebar divider */
    [data-testid="stSidebar"] hr {
        border-color: var(--pv-border) !important;
        margin: 8px 0 !important;
    }

    /* ── Primary buttons ── */
    .block-container .stButton > button[kind="primary"],
    .block-container button[data-testid="stBaseButton-primary"] {
        background: var(--pv-accent) !important;
        border: none !important;
        border-radius: var(--radius-md) !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        color: white !important;
        box-shadow: none !important;
        padding: 10px 24px !important;
        transition: all 0.15s ease !important;
    }
    .block-container .stButton > button[kind="primary"]:hover,
    .block-container button[data-testid="stBaseButton-primary"]:hover {
        background: var(--pv-accent-hover) !important;
        box-shadow: 0 2px 12px rgba(124, 107, 255, 0.3) !important;
    }

    /* ── Secondary buttons ── */
    .block-container .stButton > button:not([kind="primary"]),
    .block-container button[data-testid="stBaseButton-secondary"] {
        border: 1px solid var(--pv-border-light) !important;
        border-radius: var(--radius-md) !important;
        background: var(--pv-surface) !important;
        color: var(--pv-text-secondary) !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        padding: 8px 16px !important;
        transition: all 0.15s ease !important;
    }
    .block-container .stButton > button:not([kind="primary"]):hover {
        border-color: var(--pv-accent) !important;
        color: var(--pv-text) !important;
        background: var(--pv-surface-hover) !important;
    }

    /* ── Cards ── */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: var(--pv-surface) !important;
        border: 1px solid var(--pv-border) !important;
        border-radius: var(--radius-lg) !important;
    }

    /* ── Equal-height columns ── */
    [data-testid="stHorizontalBlock"] { align-items: stretch !important; }

    /* ── Form inputs ── */
    [data-testid="stTextInput"] input,
    [data-testid="stSelectbox"] .st-cb,
    [data-baseweb="select"] > div:first-child {
        background: var(--pv-bg) !important;
        border-color: var(--pv-border) !important;
        font-size: 14px !important;
        border-radius: var(--radius-sm) !important;
    }
    [data-testid="stTextInput"] input:focus {
        border-color: var(--pv-accent) !important;
        box-shadow: 0 0 0 1px var(--pv-accent) !important;
    }
    /* Input labels */
    [data-testid="stWidgetLabel"] p {
        font-size: 12px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
        color: var(--pv-text-muted) !important;
    }

    /* ── Checkbox rows ── */
    [data-testid="stCheckbox"] {
        padding: 5px 8px;
        margin: 2px 0;
        border-radius: var(--radius-sm);
        transition: all 0.12s ease;
    }
    [data-testid="stCheckbox"]:hover {
        background: rgba(124, 107, 255, 0.06);
    }
    [data-testid="stCheckbox"] label p {
        font-weight: 500 !important;
        font-size: 14px !important;
        color: var(--pv-text) !important;
    }

    /* ── Section label (reusable) ── */
    .section-label {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: var(--pv-text-muted);
        margin: 0 0 8px 0;
    }

    /* ── Page title ── */
    .page-title {
        font-size: 24px;
        font-weight: 700;
        color: var(--pv-text);
        margin: 0 0 4px 0;
        line-height: 1.3;
    }
    .page-subtitle {
        font-size: 15px;
        color: var(--pv-text-secondary);
        margin: 0 0 20px 0;
    }

    /* ── Step indicator ── */
    .step-indicator {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-bottom: 16px;
        font-size: 13px;
        font-weight: 500;
    }
    .step-item {
        padding: 4px 12px;
        border-radius: 20px;
        color: var(--pv-text-muted);
        transition: all 0.12s ease;
    }
    .step-item.active {
        background: var(--pv-accent-muted);
        color: #C4BAFF;
        font-weight: 600;
    }
    .step-item.completed {
        color: var(--pv-green);
    }
    .step-sep {
        color: var(--pv-text-muted);
        font-size: 11px;
    }

    /* ── Stat pills (inline metrics) ── */
    .stat-bar {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }
    .stat-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 5px 14px;
        border: 1px solid var(--pv-border);
        border-radius: 20px;
        font-size: 13px;
        color: var(--pv-text-secondary);
        background: transparent;
    }
    .stat-pill strong {
        color: var(--pv-text);
        font-weight: 600;
    }

    /* ── Tags ── */
    .pv-tag {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
        text-transform: uppercase;
    }
    .pv-tag-offer     { background: rgba(63, 185, 80, 0.12); color: var(--pv-green); }
    .pv-tag-claim     { background: rgba(210, 153, 34, 0.12); color: var(--pv-yellow); }
    .pv-tag-curiosity { background: rgba(88, 166, 255, 0.12); color: var(--pv-blue); }
    .pv-tag-urgency   { background: rgba(248, 81, 73, 0.12); color: var(--pv-red); }
    .pv-tag-info      { background: rgba(167, 139, 250, 0.12); color: #A78BFA; }
    .pv-tag-direct    { background: rgba(63, 185, 80, 0.12); color: var(--pv-green); }
    .pv-tag-hook      { background: rgba(88, 166, 255, 0.12); color: var(--pv-blue); }

    /* ── Opportunity badge ── */
    .opp-badge {
        display: inline-flex; align-items: center; gap: 4px;
        padding: 3px 10px; border-radius: 4px;
        font-size: 11px; font-weight: 600; white-space: nowrap;
        text-transform: uppercase; letter-spacing: 0.3px;
    }
    .opp-high { background: rgba(74, 222, 128, 0.15); color: var(--pv-green); }
    .opp-med  { background: rgba(250, 204, 21, 0.15); color: var(--pv-yellow); }
    .opp-low  { background: rgba(124, 107, 255, 0.15); color: #A78BFA; }

    /* ── Offer items ── */
    .offer-item {
        padding: 3px 0 3px 12px;
        margin: 2px 0;
        border-left: 2px solid var(--pv-accent);
        font-size: 13px;
        color: var(--pv-text-secondary);
    }

    /* ── Topic rank ── */
    .rank-num {
        display: inline-flex; align-items: center; justify-content: center;
        width: 28px; height: 28px; border-radius: 6px;
        background: var(--pv-accent-muted);
        color: #C4BAFF; font-weight: 700; font-size: 13px; flex-shrink: 0;
    }

    /* ── Topic card header ── */
    .topic-header {
        display: flex; align-items: center; gap: 10px;
        margin-bottom: 8px;
    }
    .topic-title {
        font-size: 16px; font-weight: 600; color: var(--pv-text);
        flex: 1; line-height: 1.3;
    }

    /* ── Source bar ── */
    .source-bar {
        display: inline-flex; align-items: center; gap: 8px;
        padding: 8px 14px; background: var(--pv-surface);
        border: 1px solid var(--pv-border);
        border-radius: var(--radius-sm); margin-bottom: 16px;
        font-size: 13px; color: var(--pv-text-secondary);
    }
    .source-bar a { color: #C4BAFF; text-decoration: none; font-weight: 500; }
    .source-bar a:hover { text-decoration: underline; }

    /* ── Banner placeholder ── */
    .banner-placeholder {
        background: var(--pv-bg);
        border: 1px dashed var(--pv-border-light);
        border-radius: var(--radius-md);
        padding: 28px 16px; text-align: center;
        min-height: 140px; display: flex;
        align-items: center; justify-content: center;
    }
    .banner-placeholder b { font-size: 14px; color: var(--pv-text-secondary); line-height: 1.4; }

    /* ── Run cards (asset library) ── */
    .run-card-header {
        display: flex; align-items: center; gap: 12px;
        padding: 0; flex-wrap: wrap;
    }
    .run-domain { font-weight: 600; font-size: 15px; color: var(--pv-text); }
    .run-meta { font-size: 13px; color: var(--pv-text-muted); }
    .run-badge {
        display: inline-flex; align-items: center; gap: 4px;
        padding: 3px 12px; border-radius: 4px;
        font-size: 12px; font-weight: 600;
    }
    .run-generating { background: rgba(250, 204, 21, 0.15); color: var(--pv-yellow); }
    .run-complete   { background: rgba(74, 222, 128, 0.15); color: var(--pv-green); }
    .run-error      { background: rgba(251, 113, 133, 0.15); color: var(--pv-red); }

    /* ── Toolbar row ── */
    .toolbar {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 0;
        margin-bottom: 12px;
        border-bottom: 1px solid var(--pv-border);
    }
    .toolbar-spacer { flex: 1; }

    /* ── Hide Streamlit chrome ── */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent !important; }
    [data-testid="stDeployButton"] { display: none !important; }
    .stAppDeployButton { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }

    /* ── Sidebar collapse button ── */
    [data-testid="stSidebarCollapseButton"] button {
        color: var(--pv-text-muted) !important;
        opacity: 0.5;
        transition: opacity 0.15s ease;
    }
    [data-testid="stSidebarCollapseButton"] button:hover {
        opacity: 1;
    }

    /* ── Expander cleanup ── */
    [data-testid="stExpander"] {
        border: 1px solid var(--pv-border) !important;
        border-radius: var(--radius-md) !important;
        background: var(--pv-surface) !important;
    }
    [data-testid="stExpander"] summary {
        font-size: 14px !important;
        font-weight: 500 !important;
    }

    /* ── Download buttons compact ── */
    [data-testid="stDownloadButton"] button {
        font-size: 13px !important;
        padding: 8px 14px !important;
    }

    /* ── Radio buttons ── */
    [data-testid="stRadio"] label[data-baseweb="radio"] {
        margin-right: 16px !important;
    }
    [data-testid="stRadio"] p { font-size: 14px !important; }

    /* ── Caption text ── */
    [data-testid="stCaptionContainer"] p {
        font-size: 13px !important;
    }

    /* ── Topic card equal height ── */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div > [data-testid="stVerticalBlock"] > [data-testid="element-container"] > [data-testid="stVerticalBlockBorderWrapper"] {
        height: 100% !important;
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--pv-border-light); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--pv-text-muted); }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Sidebar (Osmo-style navigation)
# ──────────────────────────────────────────────

with st.sidebar:
    st.image("assets/logo-color-white.png", width=160)
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    current = st.session_state.stage

    # Badge counts
    topic_count = (
        len(st.session_state.clusters.get("topics", []))
        if st.session_state.clusters else 0
    )
    lib_data = load_asset_library()
    lib_count = len(lib_data.get("runs", []))

    # New Run — prominent at top
    if st.button("+ New Run", key="nav_new", use_container_width=True, type="primary" if False else "secondary"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    st.markdown('<p class="section-label" style="padding-left:12px;">WORKSPACE</p>', unsafe_allow_html=True)

    # Nav: Scrape
    if st.button(
        "⌕  Scrape", key="nav_input",
        use_container_width=True,
        type="primary" if current == "input" else "secondary",
    ):
        st.session_state.stage = "input"
        st.rerun()

    # Nav: Topic Wall
    wall_label = f"▦  Topics  ({topic_count})" if topic_count else "▦  Topics"
    if st.button(
        wall_label, key="nav_select",
        use_container_width=True,
        type="primary" if current == "select" else "secondary",
    ):
        if st.session_state.clusters:
            st.session_state.stage = "select"
            st.rerun()
        else:
            st.toast("Scrape ads first", icon="⚠️")

    # Nav: Asset Library
    lib_label = f"◫  Library  ({lib_count})" if lib_count else "◫  Library"
    if st.button(
        lib_label, key="nav_library",
        use_container_width=True,
        type="primary" if current == "library" else "secondary",
    ):
        st.session_state.stage = "library"
        st.rerun()

    st.markdown("---")

    # Session info
    info_parts = []
    if st.session_state.pv_domain:
        info_parts.append(st.session_state.pv_domain)
    if st.session_state.buyer_initials:
        info_parts.append(st.session_state.buyer_initials.upper())
    if info_parts:
        st.caption(" · ".join(info_parts))

    # Generation status
    gen_id = st.session_state.get("generating_run_id")
    if gen_id:
        run = get_run(gen_id)
        if run and run.get("status") == "generating":
            st.markdown(
                '<div class="run-badge run-generating">Generating…</div>',
                unsafe_allow_html=True,
            )
        elif run and run.get("status") == "complete":
            st.session_state.generating_run_id = None
            st.markdown(
                '<div class="run-badge run-complete">✓ Ready</div>',
                unsafe_allow_html=True,
            )


# ──────────────────────────────────────────────
# Step indicator
# ──────────────────────────────────────────────

def _render_step_indicator(active):
    steps = [("input", "Scrape"), ("select", "Topics"), ("library", "Library")]
    order = [s[0] for s in steps]
    active_idx = order.index(active) if active in order else 0
    parts = []
    for i, (key, label) in enumerate(steps):
        if key == active:
            cls = "active"
        elif i < active_idx:
            cls = "completed"
        else:
            cls = ""
        parts.append(f'<span class="step-item {cls}">{label}</span>')
    html = '<span class="step-sep">›</span>'.join(parts)
    st.markdown(f'<div class="step-indicator">{html}</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# SCREEN 1: Scrape
# ──────────────────────────────────────────────

def render_input():
    _render_step_indicator("input")
    st.markdown('<p class="page-title">Scrape Competitor Ads</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Analyze competitor ads from Facebook Ad Library or CSV upload.</p>', unsafe_allow_html=True)

    with st.container(border=True):
        col_main, col_settings = st.columns([5, 3], gap="large")

        with col_main:
            st.markdown('<p class="section-label">Ad Source</p>', unsafe_allow_html=True)
            input_method = st.radio(
                "Method", ["FB Ad Library URL", "CSV Upload"],
                horizontal=True, label_visibility="collapsed",
            )

            url = ""
            uploaded_file = None
            if input_method == "FB Ad Library URL":
                url = st.text_input(
                    "URL",
                    placeholder="https://www.facebook.com/ads/library/?...&view_all_page_id=...",
                )
                st.caption("Paste the full FB Ad Library URL for any advertiser page.")
            else:
                uploaded_file = st.file_uploader("CSV", type=["csv"], label_visibility="collapsed")

        with col_settings:
            st.markdown('<p class="section-label">Launch Settings</p>', unsafe_allow_html=True)
            networks = config.get("networks", ["facebook"])
            network = st.selectbox("Destination Network", networks, index=0)
            pv_domain = st.text_input("PV Domain", placeholder="thepennypro.com")
            buyer_initials = st.text_input("Buyer Initials", placeholder="cbh", max_chars=5)

    # Action button — right-aligned, compact
    _, btn_col = st.columns([3, 1])
    with btn_col:
        do_scrape = st.button("Scrape & Analyze", type="primary", use_container_width=True)

    if do_scrape:
        if input_method == "FB Ad Library URL" and not url:
            st.error("Enter a FB Ad Library URL.")
            return
        if input_method == "CSV Upload" and not uploaded_file:
            st.error("Upload a CSV file.")
            return
        st.session_state.pv_domain = pv_domain.strip() if pv_domain else ""
        st.session_state.buyer_initials = buyer_initials.strip().lower() if buyer_initials else ""
        st.session_state.network = network

        if input_method == "CSV Upload":
            with st.spinner("Parsing CSV..."):
                from scraper.csv_fallback import parse_csv_upload
                ads = parse_csv_upload(uploaded_file)
                st.session_state.source_url = f"csv_upload:{uploaded_file.name}"
        else:
            st.session_state.source_url = url.strip()
            progress = st.progress(0, text="Connecting to Meta Ad Library API...")
            from scraper.fb_api_scraper import scrape_fb_ad_library
            result = scrape_fb_ad_library(
                url.strip(), config,
                progress_callback=lambda t, p: progress.progress(p, text=t),
            )
            if result.get("error"):
                progress.empty()
                st.error(f"Scrape failed: {result['error']}")
                return
            ads = result["ads"]
            progress.empty()
            st.success(f"Fetched **{result['successfully_parsed']}** ads from Ad Library API")

        if not ads:
            st.error("No ads found.")
            return
        st.session_state.raw_ads = ads

        with st.spinner("Clustering topics, angles, and offers..."):
            try:
                from clustering.cluster_ads import cluster_ads
                clusters = cluster_ads(ads, get_client(), config)
                st.session_state.clusters = clusters
            except Exception as e:
                st.error(f"Clustering failed: {e}")
                return

        st.session_state.stage = "select"
        st.rerun()


# ──────────────────────────────────────────────
# SCREEN 2: Topic Wall
# ──────────────────────────────────────────────

def _opp_score(topic):
    ad_count = topic.get("ad_count", 0)
    avg_days = topic.get("avg_days_active", 0)
    return ad_count * math.log(avg_days + 1, 10) if avg_days > 0 else ad_count * 0.5


def _opp_badge(score, max_score):
    if max_score == 0:
        return "High", "opp-high"
    ratio = score / max_score
    if ratio >= 0.6:
        return "High", "opp-high"
    elif ratio >= 0.3:
        return "Med", "opp-med"
    return "Low", "opp-low"


def render_select():
    _render_step_indicator("select")
    st.markdown('<p class="page-title">Topic Wall</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Select topics and angles to generate creatives for.</p>', unsafe_allow_html=True)

    # Source link
    source_url = st.session_state.source_url
    if source_url and not source_url.startswith("csv_upload"):
        st.markdown(
            f'<div class="source-bar">'
            f'Source: <a href="{source_url}" target="_blank">FB Ad Library ↗</a>'
            f'</div>',
            unsafe_allow_html=True,
        )

    clusters = st.session_state.clusters
    if not clusters or "topics" not in clusters:
        st.error("No data available. Go back to Scrape.")
        return

    topics = clusters["topics"]
    scores = [_opp_score(t) for t in topics]
    max_score = max(scores) if scores else 1
    total_angles = sum(len(t.get("angles", [])) for t in topics)

    # ── Toolbar: stats + actions on one row ──
    t_col1, t_col2, t_col3, t_col4 = st.columns([5, 1, 1, 1.5])
    with t_col1:
        st.markdown(
            f'<div class="stat-bar">'
            f'<span class="stat-pill"><strong>{len(st.session_state.raw_ads)}</strong>&nbsp;ads</span>'
            f'<span class="stat-pill"><strong>{len(topics)}</strong>&nbsp;topics</span>'
            f'<span class="stat-pill"><strong>{total_angles}</strong>&nbsp;angles</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with t_col2:
        if st.button("Select All", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key.startswith("sel_"):
                    st.session_state[key] = True
            st.rerun()
    with t_col3:
        if st.button("Clear", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key.startswith("sel_"):
                    st.session_state[key] = False
            st.rerun()

    selections = []

    for row_start in range(0, len(topics), 2):
        cols = st.columns(2, gap="medium")
        for col_idx, col in enumerate(cols):
            t_idx = row_start + col_idx
            if t_idx >= len(topics):
                break

            topic = topics[t_idx]
            rank = topic.get("rank", t_idx + 1)
            label = topic.get("topic_label", "Unknown")
            slug = topic.get("topic_slug", "unknown")
            ad_count = topic.get("ad_count", 0)
            avg_days = topic.get("avg_days_active", 0)
            top_dest = topic.get("top_destination", "")
            angles = topic.get("angles", [])
            badge_text, badge_class = _opp_badge(scores[t_idx], max_score)

            with col:
                with st.container(border=True):
                    # Header: rank + topic + opp badge
                    st.markdown(
                        f'<div class="topic-header">'
                        f'<span class="rank-num">{rank}</span>'
                        f'<span class="topic-title">{label}</span>'
                        f'<span class="opp-badge {badge_class}">{badge_text}</span>'
                        f'</div>'
                        f'<div style="font-size:13px; color:var(--pv-text-muted); margin:-4px 0 8px 38px;">'
                        f'{ad_count} ads · {avg_days}d avg'
                        f'{"  ·  " + top_dest if top_dest else ""}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    # Angles
                    selected_angles = []
                    for angle in angles:
                        a_label = angle.get("angle_label", "Unknown")
                        a_slug = angle.get("angle_slug", "unknown")
                        a_count = angle.get("angle_count", 0)
                        intent = angle.get("intent_type", "info")
                        offers = angle.get("offers_and_claims", [])

                        cb_key = f"sel_{slug}_{a_slug}"
                        if cb_key not in st.session_state:
                            st.session_state[cb_key] = True

                        checked = st.checkbox(
                            f"{a_label}  ·  {a_count} ads",
                            key=cb_key,
                            value=st.session_state[cb_key],
                        )

                        tag_html = f'<span class="pv-tag pv-tag-{intent}">{intent}</span>'
                        offers_html = "".join(
                            f'<div class="offer-item">{o}</div>'
                            for o in offers[:3]
                        )
                        st.markdown(
                            f'<div style="margin:-4px 0 8px 28px;">'
                            f'{tag_html}'
                            f'{offers_html}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                        if checked:
                            selected_angles.append(angle)

                    # Expandable details
                    with st.expander("Sample headlines"):
                        all_samples = []
                        for a in angles:
                            all_samples.extend(a.get("sample_headlines", []))
                            all_samples.extend(a.get("sample_banner_texts", []))
                        for s in all_samples[:3]:
                            st.markdown(
                                f'<div style="color:var(--pv-text-muted); font-size:13px; '
                                f'font-style:italic; margin:3px 0;">"{s[:80]}"</div>',
                                unsafe_allow_html=True,
                            )

                    if selected_angles:
                        selections.append({
                            "topic_label": label,
                            "topic_slug": slug,
                            "topic_rank": badge_text,
                            "ad_count": ad_count,
                            "angles": selected_angles,
                        })

    # Footer — compact generation bar
    st.markdown("")
    total_selected = sum(len(s["angles"]) for s in selections)

    foot1, foot2, foot3 = st.columns([3, 2, 1.5])
    with foot1:
        st.markdown(
            f'<div class="stat-bar" style="padding-top:6px;">'
            f'<span class="stat-pill"><strong>{total_selected}</strong>&nbsp;angles selected</span>'
            f'<span class="stat-pill"><strong>{total_selected * 2}</strong>&nbsp;variants</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with foot3:
        if st.button("Generate", type="primary", use_container_width=True):
            if not selections:
                st.error("Select at least one angle.")
                return
            st.session_state.selections = selections
            _start_generation(selections)


# ──────────────────────────────────────────────
# Background generation
# ──────────────────────────────────────────────

def _start_generation(selections):
    """Create a run entry, kick off background thread, navigate to Asset Library."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_data = {
        "id": run_id,
        "timestamp": datetime.now().isoformat(),
        "source_url": st.session_state.source_url,
        "network": st.session_state.network,
        "pv_domain": st.session_state.pv_domain,
        "buyer_initials": st.session_state.buyer_initials,
        "status": "generating",
        "creatives": [],
        "selections_meta": selections,
    }
    save_run(run_data)
    st.session_state.generating_run_id = run_id

    # Serialize selections_meta for the background thread (includes clustering metadata)
    selections_meta = json.loads(json.dumps(selections, default=str))

    # Get API keys — check env vars first, then Streamlit secrets
    _anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "") or st.secrets.get("ANTHROPIC_API_KEY", "")
    _openai_key = os.environ.get("OPENAI_API_KEY", "") or st.secrets.get("OPENAI_API_KEY", "")

    thread = threading.Thread(
        target=_background_generate,
        args=(
            run_id, selections, dict(config),
            _anthropic_key,
            _openai_key,
            st.session_state.pv_domain,
            st.session_state.buyer_initials,
            st.session_state.source_url,
            st.session_state.network,
            selections_meta,
        ),
        daemon=True,
    )
    thread.start()

    st.session_state.stage = "library"
    st.rerun()


def _background_generate(run_id, selections, config_dict, api_key, openai_key,
                          pv_domain, buyer_initials, source_url, network,
                          selections_meta=None):
    """Runs in background thread. Generates copy + banners, writes to asset library JSON."""
    try:
        import anthropic
        from copygen.generate_copy import generate_copy
        from utils.campaign_name import build_campaign_name

        client = anthropic.Anthropic(api_key=api_key)
        variants_data = generate_copy(selections, client, config_dict)
        creatives = variants_data.get("creatives", [])

        # Merge clustering metadata (topic_rank, intent_type, angle_count) into creatives
        if selections_meta:
            meta_lookup = {}
            for sel in selections_meta:
                for angle in sel.get("angles", []):
                    key = (sel.get("topic_slug", ""), angle.get("angle_slug", ""))
                    meta_lookup[key] = {
                        "topic_rank": sel.get("topic_rank", ""),
                        "intent_type": angle.get("intent_type", "info"),
                        "angle_count": angle.get("angle_count", 0),
                    }
            for creative in creatives:
                key = (creative.get("topic_slug", ""), creative.get("angle_slug", ""))
                meta = meta_lookup.get(key, {})
                creative["topic_rank"] = meta.get("topic_rank", "")
                creative["intent_type"] = meta.get("intent_type", "info")
                creative["angle_count"] = meta.get("angle_count", 0)

        for creative in creatives:
            creative["campaign_name"] = build_campaign_name(
                creative.get("topic_slug", "unknown"),
                creative.get("angle_slug", "unknown"),
                pv_domain, buyer_initials,
            )

        # Generate banners if enabled
        banner_cfg = config_dict.get("banner", {})
        if banner_cfg.get("enabled") and openai_key:
            os.environ["OPENAI_API_KEY"] = openai_key
            from banner.generate_banner import generate_banner_image
            for creative in creatives:
                for variant in creative.get("variants", []):
                    try:
                        variant["banner_path"] = generate_banner_image(
                            banner_text=variant.get("banner_text", ""),
                            topic=creative.get("topic", ""),
                            angle=creative.get("angle", ""),
                            primary_text=variant.get("primary_text", ""),
                            template_idx=variant.get("variant_id", 0) % 3,
                            config=config_dict,
                        )
                    except Exception as e:
                        logger.warning(f"Banner gen failed: {e}")
                        variant["banner_path"] = ""

        # Save completed run
        run = get_run(run_id)
        if run:
            run["status"] = "complete"
            run["creatives"] = creatives
            run["completed_at"] = datetime.now().isoformat()
            save_run(run)

        # Auto-log to Google Sheet
        try:
            _log_to_sheet_bg(creatives, source_url, pv_domain, buyer_initials,
                             network, config_dict)
        except Exception as e:
            logger.warning(f"Sheet log failed: {e}")

    except Exception as e:
        logger.error(f"Background generation failed: {e}")
        run = get_run(run_id)
        if run:
            run["status"] = "error"
            run["error"] = str(e)
            save_run(run)


def _log_to_sheet_bg(creatives, source_url, pv_domain, buyer_initials,
                     network, config_dict):
    """Log variants to Google Sheet (called from background thread)."""
    from sheets.tracker import connect_to_sheet, append_approved_variants, ensure_headers
    if not config_dict.get("google_sheet", {}).get("spreadsheet_id"):
        return
    ws = connect_to_sheet(config_dict)
    ensure_headers(ws)
    variants = []
    for c in creatives:
        for v in c.get("variants", []):
            variants.append({
                "approved": True,
                "topic": c.get("topic", ""),
                "angle": c.get("angle", ""),
                "variant_id": v.get("variant_id", ""),
                "variant_type": v.get("variant_type", ""),
                "headline": v.get("headline", ""),
                "primary_text": v.get("primary_text", ""),
                "banner_text": v.get("banner_text", ""),
                "banner_path": v.get("banner_path", ""),
                "campaign_name": c.get("campaign_name", ""),
            })
    append_approved_variants(
        ws, variants,
        source_url=source_url, pv_domain=pv_domain,
        buyer_initials=buyer_initials, network=network,
    )


# ──────────────────────────────────────────────
# SCREEN 3: Asset Library
# ──────────────────────────────────────────────

def render_library():
    _render_step_indicator("library")
    st.markdown('<p class="page-title">Asset Library</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Generated creative sets. Expand a run to review and download.</p>', unsafe_allow_html=True)

    lib = load_asset_library()
    runs = lib.get("runs", [])

    if not runs:
        st.markdown(
            '<div style="text-align:center; padding:48px 0; color:var(--pv-text-muted);">'
            '<p style="font-size:15px; margin-bottom:4px;">No creatives yet</p>'
            '<p style="font-size:13px;">Scrape ads and select angles to generate.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Auto-refresh if generating
    any_generating = any(r.get("status") == "generating" for r in runs)
    if any_generating:
        st.markdown(
            '<div class="run-badge run-generating" style="margin-bottom:12px;">Generating… auto-refreshing</div>',
            unsafe_allow_html=True,
        )
        import streamlit.components.v1 as components
        components.html(
            "<script>setTimeout(function(){window.parent.location.reload()}, 5000)</script>",
            height=0,
        )

    for run in runs:
        status = run.get("status", "unknown")
        ts = run.get("timestamp", "")
        domain = run.get("pv_domain", "")
        buyer = run.get("buyer_initials", "").upper()
        creatives = run.get("creatives", [])
        n_variants = sum(len(c.get("variants", [])) for c in creatives)

        try:
            dt = datetime.fromisoformat(ts)
            ts_display = dt.strftime("%b %d, %H:%M")
        except (ValueError, TypeError):
            ts_display = str(ts)[:16]

        # Status badge HTML
        if status == "generating":
            badge_html = '<span class="run-badge run-generating">Generating…</span>'
        elif status == "complete":
            badge_html = f'<span class="run-badge run-complete">✓ {n_variants} variants</span>'
        elif status == "error":
            badge_html = '<span class="run-badge run-error">Error</span>'
        else:
            badge_html = f'<span class="run-badge">{status}</span>'

        is_latest_complete = (status == "complete" and run == runs[0])

        with st.expander(
            f"{domain or 'Unknown'}  ·  {buyer}  ·  {ts_display}",
            expanded=is_latest_complete,
        ):
            st.markdown(badge_html, unsafe_allow_html=True)

            if status == "generating":
                st.caption("Generating copy and banners… you can navigate away.")
            elif status == "error":
                st.error(f"Failed: {run.get('error', 'Unknown error')}")
            elif status == "complete":
                _render_run_creatives(run)


def _render_run_creatives(run):
    """Render creatives for a completed run — variant cards + compact actions."""
    creatives = run.get("creatives", [])
    if not creatives:
        st.caption("No creatives in this run.")
        return

    for creative in creatives:
        topic = creative.get("topic", "Unknown")
        angle = creative.get("angle", "Unknown")
        campaign = creative.get("campaign_name", "")
        variants = creative.get("variants", [])

        st.markdown(
            f'<div style="margin:10px 0 4px 0;">'
            f'<span style="font-size:15px; font-weight:600; color:var(--pv-text);">{topic}</span>'
            f'<span style="color:var(--pv-text-muted); font-size:14px;"> → {angle}</span>'
            f'</div>'
            f'<div style="font-size:12px; color:var(--pv-text-muted); margin-bottom:10px; font-family:monospace;">{campaign}</div>',
            unsafe_allow_html=True,
        )

        cols = st.columns(2, gap="medium")
        for v_idx, variant in enumerate(variants[:2]):
            vid = variant.get("variant_id", v_idx + 1)
            vtype = variant.get("variant_type", "direct" if v_idx == 0 else "hook")
            banner_path = variant.get("banner_path")

            with cols[v_idx]:
                with st.container(border=True):
                    st.markdown(
                        f'<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">'
                        f'<span class="pv-tag pv-tag-{vtype}">{vtype}</span>'
                        f'<span style="color:var(--pv-text-muted); font-size:13px;">V{vid}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    if banner_path and os.path.exists(str(banner_path)):
                        st.image(banner_path, use_container_width=True)
                    else:
                        bt = variant.get("banner_text", "")
                        st.markdown(
                            f'<div class="banner-placeholder"><b>{bt}</b></div>',
                            unsafe_allow_html=True,
                        )

                    st.markdown(
                        f'<p style="font-size:14px; font-weight:600; color:var(--pv-text); margin:8px 0 4px 0;">'
                        f'{variant.get("headline", "")}</p>'
                        f'<p style="font-size:13px; color:var(--pv-text-secondary); margin:0;">'
                        f'{variant.get("primary_text", "")}</p>',
                        unsafe_allow_html=True,
                    )

    # ── Actions — single compact row ──
    from exports.zip_export import create_run_zip, build_manifest_rows

    try:
        _dt = datetime.fromisoformat(run.get("timestamp", ""))
        _run_id_str = _dt.strftime("%Y%m%d-%H%M")
    except (ValueError, TypeError):
        _run_id_str = run.get("id", "unknown")

    st.markdown('<div style="margin-top:8px; padding-top:8px; border-top:1px solid var(--pv-border);"></div>', unsafe_allow_html=True)
    btn1, btn2, btn3, btn4 = st.columns([1.2, 1.2, 1.5, 1.5])

    with btn1:
        zip_bytes = create_run_zip(run)
        st.download_button(
            "↓ ZIP",
            data=zip_bytes,
            file_name=f"run-{_run_id_str}.zip",
            mime="application/zip",
            key=f"download_{run.get('id')}",
            use_container_width=True,
        )

    with btn2:
        brief_text = _build_brief(run)
        st.download_button(
            "↓ Brief",
            data=brief_text,
            file_name=f"brief_{run.get('buyer_initials', 'xx')}_{run.get('id', '')}.txt",
            mime="text/plain",
            key=f"brief_{run.get('id')}",
            use_container_width=True,
        )

    with btn3:
        if st.button("Push to Tracker", key=f"push_{run.get('id')}", use_container_width=True):
            try:
                from sheets.tracker import (
                    connect_to_tracker_tab, run_already_pushed, push_run_to_tracker,
                )
                ws = connect_to_tracker_tab(config)
                if run_already_pushed(ws, _run_id_str):
                    st.warning("Already pushed.")
                else:
                    manifest_rows = build_manifest_rows(run)
                    count = push_run_to_tracker(ws, manifest_rows)
                    st.success(f"Pushed {count} rows.")
            except Exception as e:
                st.error(f"Failed: {e}")

    with btn4:
        # Check if already drafted to Meta
        meta_draft = run.get("meta_draft")
        if meta_draft:
            n_c = meta_draft.get("total_campaigns", 0)
            n_a = meta_draft.get("total_adsets", 0)
            st.markdown(
                f'<span style="font-size:13px; color:var(--pv-green);">'
                f'✓ {n_c} campaigns, {n_a} ad sets</span>',
                unsafe_allow_html=True,
            )
        else:
            if st.button("Draft to Meta", key=f"meta_{run.get('id')}", use_container_width=True):
                try:
                    from meta.draft_campaigns import draft_run_to_meta
                    result = draft_run_to_meta(run, config)
                    # Save the draft result to the run
                    run["meta_draft"] = result
                    save_run(run)
                    st.success(
                        f"Drafted {result['total_campaigns']} campaigns, "
                        f"{result['total_adsets']} ad sets (PAUSED)"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Meta draft failed: {e}")


def _build_brief(run):
    lines = [
        "=" * 70,
        "LAUNCH BRIEF",
        f"Generated: {run.get('timestamp', '')[:16]}",
        f"Network:   {run.get('network', '')}",
        f"PV Domain: {run.get('pv_domain', '')}",
        f"Buyer:     {run.get('buyer_initials', '')}",
        f"Source:    {run.get('source_url', '')}",
        "=" * 70, "",
    ]
    for creative in run.get("creatives", []):
        campaign = creative.get("campaign_name", "")
        lines.append(f"CAMPAIGN: {campaign}")
        lines.append(f"  Topic: {creative.get('topic', '')}")
        lines.append(f"  Angle: {creative.get('angle', '')}")
        lines.append("")
        for v in creative.get("variants", []):
            lines.append(f"  V{v.get('variant_id', '')} [{v.get('variant_type', '')}]")
            lines.append(f"    Headline:     {v.get('headline', '')}")
            lines.append(f"    Primary Text: {v.get('primary_text', '')}")
            lines.append(f"    Banner Text:  {v.get('banner_text', '')}")
            if v.get("banner_path"):
                lines.append(f"    Banner File:  {v['banner_path']}")
            lines.append("")
        lines.append("-" * 70)
        lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────

stage = st.session_state.stage
if stage == "input":
    render_input()
elif stage == "select":
    render_select()
elif stage == "library":
    render_library()
