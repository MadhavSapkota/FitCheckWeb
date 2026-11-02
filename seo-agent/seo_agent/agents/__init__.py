"""Six specialised agents implemented as plain Python modules (one Claude account, no extra services).

keyword_agent     - discovers and scores keyword opportunities, avoids duplicate topics
strategy_agent    - search intent + decides new page / improve existing / skip
writer_agent      - writes the guide and runs an independent editorial review
editor_agent      - writes pages, metadata, internal links, blog index, sitemap, robots
conversion_agent  - picks CTA wording/feature and places CTAs without disrupting reading
analytics_agent   - Search Console + CTA click events -> performance and improvement suggestions
"""
