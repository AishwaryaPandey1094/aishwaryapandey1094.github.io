#!/usr/bin/env python3
"""
AI in Marketing Morning Brief Generator
Fetches RSS feeds from top marketing/AI sources, generates TLDRs via Claude API,
and outputs a beautiful static HTML page.
"""

import feedparser
import json
import os
import re
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from anthropic import Anthropic

# ── Configuration ──────────────────────────────────────────────────────────────

RSS_FEEDS = {
    # Marketing & Advertising
    "Marketing Brew": "https://www.marketingbrew.com/feed",
    "MarTech": "https://martech.org/feed",
    "AdAge": "https://adage.com/arc/outboundfeeds/rss/",
    "Digiday": "https://digiday.com/feed/",
    "Search Engine Land": "https://searchengineland.com/feed",
    "The Drum": "https://www.thedrum.com/feeds/all.xml",
    "AdExchanger": "https://www.adexchanger.com/feed/",

    # AI & Technology
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "MIT Tech Review": "https://www.technologyreview.com/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Ars Technica AI": "https://feeds.arstechnica.com/arstechnica/technology-lab",

    # Business & Strategy
    "HBR": "https://feeds.hbr.org/harvardbusiness",
    "Forbes AI": "https://www.forbes.com/ai/feed/",
}

# Keywords to filter for AI + Marketing relevance
AI_MARKETING_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "generative ai",
    "chatgpt", "claude", "llm", "large language model", "gpt",
    "martech", "marketing technology", "marketing automation",
    "personalization", "customer experience", "cx",
    "predictive analytics", "data-driven marketing",
    "programmatic", "ad tech", "adtech",
    "marketing ops", "marketing operations", "revops",
    "content generation", "ai-generated", "ai-powered",
    "customer data platform", "cdp", "crm",
    "attribution", "marketing mix", "mmm",
    "demand generation", "lead scoring", "abm",
    "search ai", "ai search", "ai overviews",
    "copilot", "agent", "agentic", "automation",
    "salesforce", "hubspot", "adobe", "google ads",
    "meta ads", "tiktok", "social media ai",
    "email marketing", "seo", "sem",
    "digital marketing", "performance marketing",
    "roi", "conversion", "funnel",
]

TARGET_ARTICLES = 20
LOOKBACK_HOURS = 72  # Cast a wider net, then rank by relevance
MAX_ARTICLES_TO_SEND = 40  # Send top candidates to Claude for TLDR


def fetch_all_feeds():
    """Fetch and parse all RSS feeds, return list of article dicts."""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    for source_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:15]:  # Top 15 per source
                # Parse publish date
                pub_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                if pub_date and pub_date < cutoff:
                    continue

                # Extract summary/description
                summary = ""
                if hasattr(entry, "summary"):
                    summary = re.sub(r"<[^>]+>", "", entry.summary)[:500]
                elif hasattr(entry, "description"):
                    summary = re.sub(r"<[^>]+>", "", entry.description)[:500]

                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()

                if not title or not link:
                    continue

                # Deduplicate by URL
                articles.append({
                    "title": title,
                    "link": link,
                    "source": source_name,
                    "summary": summary,
                    "pub_date": pub_date.isoformat() if pub_date else "",
                    "pub_date_obj": pub_date,
                })
        except Exception as e:
            print(f"  [WARN] Failed to fetch {source_name}: {e}")

    # Deduplicate by link
    seen = set()
    unique = []
    for a in articles:
        url_hash = hashlib.md5(a["link"].encode()).hexdigest()
        if url_hash not in seen:
            seen.add(url_hash)
            unique.append(a)

    return unique


def score_relevance(article):
    """Score article relevance to AI + Marketing topics."""
    text = (article["title"] + " " + article["summary"]).lower()
    score = 0
    for kw in AI_MARKETING_KEYWORDS:
        if kw in text:
            score += 1
    # Boost newer articles
    if article.get("pub_date_obj"):
        hours_ago = (datetime.now(timezone.utc) - article["pub_date_obj"]).total_seconds() / 3600
        if hours_ago < 12:
            score += 3
        elif hours_ago < 24:
            score += 2
        elif hours_ago < 48:
            score += 1
    return score


def generate_tldrs(articles):
    """Send top articles to Claude API for TLDR generation."""
    client = Anthropic()

    # Prepare article data for Claude
    article_text = ""
    for i, a in enumerate(articles):
        article_text += f"\n---\nARTICLE {i+1}:\nTitle: {a['title']}\nSource: {a['source']}\nURL: {a['link']}\nSummary: {a['summary']}\n"

    prompt = f"""You are the editor of "The AI Marketing Brief" - a daily morning digest for marketing professionals who want to stay ahead of AI trends.

Below are {len(articles)} recent articles about AI, MarTech, and Marketing. Your job:

1. Select the TOP 20 most important/interesting articles for a marketing professional.
2. For each, write a sharp 1-2 sentence TLDR that captures the "so what" for marketers. Be specific about numbers, companies, and implications. No fluff.
3. Assign each article ONE category tag from: [AI Strategy, MarTech, AdTech, Content & Creative, Data & Analytics, Search & SEO, Social Media, Email & CRM, Automation, Industry Moves, Regulation & Ethics, Customer Experience]

Return ONLY valid JSON (no markdown, no backticks, no preamble). Format:
[
  {{
    "title": "article title",
    "source": "source name",
    "url": "article url",
    "tldr": "your 1-2 sentence TLDR",
    "category": "one of the category tags above",
    "priority": "high" or "medium"
  }}
]

If fewer than 20 articles are relevant, return as many as you have. Prioritize articles that reveal strategic shifts, new product launches, data/research findings, or regulatory changes.

{article_text}
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.content[0].text.strip()
    # Clean potential markdown fences
    response_text = re.sub(r"^```json\s*", "", response_text)
    response_text = re.sub(r"\s*```$", "", response_text)

    return json.loads(response_text)


def generate_html(briefs, generated_at):
    """Generate the static HTML morning brief page."""
    date_display = generated_at.strftime("%A, %B %-d, %Y")
    time_display = generated_at.strftime("%-I:%M %p ET")

    # Group by category
    categories = {}
    for b in briefs:
        cat = b.get("category", "Other")
        categories.setdefault(cat, []).append(b)

    # Build article cards HTML
    cards_html = ""
    for i, b in enumerate(briefs):
        priority_class = "priority-high" if b.get("priority") == "high" else ""
        cards_html += f"""
        <article class="brief-card {priority_class}">
            <div class="card-header">
                <span class="card-number">{str(i+1).zfill(2)}</span>
                <span class="card-category">{b.get('category', 'AI Strategy')}</span>
                {('<span class="card-priority">BREAKING</span>' if b.get('priority') == 'high' else '')}
            </div>
            <h3 class="card-title">
                <a href="{b['url']}" target="_blank" rel="noopener">{b['title']}</a>
            </h3>
            <p class="card-tldr">{b['tldr']}</p>
            <div class="card-footer">
                <span class="card-source">{b['source']}</span>
                <a href="{b['url']}" target="_blank" rel="noopener" class="read-more">Read full article &rarr;</a>
            </div>
        </article>"""

    # Build category nav
    cat_nav = ""
    cat_counts = {}
    for b in briefs:
        cat = b.get("category", "Other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        cat_nav += f'<button class="cat-btn" data-category="{cat}">{cat} <span class="cat-count">{count}</span></button>\n'

    EMPTY_STATE_HTML = '<div class="empty-state"><h2>Brewing the brief...</h2><p>Check back at 7:00 AM ET for today\'s stories.</p></div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The AI Marketing Brief | {date_display}</title>
    <meta name="description" content="Your daily morning brief on AI in Marketing. 20 curated stories with TLDRs from top industry sources.">
    <meta property="og:title" content="The AI Marketing Brief | {date_display}">
    <meta property="og:description" content="20 curated AI + Marketing stories you need to know today.">
    <meta property="og:type" content="website">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300..700;1,9..40,300..700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --ink: #1a1a1a;
            --paper: #f8f5f0;
            --paper-warm: #f3efe8;
            --accent: #c4410a;
            --accent-light: #fff0e8;
            --muted: #6b6560;
            --border: #d4cfc8;
            --border-light: #e8e3dc;
            --high-priority: #c4410a;
            --card-bg: #ffffff;
            --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
            --shadow-hover: 0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: 'DM Sans', sans-serif;
            background: var(--paper);
            color: var(--ink);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
        }}

        .masthead {{
            border-bottom: 3px double var(--ink);
            padding: 2rem 0 1.5rem;
            text-align: center;
            background: var(--paper);
        }}

        .masthead-inner {{
            max-width: 900px;
            margin: 0 auto;
            padding: 0 1.5rem;
        }}

        .masthead-rule {{
            width: 60px;
            height: 3px;
            background: var(--accent);
            margin: 0 auto 1rem;
        }}

        .masthead h1 {{
            font-family: 'Instrument Serif', serif;
            font-size: clamp(2.2rem, 5vw, 3.5rem);
            font-weight: 400;
            letter-spacing: -0.02em;
            line-height: 1.1;
            margin-bottom: 0.3rem;
        }}

        .masthead h1 em {{
            color: var(--accent);
            font-style: italic;
        }}

        .masthead-tagline {{
            font-size: 0.95rem;
            color: var(--muted);
            font-weight: 300;
            letter-spacing: 0.03em;
            margin-bottom: 0.8rem;
        }}

        .masthead-meta {{
            display: flex;
            justify-content: center;
            gap: 1.5rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}

        .category-nav {{
            max-width: 900px;
            margin: 0 auto;
            padding: 1.2rem 1.5rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            justify-content: center;
            border-bottom: 1px solid var(--border-light);
        }}

        .cat-btn {{
            font-family: 'DM Sans', sans-serif;
            font-size: 0.78rem;
            font-weight: 500;
            padding: 0.35rem 0.8rem;
            border: 1px solid var(--border);
            border-radius: 100px;
            background: transparent;
            color: var(--muted);
            cursor: pointer;
            transition: all 0.2s ease;
            white-space: nowrap;
        }}

        .cat-btn:hover, .cat-btn.active {{
            background: var(--ink);
            color: var(--paper);
            border-color: var(--ink);
        }}

        .cat-btn .cat-count {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.65rem;
            opacity: 0.6;
            margin-left: 0.2rem;
        }}

        .cat-btn-all {{
            font-weight: 600;
            color: var(--ink);
        }}

        .content {{
            max-width: 900px;
            margin: 0 auto;
            padding: 1.5rem 1.5rem 4rem;
        }}

        .brief-count {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
        }}

        .brief-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 1.3rem 1.5rem;
            margin-bottom: 0.75rem;
            box-shadow: var(--shadow);
            transition: all 0.25s ease;
            animation: fadeInUp 0.4s ease both;
        }}

        .brief-card:hover {{
            box-shadow: var(--shadow-hover);
            border-color: var(--border);
        }}

        .brief-card.priority-high {{
            border-left: 3px solid var(--high-priority);
        }}

        .brief-card.hidden {{
            display: none;
        }}

        @keyframes fadeInUp {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .card-header {{
            display: flex;
            align-items: center;
            gap: 0.6rem;
            margin-bottom: 0.5rem;
        }}

        .card-number {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.7rem;
            font-weight: 500;
            color: var(--muted);
            opacity: 0.5;
        }}

        .card-category {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.65rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--accent);
            background: var(--accent-light);
            padding: 0.15rem 0.5rem;
            border-radius: 3px;
        }}

        .card-priority {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.6rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #fff;
            background: var(--high-priority);
            padding: 0.15rem 0.5rem;
            border-radius: 3px;
        }}

        .card-title {{
            font-family: 'Instrument Serif', serif;
            font-size: 1.2rem;
            font-weight: 400;
            line-height: 1.35;
            margin-bottom: 0.5rem;
        }}

        .card-title a {{
            color: var(--ink);
            text-decoration: none;
            transition: color 0.2s;
        }}

        .card-title a:hover {{
            color: var(--accent);
        }}

        .card-tldr {{
            font-size: 0.9rem;
            color: #444;
            line-height: 1.55;
            margin-bottom: 0.7rem;
        }}

        .card-footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .card-source {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.7rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .read-more {{
            font-size: 0.8rem;
            font-weight: 500;
            color: var(--accent);
            text-decoration: none;
            transition: opacity 0.2s;
        }}

        .read-more:hover {{
            opacity: 0.7;
        }}

        .site-footer {{
            border-top: 3px double var(--ink);
            padding: 2rem 0;
            text-align: center;
            background: var(--paper-warm);
        }}

        .footer-inner {{
            max-width: 900px;
            margin: 0 auto;
            padding: 0 1.5rem;
        }}

        .footer-brand {{
            font-family: 'Instrument Serif', serif;
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
        }}

        .footer-text {{
            font-size: 0.78rem;
            color: var(--muted);
            line-height: 1.6;
        }}

        .footer-text a {{
            color: var(--accent);
            text-decoration: none;
        }}

        .empty-state {{
            text-align: center;
            padding: 4rem 2rem;
            color: var(--muted);
        }}

        .empty-state h2 {{
            font-family: 'Instrument Serif', serif;
            font-size: 1.5rem;
            font-weight: 400;
            margin-bottom: 0.5rem;
            color: var(--ink);
        }}

        @media (max-width: 640px) {{
            .masthead-meta {{
                flex-direction: column;
                gap: 0.3rem;
            }}
            .brief-card {{
                padding: 1rem 1.2rem;
            }}
            .card-title {{
                font-size: 1.05rem;
            }}
            .card-footer {{
                flex-direction: column;
                align-items: flex-start;
                gap: 0.3rem;
            }}
        }}
    </style>
</head>
<body>

    <header class="masthead">
        <div class="masthead-inner">
            <div class="masthead-rule"></div>
            <h1>The <em>AI</em> Marketing Brief</h1>
            <p class="masthead-tagline">Your daily intelligence on AI, MarTech & the future of marketing</p>
            <div class="masthead-meta">
                <span>{date_display}</span>
                <span>{len(briefs)} stories curated</span>
                <span>Updated {time_display}</span>
            </div>
        </div>
    </header>

    <nav class="category-nav">
        <button class="cat-btn cat-btn-all active" data-category="all">All stories</button>
        {cat_nav}
    </nav>

    <main class="content">
        <p class="brief-count" id="showing-count">Showing {len(briefs)} of {len(briefs)} stories</p>
        <div class="briefs-container">
            {cards_html if cards_html else EMPTY_STATE_HTML}
        </div>
    </main>

    <footer class="site-footer">
        <div class="footer-inner">
            <p class="footer-brand">The AI Marketing Brief</p>
            <p class="footer-text">
                Auto-curated daily at 7 AM ET from Marketing Brew, MarTech, HBR, TechCrunch, VentureBeat, AdAge, and more.<br>
                TLDRs generated by Claude AI. Built by <a href="https://www.linkedin.com/in/aishwaryapandey1094/" target="_blank">Aishwarya Pandey</a>.
            </p>
        </div>
    </footer>

    <script>
        // Category filtering
        document.querySelectorAll('.cat-btn').forEach(btn => {{
            btn.addEventListener('click', () => {{
                document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                const category = btn.dataset.category;
                const cards = document.querySelectorAll('.brief-card');
                let visible = 0;

                cards.forEach(card => {{
                    const cardCat = card.querySelector('.card-category')?.textContent;
                    if (category === 'all' || cardCat === category) {{
                        card.classList.remove('hidden');
                        visible++;
                    }} else {{
                        card.classList.add('hidden');
                    }}
                }});

                document.getElementById('showing-count').textContent =
                    `Showing ${{visible}} of {len(briefs)} stories`;
            }});
        }});

        // Stagger card animations
        document.querySelectorAll('.brief-card').forEach((card, i) => {{
            card.style.animationDelay = `${{i * 0.04}}s`;
        }});
    </script>
</body>
</html>"""

    return html


def main():
    print("=" * 60)
    print("  THE AI MARKETING BRIEF - Daily Generator")
    print("=" * 60)

    # Step 1: Fetch RSS feeds
    print("\n[1/4] Fetching RSS feeds...")
    articles = fetch_all_feeds()
    print(f"  Found {len(articles)} total articles")

    if not articles:
        print("  [ERROR] No articles fetched. Generating empty page.")
        html = generate_html([], datetime.now(timezone.utc))
        with open("index.html", "w") as f:
            f.write(html)
        return

    # Step 2: Score and rank by relevance
    print("\n[2/4] Scoring relevance...")
    for a in articles:
        a["relevance_score"] = score_relevance(a)

    articles.sort(key=lambda x: -x["relevance_score"])
    top_articles = articles[:MAX_ARTICLES_TO_SEND]
    print(f"  Top {len(top_articles)} candidates selected (score range: {top_articles[0]['relevance_score']} to {top_articles[-1]['relevance_score']})")

    # Step 3: Generate TLDRs via Claude
    print("\n[3/4] Generating TLDRs via Claude API...")
    try:
        briefs = generate_tldrs(top_articles)
        print(f"  Generated {len(briefs)} TLDR briefs")
    except Exception as e:
        print(f"  [ERROR] Claude API failed: {e}")
        print("  Falling back to headlines-only mode...")
        briefs = []
        for i, a in enumerate(top_articles[:TARGET_ARTICLES]):
            briefs.append({
                "title": a["title"],
                "source": a["source"],
                "url": a["link"],
                "tldr": a["summary"][:200] + "..." if a["summary"] else "Read the full article for details.",
                "category": "AI Strategy",
                "priority": "medium",
            })

    # Step 4: Generate HTML
    print("\n[4/4] Generating HTML...")
    generated_at = datetime.now(timezone.utc)
    # Adjust to ET (UTC-5 or UTC-4 depending on DST)
    et_offset = timedelta(hours=-4)  # EDT
    generated_at_et = generated_at + et_offset

    html = generate_html(briefs, generated_at_et)

    with open("index.html", "w") as f:
        f.write(html)

    print(f"\n  ✓ index.html generated with {len(briefs)} stories")
    print(f"  ✓ Generated at {generated_at_et.strftime('%Y-%m-%d %I:%M %p')} ET")
    print("=" * 60)


if __name__ == "__main__":
    main()
