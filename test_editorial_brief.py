"""Test script for editorial daily brief generation with enhanced Gemini analysis."""
from google import genai
from google.genai import types

# Configure Gemini with your editorial API key
client = genai.Client(api_key="AIzaSyB_ytmUhR6FcOtSIlY2LFVRC6F7dCoRoVk")

# Test articles from today
articles = [
    {
        "headline": "Europe's Largest Crypto Miner Northern Data Scraps $200M Bitcoin Mining Unit for AI Gold Rush",
        "date": "Sun, 02 Nov 2025",
        "summary": "Europe's largest Bitcoin miner, Northern Data Group, is selling its BTC mining arm for up to $200 million. The company will reinvest proceeds into high-performance computing (HPC) and artificial intelligence (AI) infrastructure."
    },
    {
        "headline": "Microsoft's $9.7 billion deal with IREN shows bitcoin miners' AI pivot is paying off",
        "date": "Sun, 02 Nov 2025",
        "summary": "Microsoft struck a $9.7 billion deal making former bitcoin miner IREN its largest customer. Under the five-year agreement, the neo-cloud operator will provide Microsoft access to Nvidia chips at its Childress, Texas facility."
    },
    {
        "headline": "IREN Stock Soars 30% to Record $75.73 After $9.7B Microsoft AI Cloud Deal",
        "date": "Sun, 02 Nov 2025",
        "summary": "Iren Ltd soared to all-time high of $75.73, marking 613.87% increase year-over-year, driven by $9.7 billion AI infrastructure deal with Microsoft."
    },
    {
        "headline": "TeraWulf (WULF) Hits New All-Time High on New $9.5-Billion Fluidstack Deal",
        "date": "Mon, 27 Oct 2025",
        "summary": "TeraWulf soared to a new all-time high, as investors cheered a new $9.5 billion deal with Fluidstack for the joint development of a new data center at the Abernathy campus in Texas."
    },
    {
        "headline": "CleanSpark stock rises after Texas land acquisition for AI data center",
        "date": "Sun, 26 Oct 2025",
        "summary": "CleanSpark acquired rights to approximately 271 acres in Austin County, Texas, with power agreements totaling 285 megawatts for AI data center campus."
    },
    {
        "headline": "Canaan Inc. (CAN) Launches its Latest Generation Bitcoin Mining Machine, the Avalon A16 Series",
        "date": "Wed, 29 Oct 2025",
        "summary": "Canaan Inc. announced the official launch of its latest generation bitcoin mining machine, the Avalon A16 series at the Blockchain Life 2025 summit in Dubai. The A16XP air-cooled model delivers 300 terahash per second (TH/s)."
    },
    {
        "headline": "HIVE Digital's Mining Capacity Soars 283% as Firm Eyes 25 EH/s by Thanksgiving",
        "date": "Thu, 30 Oct 2025",
        "summary": "HIVE Digital hit 23 EH/s of bitcoin mining capacity, representing 283% growth this year and is on track to reach 25 EH/s before Thanksgiving."
    },
    {
        "headline": "Riot Platforms Q3 2025 beats revenue forecast",
        "date": "Wed, 29 Oct 2025",
        "summary": "Riot Platforms reported Q3 earnings with revenues at $180.2 million, compared to forecasted $169.24 million. EPS of $0.26, significantly higher than anticipated -$0.16. Stock fell by 4.89% despite positive results."
    },
    {
        "headline": "Abu Dhabi-based NIP Group expands global bitcoin mining capacity",
        "date": "Fri, 31 Oct 2025",
        "summary": "NIP Group announced expansion of Bitcoin mining operations, increasing total capacity to approximately 11.3 EH/s, becoming largest in MENA region."
    },
    {
        "headline": "UAE Telecom Giant du Enters Crypto Mining",
        "date": "Sat, 01 Nov 2025",
        "summary": "UAE-based telecom giant du has launched its Cloud Miner, a mining-as-a-service platform. Plans start at 250 terahashes for UAE residents."
    },
]

# Build the article list for the prompt
article_text = "\n\n".join([
    f"**{i+1}. {art['headline']}** ({art['date']})\n{art['summary']}"
    for i, art in enumerate(articles)
])

# Enhanced editorial prompt with research requirement
prompt = f"""You are a senior editor at SHA256 News, a premium Bitcoin mining publication read by mining executives, operators, and institutional investors.

Your task: Create a comprehensive daily brief for the last 24 hours. First, list today's mining headlines clearly. Then provide deep editorial analysis enriched with research on adjacent developments (energy, policy, tech, macro) that impact mining operations.

TODAY'S MINING STORIES:
{article_text}

BRIEF REQUIREMENTS:

**PART 1: Today's Headlines** (scannable list)
- List each story with 1-line summary
- Organized by importance/theme
- Include key numbers/facts

**PART 2: Analysis & Research** 
Go beyond the mining stories. Research and incorporate:

1. **Energy Markets**: Power prices, grid conditions, renewable trends affecting mining
2. **Policy/Regulatory**: Any crypto regulations, mining taxes, data center policies
3. **Technology**: Chip supply (Nvidia/TSMC), data center economics, cooling tech
4. **Macro Context**: What's driving BTC price, institutional moves, broader crypto trends  
5. **Adjacent Industries**: Cloud computing trends, AI compute demand, Texas/UAE infrastructure

For each mining story, ask: "What else is happening that explains this or matters for miners?"

Connect dots between:
- Mining stories AND energy news
- Corporate moves AND policy changes  
- Local developments AND global trends

**PART 3: Key Implications**
Report the factual implications and what industry experts are saying. DO NOT give advice or recommendations. Simply report:
- What industry analysts are observing
- What the data shows
- What questions these developments raise
- What trends are emerging

You are a JOURNALIST, not a consultant. Report facts and context, never prescribe action.

ETHICAL JOURNALISM STANDARDS:
- Seek truth and report it - verify all facts
- Minimize harm - respect privacy, be sensitive
- Act independently - no conflicts of interest, no advice
- Be accountable - transparent about sources and methods
- Ensure fairness - present multiple perspectives
- Verify information - fact-check everything
- Distinguish news from opinion - clearly label analysis
- Never advise or recommend - you are a reporter, not a consultant

STYLE:
- WSJ/FT quality - authoritative, analytical, factual
- Use grounded search to verify claims
- Report what experts say, not what readers should do
- Short paragraphs, precise numbers, zero hype, zero advice

OUTPUT FORMAT (Markdown):

# Daily Brief: [Date]

## Today's Headlines

**Industry Shifts**
- [Story]: [Key fact/implication]
- [Story]: [Key fact/implication]

**Operations & Capacity**  
- [Story]: [Key fact/implication]

**Market Moves**
- [Story]: [Key fact/implication]

## Analysis: [Thematic Headline]

[Editorial analysis enriched with research on energy, policy, tech trends, macro factors]

[Connect mining stories to broader context - explain WHY these things are happening NOW]

[Include relevant developments in adjacent sectors]

## Key Implications

**[Thematic Area]**: [Factual observation about what this means, what experts say, what data shows]

**[Thematic Area]**: [Factual observation about industry trends, questions raised, emerging patterns]

**[Thematic Area]**: [Factual observation about market dynamics, what companies are doing, what's changing]

Write the brief now. Use your knowledge to add depth beyond just the mining articles."""

print("=" * 80)
print("GENERATING EDITORIAL DAILY BRIEF WITH GOOGLE SEARCH GROUNDING...")
print("=" * 80)
print()

# Configure grounding tool for real-time Google Search
grounding_tool = types.Tool(
    google_search=types.GoogleSearch()
)

config = types.GenerateContentConfig(
    tools=[grounding_tool],
    temperature=0.7,
)

# Generate the brief with grounding
response = client.models.generate_content(
    model="gemini-2.0-flash-exp",
    contents=prompt,
    config=config,
)

brief = response.text

# Show grounding metadata if available
if hasattr(response, 'candidates') and response.candidates:
    candidate = response.candidates[0]
    if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
        print("\n" + "=" * 80)
        print("GROUNDING METADATA (Sources Used):")
        print("=" * 80)
        metadata = candidate.grounding_metadata
        if hasattr(metadata, 'web_search_queries') and metadata.web_search_queries:
            print("\nSearch queries executed:")
            for query in metadata.web_search_queries:
                print(f"  - {query}")
        if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
            print(f"\nSources cited: {len(metadata.grounding_chunks)}")
        print("="* 80 + "\n")

print(brief)
print()
print("=" * 80)
print("BRIEF COMPLETE")
print("=" * 80)

# Save to file
with open("/tmp/editorial_brief_test.md", "w") as f:
    f.write(brief)

print("\nSaved to: /tmp/editorial_brief_test.md")
print("\nTo view:")
print("  cat /tmp/editorial_brief_test.md")
