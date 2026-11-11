/* Plain-English check descriptions; no dataset observations. */
const KuinaReasons = {
  "mixed_price_construction": [
    "Prices combine trades and quote midpoints",
    "The meaning is known: these prices mix executed trades with the midpoint between bid and ask quotes. They do not meet the agreed requirement for clearly labelled trade or bid candles."
  ],
  "inconsistent_ohlc": [
    "Price candle values contradict each other",
    "The opening, highest, lowest or closing price does not fit the others; for example, the highest price is below the closing price."
  ],
  "ohlc_check_missing": [
    "The price candle consistency check is missing",
    "We have not established whether each candle has sensible opening, highest, lowest and closing prices."
  ],
  "not_source_observations": [
    "We cannot confirm these are recorded historical values",
    "The files may contain predictions, summaries or supporting information rather than measurements recorded for that time."
  ],
  "input_identity_unverified": [
    "File-version check unfinished",
    "The audit has not tied this result to a verified input fingerprint. Check the existing file inventory and hashes, then rerun affected checks if necessary. New observations are not required for this check."
  ],
  "series_type_unknown": [
    "We do not know what kind of value this is",
    "We cannot establish whether this is a market price or another predictor, such as a sentiment score or economic indicator."
  ],
  "no_valid_observations": [
    "No usable numbers with dates remain",
    "The series has no observations that can be used after checking its numbers and dates."
  ],
  "no_window_data": [
    "No usable data fall inside our test dates",
    "We found no usable observations from 1 October 2024 through 30 September 2026, even if data exist outside those dates."
  ],
  "invalid_values": [
    "Some recorded numbers are invalid",
    "Some entries cannot be used as numbers, such as infinity or an unreadable number."
  ],
  "invalid_times": [
    "Some dates or times cannot be read",
    "One or more observations have timestamps the audit could not turn into a usable date and time."
  ],
  "conflicting_duplicates": [
    "The same time has different recorded values",
    "More than one value exists for the same series at the same time, and the conflict needs to be resolved."
  ],
  "source_parse_error": [
    "Some source files could not be fully read",
    "The audit could not read the complete contents of at least one input file, so the result may be incomplete."
  ],
  "aggregation_unverified": [
    "Event-to-series calculation not checked",
    "The audit has not verified how individual events become regular predictor values. Inspect the existing aggregation code, interval boundaries and timestamps before treating this as a request for new data."
  ],
  "score_probability_invalid": [
    "Sentiment scores failed a maths check",
    "The saved scores or probabilities do not meet the scoring rules used by the audit."
  ],
  "grid_alignment_invalid": [
    "Recorded times do not match the stated schedule",
    "The timestamps do not line up with the regular intervals the dataset claims to use."
  ],
  "short_history": [
    "Less than two years of usable history",
    "The first and last valid observations do not span two full calendar years. This check is separate from checks for gaps inside that span."
  ],
  "calendar_unverified": [
    "Market or reporting schedule not checked",
    "The audit has not matched this series to its opening hours, holidays or reporting schedule. Check the existing source and exchange information before deciding whether an empty period is a gap."
  ],
  "coarse_resolution": [
    "Values are recorded less often than every 15 minutes",
    "The original data are hourly, daily or otherwise too far apart. Adding copied or interpolated values would not make them qualify."
  ],
  "cadence_unknown": [
    "Recording interval not established by the audit",
    "Check the existing timestamps and interval labels to establish how often values were originally recorded. This flag does not establish that the data are too coarse."
  ],
  "missing_months": [
    "At least one test month has no price data",
    "One or more months inside our test dates contain no valid prices for this series."
  ],
  "price_definition_unverified": [
    "Financial-field metadata review unfinished",
    "The saved audit combines several questions: price basis, adjustment, units and instrument identity. OHLC, volume or adjusted-close columns may already establish part of the meaning. Preserve those known facts and verify only the remaining details from existing metadata. Bid/ask price basis does not apply to volume or trade counts. This flag does not mean that the files contain no price information."
  ],
  "availability_unverified": [
    "Historical release timing not checked",
    "The audit did not establish when each value first became available or which revision it contains. An observation date alone cannot answer that: a January figure published in March was unavailable for a January forecast. Inspect stored publication, release and collection timestamps first."
  ],
  "collection_completeness_unverified": [
    "Event collection not cross-checked",
    "The audit has not established whether the stored events cover the intended collection. Check existing collection logs and source coverage; the observed events alone cannot reveal every missed event."
  ],
  "completeness_unverified": [
    "Gap check unfinished",
    "The audit could not complete the gap test using a verified schedule and coverage counts. This flag does not establish that observations are missing. Inspect the existing timestamps and schedule first."
  ],
  "hourly_gaps": [
    "Some expected hours have no data",
    "The earlier audit measured at least one empty hour when observations should have existed. That also fails the current 15-minute requirement."
  ],
  "long_gaps": [
    "A gap between observations is longer than 15 minutes",
    "Within the checked market schedule, some consecutive observations are more than 15 minutes apart."
  ],
  "context_gaps": [
    "Some expected reports or predictor values are missing",
    "An observation is missing at a time when the checked reporting schedule says one should exist."
  ],
  "scrape_completeness": [
    "Account scraping not cross-checked",
    "Collected tweets alone cannot show which posts were missed. Check the existing scrape logs, pagination and account coverage. An empty period is not automatically a scrape failure."
  ],
  "causal_processing_unverified": [
    "Signal calculation timing not checked",
    "The audit has not verified from the existing calculation code and logs that a signal uses only information available by its timestamp. This requires checking the processing, not automatically collecting more data."
  ],
  "numeric_observations_check_missing": [
    "The check for usable numbers is missing",
    "The audit has no completed check proving this series contains usable numerical observations."
  ],
  "window_observations_check_missing": [
    "The check for data inside our test dates is missing",
    "The audit has not established whether usable observations exist from 1 October 2024 through 30 September 2026."
  ],
  "value_check_missing": [
    "The check for invalid numbers is missing",
    "The audit has no completed result showing whether the recorded numbers are valid."
  ],
  "timestamp_check_missing": [
    "The check for readable dates and times is missing",
    "The audit has no completed result showing whether observation timestamps can be read."
  ],
  "duplicate_check_missing": [
    "The check for conflicting values at the same time is missing",
    "The audit has not established whether duplicate timestamps contain different values."
  ],
  "source_parse_check_missing": [
    "The check that source files were fully read is missing",
    "The audit has not established whether all input files could be read completely."
  ],
  "sentiment_score_check_missing": [
    "The sentiment score calculation check is missing",
    "The audit has no completed result showing whether saved sentiment scores follow the intended calculation."
  ],
  "grid_alignment_check_missing": [
    "The check that times match the stated schedule is missing",
    "The audit has not established whether timestamps line up with the claimed recording intervals."
  ],
  "history_span_check_missing": [
    "The two-year history check is missing",
    "The audit has not established the first and last valid observation dates, so two years of history cannot be confirmed."
  ],
  "window_months_check_missing": [
    "The check for data in every test month is missing",
    "The audit has not established whether prices exist in every month of our test dates."
  ]
};
