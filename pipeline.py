
import re

from agents import (
    build_reader_agent,
    writer_chain,
    run_critic,
)

from tools import web_search


# ==========================================
# EXTRACT VERIFIED SOURCES
# ==========================================

def extract_sources(scraped_content):

    sources = []
    seen_urls = set()

    pattern = (
        r"PAGE TITLE:\s*(.*?)\s*"
        r"SOURCE URL:\s*(https?://\S+)"
    )

    matches = re.findall(
        pattern,
        scraped_content,
        re.IGNORECASE
    )

    for title, url in matches:

        title = title.strip()
        url = url.strip().rstrip(".,;!?)]}")

        if url not in seen_urls:

            seen_urls.add(url)

            sources.append({
                "title": title,
                "url": url
            })

    return sources


# ==========================================
# EXTRACT READER CONTENT
# ==========================================

def extract_reader_content(reader_result):

    messages = reader_result.get("messages", [])

    reader_content = []

    for message in messages:

        content = getattr(message, "content", "")

        if not content or not str(content).strip():
            continue

        message_type = message.__class__.__name__

        if message_type == "HumanMessage":
            continue

        if message_type in ["ToolMessage", "AIMessage"]:

            text_content = str(content).strip()

            if text_content not in reader_content:
                reader_content.append(text_content)

    return "\n\n".join(reader_content)


# ==========================================
# MAIN RESEARCH PIPELINE
# ==========================================

def run_research_pipeline(topic: str) -> dict:

    state = {
        "topic": topic,
        "search_results": "",
        "scraped_content": "",
        "sources": [],
        "report": "",
        "feedback": "",
    }

    if not topic or not topic.strip():

        state["feedback"] = "Please provide a valid research topic."
        return state

    topic = topic.strip()
    state["topic"] = topic

    # ==========================================
    # STEP 1 - WEB SEARCH
    # ==========================================

    print("\n" + "=" * 50)
    print("Step 1 - Search Agent is working...")
    print("=" * 50)

    try:

        search_results = web_search.invoke({
            "query": f"Recent, reliable and detailed information about {topic}"
        })

        if not search_results:

            state["feedback"] = "Search failed: No results were found."
            return state

        state["search_results"] = str(search_results)

        print("\nSearch Results:\n")
        print(state["search_results"])

    except Exception as e:

        state["feedback"] = (
            f"Search failed: {type(e).__name__}: {e}"
        )

        print(state["feedback"])
        return state

    # ==========================================
    # STEP 2 - READER AGENT
    # ==========================================

    print("\n" + "=" * 50)
    print("Step 2 - Reader Agent is scraping resources...")
    print("=" * 50)

    try:

        reader_agent = build_reader_agent()

        reader_result = reader_agent.invoke({
            "messages": [
                (
                    "user",
                    f"""
                    Research topic: {topic}

                    Select up to 3 relevant URLs from the search results.

                    Use the scrape_url tool to read the webpages.

                    Instructions:
                    1. Choose relevant sources.
                    2. Scrape the complete URLs.
                    3. Summarize only actual scraped content.
                    4. If one webpage fails, try another URL.
                    5. Never invent facts or webpage content.
                    6. Include source titles and URLs.
                    7. Preserve PAGE TITLE and SOURCE URL labels
                       returned by the scraping tool.

                    Search Results:
                    {state["search_results"]}
                    """
                )
            ]
        })

        state["scraped_content"] = extract_reader_content(
            reader_result
        )

        print("\nScraped Content:\n")
        print(state["scraped_content"])

        if not state["scraped_content"].strip():

            state["feedback"] = (
                "Reader returned empty content. "
                "Writer was not started."
            )

            print(state["feedback"])
            return state

        # Extract successfully scraped sources
        state["sources"] = extract_sources(
            state["scraped_content"]
        )

        print("\n" + "=" * 50)
        print("VERIFIED SOURCES")
        print("=" * 50)

        if state["sources"]:

            for index, source in enumerate(
                state["sources"],
                start=1
            ):

                print(f"\n{index}. {source['title']}")
                print(f"URL: {source['url']}")

        else:

            print("No source metadata could be extracted.")

    except Exception as e:

        state["feedback"] = (
            f"Reader failed: {type(e).__name__}: {e}"
        )

        print(state["feedback"])
        return state

    # ==========================================
    # STEP 3 - WRITER AGENT
    # ==========================================

    print("\n" + "=" * 50)
    print("Step 3 - Writer Agent is preparing the report...")
    print("=" * 50)

    # Format verified sources for Writer
    verified_sources = "\n".join(
        [
            f"{index}. {source['title']} - {source['url']}"
            for index, source in enumerate(
                state["sources"],
                start=1
            )
        ]
    )

    if not verified_sources:

        verified_sources = (
            "No successfully scraped source metadata available."
        )

    research_combined = (
        "RESEARCH TOPIC:\n"
        f"{topic}\n\n"

        "SCRAPED WEBPAGE CONTENT:\n"
        f"{state['scraped_content']}\n\n"

        "VERIFIED SOURCES:\n"
        f"{verified_sources}\n\n"

        "ORIGINAL SEARCH RESULTS:\n"
        f"{state['search_results']}"
    )

    try:

        # First attempt
        research_input = research_combined[:10000]

        print(
            "\nWriter input size:",
            len(research_input),
            "characters"
        )

        report = writer_chain.invoke({
            "topic": topic,
            "research": research_input,
        })

        if report is not None:
            report = str(report).strip()

        # Second attempt if empty
        if not report:

            print("\nWriter returned an empty response.")
            print("Retrying with shorter research content...")

            research_input = research_combined[:5000]

            report = writer_chain.invoke({
                "topic": topic,
                "research": research_input,
            })

            if report is not None:
                report = str(report).strip()

        if not report:

            state["feedback"] = (
                "Writer returned an empty response after two attempts. "
                "Check the Groq model response and API configuration."
            )

            print(state["feedback"])
            return state

        # Append verified source URLs to final report
        if state["sources"]:

            source_section = "\n\n## Verified Sources\n\n"

            for index, source in enumerate(
                state["sources"],
                start=1
            ):

                source_section += (
                    f"{index}. **{source['title']}**\n"
                    f"   {source['url']}\n\n"
                )

            report += source_section

        state["report"] = report

        print("\nFinal Research Report:\n")
        print(state["report"])

    except Exception as e:

        state["feedback"] = (
            f"Writer failed: {type(e).__name__}: {e}"
        )

        print(state["feedback"])
        return state

    # ==========================================
    # STEP 4 - CRITIC AGENT
    # ==========================================

    print("\n" + "=" * 50)
    print("Step 4 - Critic Agent is evaluating the report...")
    print("=" * 50)

    try:

        report_for_review = state["report"][:5000]

        feedback = run_critic(report_for_review)

        if not feedback or not feedback.strip():

            print("\nCritic returned an empty response. Retrying...")

            feedback = run_critic(report_for_review)

        if feedback and feedback.strip():

            state["feedback"] = feedback

            print("\nCritic Evaluation:\n")
            print(feedback)

        else:

            state["feedback"] = (
                "Critic returned an empty response after retry."
            )

            print(state["feedback"])

    except Exception as e:

        state["feedback"] = (
            f"Critic failed: {type(e).__name__}: {e}"
        )

        print(state["feedback"])

    # ==========================================
    # FINAL OUTPUT
    # ==========================================

    print("\n" + "=" * 50)
    print("Research Pipeline Completed")
    print("=" * 50)

    return state


# ==========================================
# RUN PIPELINE DIRECTLY
# ==========================================

if __name__ == "__main__":

    topic = input("\nEnter a research topic: ").strip()

    if topic:

        result = run_research_pipeline(topic)

        print("\nResearch Pipeline Result:")

        print("Topic:", result["topic"])

        print(
            "Search Results Available:",
            bool(result["search_results"])
        )

        print(
            "Scraped Content Available:",
            bool(result["scraped_content"])
        )

        print(
            "Verified Sources Found:",
            len(result["sources"])
        )

        print(
            "Report Generated:",
            bool(result["report"])
        )

        print("\nCritic Feedback:")
        print(result["feedback"])

    else:

        print("Please enter a research topic.")
