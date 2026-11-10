/* Plain-English check descriptions; no dataset observations. */
const KuinaReasons = {
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
    "We cannot trace the exact file version that was checked",
    "The audit lacks a verified file fingerprint, so it cannot prove which version of the source file was checked."
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
    "Individual events have no verified time-series recipe",
    "Tweets, trades or other events need a checked rule for turning them into regular values, such as one score per 15 minutes."
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
    "We do not know when observations should exist",
    "We lack a checked schedule of market opening hours, holidays or reporting dates, so we cannot reliably distinguish normal closures from missing data."
  ],
  "coarse_resolution": [
    "Values are recorded less often than every 15 minutes",
    "The original data are hourly, daily or otherwise too far apart. Adding copied or interpolated values would not make them qualify."
  ],
  "cadence_unknown": [
    "We cannot confirm how often values were recorded",
    "The original recording interval has not been established, so we cannot prove the series meets the 15-minute requirement."
  ],
  "missing_months": [
    "At least one test month has no price data",
    "One or more months inside our test dates contain no valid prices for this series."
  ],
  "price_definition_unverified": [
    "We do not know exactly what the price represents",
    "We cannot confirm whether it is a buyer bid, seller ask or completed trade, how candles were built, or whether stock prices account for splits and dividends."
  ],
  "availability_unverified": [
    "We cannot confirm what was known at the time",
    "We do not know when a value first became available or whether it was changed later. For example, a January figure published in March was not available for a January forecast."
  ],
  "collection_completeness_unverified": [
    "We cannot confirm all events were collected",
    "The available records do not prove that all expected events were captured; an empty interval may be inactivity or a collection failure."
  ],
  "completeness_unverified": [
    "We cannot confirm the data are complete",
    "We lack enough evidence to tell whether expected observations are missing."
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
    "We cannot confirm every relevant tweet was collected",
    "For an account, we cannot prove the scraper captured all relevant posts. A blank period might mean no posts or a failed scrape."
  ],
  "causal_processing_unverified": [
    "We cannot confirm the signal uses only earlier information",
    "The processing record does not prove that each historical signal was made using only information available by that time. Later information could make a forecast test look better than it really is."
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
