"""
Shared Anthropic client initialization.
Reads ANTHROPIC_API_KEY from environment and returns a reusable client.
"""

import os
import anthropic


def get_claude_client():
    """Create and return an Anthropic client.

    Checks Streamlit secrets first (for cloud deployment),
    then falls back to environment variable.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # Try Streamlit secrets (for Streamlit Cloud)
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass

    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. "
            "Add it to .env (local) or Streamlit secrets (cloud)."
        )
    return anthropic.Anthropic(api_key=api_key)
