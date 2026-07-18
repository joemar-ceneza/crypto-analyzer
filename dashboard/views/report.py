"""Market Report view — the full automated report, rendered and downloadable."""

import streamlit as st

from ai import analyzer
from analysis import report_generator
from dashboard import loaders


def render(analysis: dict) -> None:
    """Generates and displays the automated market report."""
    narrative = analyzer.run_narrative(analysis)
    confluence_result = loaders.load_confluence(analysis["symbol"])
    report_markdown = report_generator.generate_report(
        analysis, narrative, confluence_result
    )
    st.download_button(
        "⬇️ Download report (.md)", report_markdown,
        file_name=f"{analysis['symbol'].replace('/', '-')}_report.md",
    )
    st.markdown(report_markdown)
