# Metric definitions

Replace the placeholder policy numbers below with your own before going live.
Everything in this folder is what the bot treats as authoritative about how we
work, so wrong content here produces confidently wrong answers.

## Visibility

Share of the total available search demand our tracked keywords actually
capture, weighted by search volume and by the click-through rate of the
position we hold. A keyword with 50,000 monthly searches ranking 3rd moves
Visibility far more than one with 200 searches ranking 1st.

Reported separately for desktop and mobile. When a client asks about
"Visibility" without qualifying, we report mobile, because that is where the
majority of their demand sits.

A Visibility change under 2 percentage points week-over-week is noise. Do not
raise it in a report unless it is part of a four-week trend.

## Rank

Position in the organic results, 1-100. **A rank of 100 means the keyword was
not found anywhere in the top 100** — it is a sentinel value, not a position.
Never average ranks without excluding 100s, or the average becomes meaningless
the moment a keyword falls off.

`trend` is the change over the requested timeframe. Negative is an improvement,
because the number got smaller.

## SEO Opportunity

A 1-10 score combining search volume, current rank, difficulty of reaching the
top 10, and the additional sessions the keyword would deliver if it got there.
It answers "what should we work on next", not "how are we doing".

We prioritise keywords scoring 7 or above with a `difficulty_top_10` of easy or
medium. Anything scoring 9-10 but rated hard goes into the long-term content
plan rather than the current sprint.

## Share of Voice

Our Visibility as a proportion of the combined Visibility of us plus the
tracked competitor set. Use this when the client asks about competitors;
use Visibility when they ask about themselves.

## AI Overview presence

`my_brand_present` means our domain is cited inside Google's AI Overview.
`any_brand_present` means an AI Overview appeared at all. Both matter: an AI
Overview appearing at all typically suppresses clicks to position 1, so a
keyword can hold rank 1 and still lose traffic.

Track this on every commercial-intent head term. It is now the most common
explanation for "rank flat, traffic down".

## SERP feature codes

The API returns abbreviated feature names. Full mapping:

aio AI Overview · aib AI Button · adt Ads Pack Top · def Definitions ·
dir Directions · fsn Featured Snippet · flt Flights · htl Hotels ·
img Images Pack · job Jobs · kng Knowledge Graph · geo Local Pack ·
shp Product Listing · rcp Recipes · qns Questions · new Top Stories ·
vid Video Carousel · app Apps · prd Product Grid · plc Places ·
pls Places Sites · tst Top Sights Grid · vdi Visual Digest ·
dan Direct Answer · fla Flights Airlines · fls Flights Sites ·
ttk Things to Know

## Search intent

SEOmonitor classifies keywords as informational, navigational, commercial or
transactional. We hold different rank targets by intent: top 3 for
transactional, top 5 for commercial, top 10 for informational. Do not report an
informational keyword at position 8 as underperforming.

## Traffic segments

Organic sessions are split into brand and non-brand. Brand traffic tracks
marketing spend and PR, not SEO work. Every performance claim we make should be
about non-brand unless we say otherwise explicitly.
