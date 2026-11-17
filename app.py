
import re
import html
from urllib.parse import urlparse

import streamlit as st

from database import (
    initialize_database,
    save_research,
    get_all_research,
    get_research_by_id,
    delete_research,
)

from agents import writer_chain, run_critic
from tools import web_search, scrape_url


# ==================================================
# PAGE CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="AI Research Studio",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

initialize_database()


# ==================================================
# CUSTOM CSS
# ==================================================

st.markdown("""
<style>

.stApp {
    background-color: #0b1020;
    color: #e5e7eb;
}

.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1450px;
}

[data-testid="stSidebar"] {
    background-color: #111827;
    border-right: 1px solid #273449;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #ffffff;
}

h1, h2, h3 {
    color: #f8fafc !important;
}

.hero {
    background: linear-gradient(
        120deg,
        #172554,
        #312e81,
        #1e1b4b
    );
    border: 1px solid #3730a3;
    padding: 30px;
    border-radius: 18px;
    margin-bottom: 25px;
}

.hero-title {
    color: white;
    font-size: 32px;
    font-weight: 800;
    margin-bottom: 8px;
}

.hero-subtitle {
    color: #c7d2fe;
    font-size: 15px;
}

.metric-card {
    background: #151e31;
    border: 1px solid #293750;
    border-radius: 14px;
    padding: 20px;
    min-height: 115px;
}

.metric-label {
    color: #94a3b8;
    font-size: 13px;
    margin-bottom: 10px;
}

.metric-value {
    color: #f8fafc;
    font-size: 27px;
    font-weight: 750;
    overflow-wrap: anywhere;
}

.section-card {
    background: #151e31;
    border: 1px solid #293750;
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 15px;
}

.small-muted {
    color: #94a3b8;
    font-size: 13px;
}

.stButton > button {
    border-radius: 9px;
    font-weight: 600;
    min-height: 42px;
}

.stTextInput input {
    border-radius: 9px;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 12px;
    border-bottom: 1px solid #293750;
}

.stTabs [data-baseweb="tab"] {
    color: #cbd5e1;
    font-weight: 600;
}

.stTabs [aria-selected="true"] {
    color: #818cf8 !important;
}

hr {
    border-color: #293750;
}

[data-testid="stStatusWidget"] {
    border-radius: 12px;
}

.footer {
    color: #64748b;
    text-align: center;
    font-size: 12px;
    padding-top: 35px;
}

</style>
""", unsafe_allow_html=True)


# ==================================================
# HELPER FUNCTIONS
# ==================================================

def extract_urls(search_results):
    """Extract unique URLs from search results."""

    urls = re.findall(
        r"""https?://[^\s<>"']+""",
        search_results or ""
    )

    cleaned_urls = []

    for url in urls:

        url = url.rstrip(".,;:!?)]}")

        if url not in cleaned_urls:
            cleaned_urls.append(url)

    return cleaned_urls[:3]


def extract_verified_sources(scraped_content):
    """Extract actual scraped webpage titles and final URLs."""

    sources = []
    seen_urls = set()

    pattern = (
        r"PAGE TITLE:\s*(.*?)\s*"
        r"SOURCE URL:\s*(https?://\S+)"
    )

    matches = re.findall(
        pattern,
        scraped_content or "",
        re.IGNORECASE
    )

    for title, url in matches:

        title = title.strip()
        url = url.strip().rstrip(".,;!?)]}")

        parsed = urlparse(url)

        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
        ):
            continue

        if url not in seen_urls:

            seen_urls.add(url)

            sources.append({
                "title": title,
                "url": url
            })

    return sources


def output_to_text(output):
    """Convert tool output into readable text."""

    if isinstance(output, str):
        return output

    if isinstance(output, dict):
        return str(output)

    if isinstance(output, list):
        return "\n".join(str(item) for item in output)

    return str(output)


def get_critic_score(feedback):
    """Extract critic score from feedback."""

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*/\s*10",
        feedback or ""
    )

    if match:
        return match.group(1) + "/10"

    return "N/A"


def add_verified_sources(report, sources):
    """Append one verified source section to the report."""

    if not sources:
        return report

    # Avoid adding a duplicate section.
    if re.search(
        r"^##\s+Verified Sources\s*$",
        report,
        re.IGNORECASE | re.MULTILINE
    ):
        return report

    source_section = "\n\n## Verified Sources\n\n"

    for index, source in enumerate(sources, start=1):

        source_section += (
            f"{index}. **{source['title']}**\n"
            f"   {source['url']}\n\n"
        )

    return report + source_section


# ==================================================
# RESEARCH PIPELINE
# ==================================================

def run_pipeline_ui(topic):

    result = {
        "search_results": "",
        "scraped_content": "",
        "sources": [],
        "report": "",
        "feedback": "",
    }

    # ----------------------------------------------
    # STAGE 1: SEARCH
    # ----------------------------------------------

    with st.status(
        "Stage 1/4: Searching the web...",
        expanded=True
    ) as status:

        search_output = web_search.invoke({
            "query": (
                f"Recent, reliable and detailed information "
                f"about {topic}"
            )
        })

        result["search_results"] = output_to_text(
            search_output
        )

        if (
            not result["search_results"].strip()
            or result["search_results"].startswith(
                ("Web search failed:", "Search failed:")
            )
        ):
            raise RuntimeError(result["search_results"])

        status.update(
            label="Stage 1/4: Search completed",
            state="complete"
        )

    # ----------------------------------------------
    # STAGE 2: WEBPAGE SCRAPING
    # ----------------------------------------------

    with st.status(
        "Stage 2/4: Reading webpages...",
        expanded=True
    ) as status:

        urls = extract_urls(result["search_results"])

        scraped_pages = []

        scraping_errors = (
            "Scraping failed:",
            "Could not read webpage.",
            "Could not extract readable content",
            "The webpage did not contain readable text."
        )

        if not urls:

            result["scraped_content"] = (
                "No URLs were found in the search results."
            )

        else:

            for index, url in enumerate(urls, start=1):

                st.write(
                    f"Reading source {index} of {len(urls)}"
                )

                st.caption(url)

                try:

                    page_output = scrape_url.invoke({
                        "url": url
                    })

                    page_text = output_to_text(page_output)

                    if (
                        page_text.strip()
                        and not page_text.startswith(scraping_errors)
                    ):

                        scraped_pages.append(
                            f"SOURCE {index}\n"
                            f"{page_text[:5000]}"
                        )

                        st.success(
                            f"Source {index} read successfully."
                        )

                    else:

                        st.warning(
                            f"Source {index} could not be read."
                        )

                        st.caption(page_text[:500])

                except Exception as exc:

                    st.warning(
                        f"Source {index} failed: {exc}"
                    )

        if scraped_pages:

            result["scraped_content"] = "\n\n".join(
                scraped_pages
            )

        else:

            result["scraped_content"] = (
                "No webpage content could be extracted. "
                "The report will use search results only."
            )

            st.warning(
                "No webpages were successfully scraped."
            )

        # Extract actual scraped sources.
        result["sources"] = extract_verified_sources(
            result["scraped_content"]
        )

        status.update(
            label="Stage 2/4: Webpage reading completed",
            state="complete"
        )

    # ----------------------------------------------
    # STAGE 3: WRITER
    # ----------------------------------------------

    with st.status(
        "Stage 3/4: Generating research report...",
        expanded=True
    ) as status:

        verified_sources = "\n".join(
            [
                f"{index}. {source['title']} - {source['url']}"
                for index, source in enumerate(
                    result["sources"],
                    start=1
                )
            ]
        )

        if not verified_sources:
            verified_sources = "No verified sources available."

        research_material = (
            "RESEARCH TOPIC:\n"
            f"{topic}\n\n"

            "WEB SEARCH RESULTS:\n"
            f"{result['search_results']}\n\n"

            "SCRAPED WEBPAGE CONTENT:\n"
            f"{result['scraped_content']}\n\n"

            "VERIFIED SOURCES:\n"
            f"{verified_sources}\n\n"

            "WRITING INSTRUCTIONS:\n"
            "Use the supplied research material. "
            "Do not invent sources, statistics or URLs. "
            "Distinguish supported facts from uncertain claims. "
            "Use the verified sources where relevant."
        )

        report = writer_chain.invoke({
            "topic": topic,
            "research": research_material[:10000],
        })

        result["report"] = str(report or "").strip()

        if not result["report"]:

            raise RuntimeError(
                "The Writer Agent returned an empty report."
            )

        # Add actual scraped source URLs.
        result["report"] = add_verified_sources(
            result["report"],
            result["sources"]
        )

        status.update(
            label="Stage 3/4: Report generated",
            state="complete"
        )

    # ----------------------------------------------
    # STAGE 4: CRITIC
    # ----------------------------------------------

    with st.status(
        "Stage 4/4: Evaluating research report...",
        expanded=True
    ) as status:

        result["feedback"] = run_critic(
            result["report"][:5000]
        )

        if not result["feedback"].strip():

            result["feedback"] = (
                "The Critic Agent did not return feedback."
            )

        status.update(
            label="Stage 4/4: Evaluation completed",
            state="complete"
        )

    return result


# ==================================================
# REUSABLE METRIC CARD
# ==================================================

def metric_card(label, value):

    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">
                {safe_label}
            </div>
            <div class="metric-value">
                {safe_value}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ==================================================
# RESEARCH RESULT DISPLAY
# ==================================================

def display_research_result(result, key_prefix):

    report = result.get("report", "")
    feedback = result.get("feedback", "")
    scraped = result.get("scraped_content", "")
    search = result.get("search_results", "")

    # Extract sources from saved scraped content too.
    sources = extract_verified_sources(scraped)

    # Calculate metrics.
    search_count = len(extract_urls(search))
    verified_count = len(sources)

    critic_score = get_critic_score(feedback)

    st.markdown("## Research Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        metric_card(
            "SEARCH RESULTS",
            search_count
        )

    with col2:
        metric_card(
            "VERIFIED SOURCES",
            verified_count
        )

    with col3:
        metric_card(
            "REPORT STATUS",
            "Ready" if report else "Pending"
        )

    with col4:
        metric_card(
            "CRITIC SCORE",
            critic_score
        )

    st.write("")

    # Research tabs.
    tab1, tab2, tab3, tab4 = st.tabs([
        "📄 Final Report",
        "⭐ Critic Evaluation",
        "🌐 Verified Sources",
        "🔎 Search Results",
    ])

    # ----------------------------------------------
    # REPORT TAB
    # ----------------------------------------------

    with tab1:

        if report:

            st.markdown(report)

            st.download_button(
                "⬇️ Download Research Report",
                data=report,
                file_name="research_report.md",
                mime="text/markdown",
                key=f"{key_prefix}_report"
            )

        else:

            st.info("No research report available.")

    # ----------------------------------------------
    # CRITIC TAB
    # ----------------------------------------------

    with tab2:

        if feedback:

            st.markdown(feedback)

            st.download_button(
                "⬇️ Download Critic Evaluation",
                data=feedback,
                file_name="critic_feedback.txt",
                mime="text/plain",
                key=f"{key_prefix}_critic"
            )

        else:

            st.info("No critic evaluation available.")

    # ----------------------------------------------
    # VERIFIED SOURCES TAB
    # ----------------------------------------------

    with tab3:

        if sources:

            st.markdown("### Successfully Scraped Sources")

            for index, source in enumerate(
                sources,
                start=1
            ):

                safe_title = html.escape(source["title"])
                safe_url = html.escape(
                    source["url"],
                    quote=True
                )

                st.markdown(
                    f"""
                    **{index}. {safe_title}**

                    [Open source webpage]({safe_url})
                    """
                )

                st.divider()

            st.download_button(
                "⬇️ Download Source List",
                data="\n".join(
                    [
                        f"{index}. {source['title']}\n{source['url']}"
                        for index, source in enumerate(
                            sources,
                            start=1
                        )
                    ]
                ),
                file_name="verified_sources.txt",
                mime="text/plain",
                key=f"{key_prefix}_verified_sources"
            )

        else:

            st.info(
                "No verified scraped sources are available."
            )

        if scraped:

            with st.expander("View Full Scraped Content"):

                st.text_area(
                    "Extracted webpage content",
                    value=scraped,
                    height=450,
                    key=f"{key_prefix}_scraped"
                )

                st.download_button(
                    "⬇️ Download Scraped Content",
                    data=scraped,
                    file_name="scraped_sources.txt",
                    mime="text/plain",
                    key=f"{key_prefix}_scraped_download"
                )

    # ----------------------------------------------
    # SEARCH RESULTS TAB
    # ----------------------------------------------

    with tab4:

        if search:

            st.text_area(
                "Tavily search results",
                value=search,
                height=450,
                key=f"{key_prefix}_search"
            )

        else:

            st.info("No search results available.")


# ==================================================
# SIDEBAR
# ==================================================

with st.sidebar:

    st.markdown(
        """
        <div style="padding:12px 0 20px 0;">
            <div style="font-size:28px;font-weight:800;color:white;">
                🔎 Research Studio
            </div>
            <div style="font-size:12px;color:#94a3b8;">
                MULTI-AGENT AI PLATFORM
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.divider()

    page = st.radio(
        "WORKSPACE",
        [
            "New Research",
            "Research History"
        ],
        key="navigation_page"
    )

    st.divider()

    st.markdown("### ⚙️ Research Pipeline")

    st.markdown(
        """
        **01 · Search Agent**

        Find relevant sources.

        **02 · Reader / Scraper**

        Extract webpage content.

        **03 · Writer Agent**

        Generate research reports.

        **04 · Critic Agent**

        Evaluate report quality.

        **05 · SQLite Database**

        Store research history.
        """
    )

    st.divider()

    st.caption("Powered by")

    st.markdown(
        """
        - Groq LLM
        - Tavily Search
        - LangChain
        - Streamlit
        - SQLite
        """
    )

    if st.button(
        "🧹 Clear Current Results",
        use_container_width=True
    ):

        st.session_state.pop("result", None)
        st.session_state.pop("topic", None)
        st.session_state.pop("saved_record_id", None)

        st.rerun()


# ==================================================
# PAGE 1: NEW RESEARCH
# ==================================================

if page == "New Research":

    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">
                Welcome to AI Research Studio
            </div>
            <div class="hero-subtitle">
                Research smarter. Discover information.
                Generate reports with intelligent AI agents.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("### 🚀 Start a New Research Project")

    st.markdown(
        '<div class="small-muted">'
        'Enter a topic and let your AI research team do the work.'
        '</div>',
        unsafe_allow_html=True
    )

    with st.form("research_form"):

        topic_input = st.text_input(
            "Research Topic",
            placeholder=(
                "Example: Applications of AI in healthcare"
            )
        )

        run_clicked = st.form_submit_button(
            "🚀 Start AI Research",
            type="primary",
            use_container_width=True
        )

    if run_clicked:

        topic = topic_input.strip()

        if not topic:

            st.warning("Please enter a research topic.")

        else:

            st.session_state.pop("result", None)
            st.session_state.pop("topic", None)
            st.session_state.pop("saved_record_id", None)

            try:

                result = run_pipeline_ui(topic)

                st.session_state["result"] = result
                st.session_state["topic"] = topic

                try:

                    record_id = save_research(
                        topic,
                        result
                    )

                    st.session_state["saved_record_id"] = record_id

                    st.success(
                        f"Research completed and saved! "
                        f"Record ID: #{record_id}"
                    )

                except Exception as exc:

                    st.warning(
                        f"Research completed, but saving failed: {exc}"
                    )

            except Exception as exc:

                st.error(f"Research failed: {exc}")

    # Show current result.

    current_result = st.session_state.get("result")

    if current_result:

        st.divider()

        st.subheader(
            st.session_state.get(
                "topic",
                "Research Report"
            )
        )

        display_research_result(
            current_result,
            "new_research"
        )

    else:

        st.markdown("")

        st.markdown(
            """
            <div class="section-card">
                <h3>🤖 Your AI Research Team</h3>
                <p style="color:#94a3b8;">
                    Four intelligent stages work together to turn
                    your research topic into a structured report.
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            metric_card("01 · SEARCH", "Discover")

        with col2:
            metric_card("02 · READER", "Extract")

        with col3:
            metric_card("03 · WRITER", "Generate")

        with col4:
            metric_card("04 · CRITIC", "Evaluate")


# ==================================================
# PAGE 2: RESEARCH HISTORY
# ==================================================

elif page == "Research History":

    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">
                📚 Research Library
            </div>
            <div class="hero-subtitle">
                Access, review and manage your previous AI research.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    try:

        history = get_all_research()

    except Exception as exc:

        st.error(f"Could not load research history: {exc}")
        history = []

    # History summary.

    col1, col2 = st.columns(2)

    with col1:

        metric_card(
            "TOTAL RESEARCH REPORTS",
            len(history)
        )

    with col2:

        metric_card(
            "DATABASE",
            "Connected"
        )

    st.write("")

    if not history:

        st.info(
            "Your research library is empty. "
            "Create your first report from New Research."
        )

    else:

        st.markdown("### Select a Research Report")

        history_options = {
            (
                f"#{item['id']} | {item['topic']} | "
                f"{item['created_at']}"
            ): item["id"]
            for item in history
        }

        selected_label = st.selectbox(
            "Research records",
            options=list(history_options.keys()),
            key="history_selection"
        )

        selected_id = history_options[selected_label]

        try:

            saved = get_research_by_id(selected_id)

            if saved:

                st.subheader(
                    saved.get("topic", "Untitled Research")
                )

                st.caption(
                    f"Record #{saved['id']} · "
                    f"Created {saved['created_at']}"
                )

                saved_result = {
                    "report": saved.get("report") or "",
                    "feedback": saved.get("critic_feedback") or "",
                    "search_results": saved.get("search_results") or "",
                    "scraped_content": saved.get("scraped_content") or "",
                }

                display_research_result(
                    saved_result,
                    f"history_{saved['id']}"
                )

                st.divider()

                with st.expander(
                    "🗑️ Delete Research Record"
                ):

                    st.warning(
                        "Deleting this record permanently removes "
                        "it from your research history."
                    )

                    confirm_delete = st.checkbox(
                        "I confirm that I want to delete this record.",
                        key=f"confirm_{saved['id']}"
                    )

                    if st.button(
                        "Delete Selected Record",
                        disabled=not confirm_delete,
                        key=f"delete_{saved['id']}"
                    ):

                        try:

                            delete_research(saved["id"])

                            st.success(
                                "Research record deleted successfully."
                            )

                            st.rerun()

                        except Exception as exc:

                            st.error(
                                f"Deletion failed: {exc}"
                            )

            else:

                st.warning(
                    "Selected research record was not found."
                )

        except Exception as exc:

            st.error(
                f"Could not load selected research: {exc}"
            )


# ==================================================
# FOOTER
# ==================================================

st.markdown(
    """
    <div class="footer">
        AI Research Studio · Multi-Agent Research System
        <br>
        Built with Python, LangChain, Groq, Tavily and Streamlit
    </div>
    """,
    unsafe_allow_html=True
)
