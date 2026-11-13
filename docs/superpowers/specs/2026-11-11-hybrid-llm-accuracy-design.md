# Hybrid LLM Accuracy Design

**Date:** 2026-11-11  
**Status:** Approved for implementation (user: best accuracy)  
**Mode:** Accuracy-first — slower generate OK when repair runs

## Goal

Push toward ~95–99% sendable extracts without inventing content: deterministic parse first, LLM structure repair only when weak, every returned fact must be source-backed, company format only restyles.

## Rules

1. Deterministic parse always runs.
2. LLM repair at most once when eligible (0 roles + work evidence, low confidence, garbled/unresolved titles, ambiguous assignment).
3. Reject repair if any company/title/location/duration/bullet fails contiguous source match or introduces unsupported tokens.
4. Golden CI keeps `RESUME_LLM_PARSE_FALLBACK=false`.
5. Production default remains repair **on**.

## Success

- No increase in invented-fact risk (tests reject fabrications)
- Golden still green with repair off
- More weak parses eligible for grounded repair when Bedrock is available
