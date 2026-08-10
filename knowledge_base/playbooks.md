# Playbooks

## Diagnosing a visibility drop

Work through these in order. Stop when one explains the size of the move.

1. **Check whether it is real.** Pull daily group visibility for 90 days. A
   single-day dip that recovers is a crawl artefact. Sustained means three or
   more consecutive days.
2. **Separate device.** Mobile-only drops usually mean a SERP layout change.
   Both devices moving together points at us or at the site.
3. **Find the movers.** Pull keywords ordered by trend descending. If fewer
   than five keywords account for most of the drop, it is keyword-specific. If
   the loss is spread thin across hundreds, it is site-wide or algorithmic.
4. **Check SERP features.** A new AI Overview or Product Grid on high-volume
   terms takes Visibility without any rank change.
5. **Check landing pages.** Compare `current` against `desired` on the affected
   keywords. A mismatch means cannibalisation or a redirect that went wrong.
6. **Check competitors.** Run domain overview on the tracked competitor set. If
   one competitor gained roughly what we lost, it is a competitive move, not a
   penalty.

Only after all six do we raise the possibility of an algorithm update, and we
never say "algorithm update" to a client without a dated, corroborated source.

## Monthly client reporting

Report against the Forecast objective, not against last month. Clients signed
up to a trajectory; month-over-month noise is not the story.

Structure every report the same way:
- One sentence on whether we are on track against the objective.
- Non-brand organic sessions versus forecast.
- The three keyword groups that moved most, with the reason for each.
- What we are doing next month, tied to SEO Opportunity scores.

Never lead with Visibility. Clients care about sessions and revenue;
Visibility is the explanation, not the headline.

## Escalation thresholds

Notify the account lead same-day when any of these is true:
- Visibility down more than 5 percentage points week-over-week
- A transactional head term drops out of the top 10
- Non-brand sessions down more than 20% versus the same week last year
- Objective status flips to `off_track`

Anything below those goes in the weekly note.

## Keyword prioritisation

Every sprint takes the top 20 by SEO Opportunity, then filters:
- Drop anything with `difficulty_top_10` = hard unless it is a strategic head term.
- Drop informational keywords if non-brand transactional traffic is below forecast.
- Keep at least three keywords where an AI Overview is present — we are building
  a position there deliberately, and the data on what works is still thin.

## What we do not do

- We do not report rank averages that include the value 100.
- We do not attribute a change to an algorithm update without a source.
- We do not quote Visibility to two decimal places. One is beyond the precision
  of the underlying estimate.
- We do not promise a specific rank by a specific date. Forecasts are ranges.
