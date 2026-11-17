
import re

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

from tools import web_search, scrape_url

load_dotenv()


# ==========================================
# 1. INITIALIZE LLM MODELS
# ==========================================

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=2000
)

writer_llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=3000
)

critic_llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=1500
)


# ==========================================
# 2. SEARCH AGENT
# ==========================================

def build_search_agent():

    search_agent = create_agent(
        model=llm,
        tools=[web_search],
        system_prompt="""
        You are an expert web research agent.

        Your responsibilities:
        1. Search the web for the requested topic.
        2. Use the web_search tool to collect information.
        3. Use actual search results only.
        4. Preserve source titles and complete URLs.
        5. Never invent facts, sources, or URLs.
        6. Present the search results clearly.
        """
    )

    return search_agent


# ==========================================
# 3. READER AGENT
# ==========================================


def build_reader_agent():

    reader_agent = create_agent(
        model=llm,
        tools=[scrape_url],
        system_prompt="""
        You are an expert webpage research agent.

        Your main task is to extract information from actual webpages.

        Follow these steps carefully:

        1. Read the search results provided by the user.
        2. Identify up to 3 relevant HTTP or HTTPS webpage URLs.
        3. Call the scrape_url tool for each selected URL.
        4. Read the actual content returned by the scrape_url tool.
        5. Summarize the extracted webpage content.
        6. Include the webpage title and original URL for each source.
        7. If one URL fails, continue with the next available URL.
        8. Do not use search snippets as a substitute for scraped content.
        9. Never invent facts or webpage content.

        IMPORTANT:
        - You must attempt to use the scrape_url tool.
        - Only report content actually returned by the tool.
        - If no webpage can be scraped, clearly explain why.
        - Always return a final text response.
        """
    )

    return reader_agent


# ==========================================
# 4. WRITER AGENT
# ==========================================

writer_prompt = ChatPromptTemplate.from_messages([

    (
        "system",
        """
        You are a professional AI research writer.

        Your task is to prepare clear, accurate and informative
        research reports using the supplied research material.

        Rules:
        1. Use only the supplied research.
        2. Never invent facts, statistics or sources.
        3. Distinguish confirmed facts from estimates and predictions.
        4. Avoid unnecessary repetition.
        5. Explain important findings clearly.
        6. Mention limitations when evidence is insufficient.
        7. Include the exact source URLs provided.

        Write approximately 500-700 words.

        Complete every section of the report.
        """
    ),

    (
        "human",
        """
        Prepare a research report about:

        {topic}

        Research gathered:

        {research}

        Use the following structure:

        1. Introduction

        2. Key Findings
           - Finding 1
           - Finding 2
           - Finding 3
           - Additional findings if relevant

        3. Conclusion

        4. Sources
           - Include the exact URLs supplied.

        Make the report professional, readable and well-organized.
        """
    )

])

writer_chain = writer_prompt | writer_llm | StrOutputParser()


# ==========================================
# 5. CRITIC AGENT
# ==========================================

critic_prompt = ChatPromptTemplate.from_messages([

    (
        "system",
        """
        You are an independent AI research report evaluator.

        Evaluate the report carefully using the available content.

        Do not assume claims are correct simply because
        they are written confidently.

        Do not claim that you independently verified sources.

        Evaluate using these scoring criteria:

        1. Factual accuracy and evidence: 0-3
        2. Source quality and traceability: 0-2
        3. Analysis and completeness: 0-2
        4. Organization and clarity: 0-2
        5. Limitations and balanced conclusions: 0-1

        IMPORTANT SCORING RULES:

        - Give a score for every criterion.
        - Stay within each criterion's maximum score.
        - Do not invent evidence.
        - Do not calculate or guess the final total.
        - Python will calculate the final score.
        - Provide specific strengths and improvements.

        Use this exact structure:

        Scoring Breakdown:
        - Factual accuracy and evidence: X/3
        - Source quality and traceability: X/2
        - Analysis and completeness: X/2
        - Organization and clarity: X/2
        - Limitations and balanced conclusions: X/1

        Strengths:
        - Two specific strengths.

        Areas to Improve:
        - Two specific improvements.

        One line verdict:
        - A complete sentence summarizing report quality.

        Finish every section.
        """
    ),

    (
        "human",
        """
        Evaluate the following research report:

        {report}
        """
    )

])

critic_chain = critic_prompt | critic_llm | StrOutputParser()


# ==========================================
# 6. PYTHON CRITIC SCORE CALCULATION
# ==========================================

def calculate_critic_score(feedback: str) -> str:
    """
    Calculate the final Critic score using Python.

    The final score is calculated by adding the
    five individual scoring criteria.
    """

    criteria = [

        (
            r"Factual accuracy and evidence:\s*(\d+(?:\.\d+)?)\s*/\s*3",
            3
        ),

        (
            r"Source quality and traceability:\s*(\d+(?:\.\d+)?)\s*/\s*2",
            2
        ),

        (
            r"Analysis and completeness:\s*(\d+(?:\.\d+)?)\s*/\s*2",
            2
        ),

        (
            r"Organization and clarity:\s*(\d+(?:\.\d+)?)\s*/\s*2",
            2
        ),

        (
            r"Limitations and balanced conclusions:\s*(\d+(?:\.\d+)?)\s*/\s*1",
            1
        )

    ]

    total = 0.0

    for pattern, maximum in criteria:

        match = re.search(
            pattern,
            feedback,
            re.IGNORECASE
        )

        if not match:

            return (
                "Critic scoring error: One or more scoring "
                "criteria are missing or incorrectly formatted.\n\n"
                + feedback
            )

        score = float(match.group(1))

        if score < 0 or score > maximum:

            return (
                f"Critic scoring error: Invalid score. "
                f"Maximum allowed is {maximum}.\n\n"
                + feedback
            )

        total += score

    # Calculate final score using Python.

    total_text = f"{total:g}/10"

    # Replace any score generated by the LLM.

    score_line = re.search(
        r"(?im)^\s*Score\s*:.*$",
        feedback
    )

    if score_line:

        feedback = (
            feedback[:score_line.start()]
            + f"Score: {total_text}"
            + feedback[score_line.end():]
        )

    else:

        feedback = (
            f"Score: {total_text}\n\n"
            + feedback
        )

    return feedback.strip()


# ==========================================
# 7. RUN CRITIC
# ==========================================

def run_critic(report: str) -> str:

    if not report or not report.strip():

        return (
            "The report is empty. "
            "The Critic cannot evaluate it."
        )

    try:

        result = critic_chain.invoke({
            "report": report[:6000]
        })

        if not result or not result.strip():

            return "The Critic returned an empty response."

        # Calculate final score using Python.

        corrected_feedback = calculate_critic_score(
            result
        )

        return corrected_feedback

    except Exception as exc:

        print("Critic error:", repr(exc))

        return (
            f"Critic failed: {type(exc).__name__}: {exc}"
        )
