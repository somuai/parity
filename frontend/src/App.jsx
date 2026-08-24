import React, { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Avatar,
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  Display,
  Heading,
  PopoverInteractiveWrapper,
  ProgressBar,
  Spinner,
  Text,
} from "@razorpay/blade/components";

const numberFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
});

const currencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

const stateStyles = {
  Calm: {
    color: "information",
    dot: "feedback.background.information.intense",
  },
  Joyful: {
    color: "positive",
    dot: "feedback.background.positive.intense",
  },
  Caution: {
    color: "notice",
    dot: "feedback.background.notice.intense",
  },
  Regret: {
    color: "negative",
    dot: "feedback.background.negative.intense",
  },
};

function clamp(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.min(1, Math.max(0, numeric));
}

function asPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  const normalized = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${numberFormatter.format(normalized)}%`;
}

function confidenceValue(record) {
  return clamp(record?.confidence) ?? 0;
}

function emotionalState(record) {
  const band = String(record?.confidence_band ?? "").toLowerCase();
  const status = String(record?.status ?? "").toLowerCase();

  if (status.includes("exception") || band === "low") return "Regret";
  if (band === "medium") return "Caution";
  if (confidenceValue(record) >= 0.95) return "Joyful";
  return "Calm";
}

function budgetColor(used, limit) {
  const ratio = limit > 0 ? used / limit : 0;
  if (ratio >= 0.9) return "negative";
  if (ratio >= 0.75) return "notice";
  return "positive";
}

async function requestJson(path, options, signal) {
  const response = await fetch(path, { ...options, signal });
  if (!response.ok) {
    const message = await response.text();
    let detail = message;
    try {
      detail = JSON.parse(message).detail ?? message;
    } catch {
      // Keep the plain-text server response when it is not JSON.
    }
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

function SectionHeading({ title, description }) {
  return (
    <Box marginBottom="spacing.5">
      <Heading size="large">{title}</Heading>
      <Text marginTop="spacing.2" color="surface.text.gray.muted">
        {description}
      </Text>
    </Box>
  );
}

function MetricCard({ label, value, detail, tone = "neutral" }) {
  return (
    <Card variant="secondary" width={{ base: "100%", m: "48%", l: "23%" }}>
      <CardBody>
        <Badge color={tone} size="small">
          {label}
        </Badge>
        <Display size="small" marginTop="spacing.4">
          {value}
        </Display>
        <Text size="small" marginTop="spacing.2" color="surface.text.gray.muted">
          {detail}
        </Text>
      </CardBody>
    </Card>
  );
}

function SummaryStrip({ summary }) {
  const matches = summary.matches ?? {};
  const exceptions = summary.exceptions ?? {};
  const truthTotal = summary.truth_transactions ?? summary.records_total ?? 0;

  return (
    <Box display="flex" flexWrap="wrap" gap="spacing.5">
      <MetricCard
        label="Match rate"
        value={asPercent(summary.match_rate)}
        detail={`${numberFormatter.format(matches.total ?? 0)} of ${numberFormatter.format(
          truthTotal,
        )} truth transactions matched`}
        tone="positive"
      />
      <MetricCard
        label="Tier 1"
        value={numberFormatter.format(matches.tier1 ?? 0)}
        detail="Deterministic, zero-guess matches"
        tone="information"
      />
      <MetricCard
        label="Tier 2"
        value={numberFormatter.format(matches.tier2 ?? 0)}
        detail="Reasoned, signal-grounded matches"
        tone="primary"
      />
      <MetricCard
        label="Exception book"
        value={numberFormatter.format(exceptions.total ?? 0)}
        detail="Specific reasons, retained for review"
        tone="notice"
      />
    </Box>
  );
}

function RazorpayTestModeFeed({ feed, loading, error, onRefresh }) {
  const records = Array.isArray(feed?.records) ? feed.records : [];
  const payments = Array.isArray(feed?.recent_payment_activity) ? feed.recent_payment_activity : [];
  const rows = Number(feed?.validated_rows ?? 0);
  const period = feed ? `${feed.year}-${String(feed.month).padStart(2, "0")}` : "current month";

  return (
    <Card variant="secondary">
      <CardBody>
        <Box display="flex" flexWrap="wrap" justifyContent="space-between" gap="spacing.5">
          <Box flex="1 1 auto">
            <Box display="flex" flexWrap="wrap" alignItems="center" gap="spacing.3">
              <Heading size="medium">Razorpay Test Mode feed</Heading>
              <Badge color="information" size="small">
                Live, unlabeled source
              </Badge>
            </Box>
            <Text marginTop="spacing.2" size="small" color="surface.text.gray.muted">
              Authenticated Settlement Recon data from this merchant’s Test Mode account. It is
              shown separately and never changes the frozen bank-versus-ledger match rate,
              precision, recall, or exception totals.
            </Text>
          </Box>
          <Button onClick={onRefresh} isLoading={loading} isDisabled={loading}>
            Refresh feed
          </Button>
        </Box>

        {error ? (
          <Alert
            marginTop="spacing.6"
            title="Razorpay Test Mode feed unavailable"
            description={error}
            color="negative"
            isDismissible={false}
            isFullWidth
          />
        ) : null}

        {loading && !feed ? (
          <Box display="flex" justifyContent="center" paddingY="spacing.7">
            <Spinner accessibilityLabel="Loading Razorpay Test Mode feed" label="Loading live feed" />
          </Box>
        ) : null}

        {feed && !loading ? (
          <Box marginTop="spacing.6">
            <Box display="flex" flexWrap="wrap" gap="spacing.5">
              <Box
                width={{ base: "100%", m: "31%" }}
                padding="spacing.5"
                borderRadius="medium"
                backgroundColor="feedback.background.information.subtle"
              >
                <Text size="xsmall" color="surface.text.gray.muted">
                  Validated settlement rows
                </Text>
                <Display size="small" marginTop="spacing.2" color="feedback.text.information.intense">
                  {numberFormatter.format(rows)}
                </Display>
                <Text marginTop="spacing.2" size="small">
                  {period}
                </Text>
              </Box>
              <Box width={{ base: "100%", m: "65%" }} padding="spacing.5" borderRadius="medium" backgroundColor="surface.background.gray.subtle">
                <Text size="small" weight="semibold">
                  Scope boundary
                </Text>
                <Text marginTop="spacing.2" size="small" color="surface.text.gray.muted">
                  {rows
                    ? `Showing a safe sample of up to ${numberFormatter.format(feed.sample_limit ?? records.length)} normalized rows.`
                    : feed.empty_message}
                </Text>
              </Box>
            </Box>

            {records.length ? (
              <Box marginTop="spacing.6" display="flex" flexDirection="column" gap="spacing.3">
                {records.map((record) => (
                  <Box
                    key={record.id}
                    display="flex"
                    flexWrap="wrap"
                    justifyContent="space-between"
                    gap="spacing.3"
                    padding="spacing.4"
                    borderRadius="medium"
                    backgroundColor="surface.background.gray.subtle"
                  >
                    <Box>
                      <Text size="small" weight="semibold" wordBreak="break-all">
                        {record.reference || record.id}
                      </Text>
                      <Text marginTop="spacing.1" size="xsmall" color="surface.text.gray.muted">
                        {`${record.type} · ${record.txn_date} · ${record.description || "No description"}`}
                      </Text>
                    </Box>
                    <Text size="small" weight="semibold">
                      {currencyFormatter.format(Number(record.amount_inr ?? 0))}
                    </Text>
                  </Box>
                ))}
              </Box>
            ) : null}
            <Box marginTop="spacing.6">
              <Text size="small" weight="semibold">Recent Test Mode payment activity</Text>
              <Text marginTop="spacing.1" size="xsmall" color="surface.text.gray.muted">
                Captured payment activity proves the authenticated Test Mode connection; it is not a settlement row and is never scored as reconciliation evidence.
              </Text>
              {payments.length ? payments.map((payment) => (
                <Box key={payment.id} marginTop="spacing.3" display="flex" justifyContent="space-between" gap="spacing.3" padding="spacing.4" borderRadius="medium" backgroundColor="feedback.background.positive.subtle">
                  <Text size="small" wordBreak="break-all">{payment.id} · {payment.status}</Text>
                  <Text size="small" weight="semibold">{currencyFormatter.format(Number(payment.amount_inr ?? 0))}</Text>
                </Box>
              )) : <Text marginTop="spacing.3" size="small" color="surface.text.gray.muted">No recent Test Mode payment activity was returned.</Text>}
            </Box>
          </Box>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ConfidenceScatter({ records, selectedId, onSelect }) {
  const counts = useMemo(
    () =>
      records.reduce(
        (totals, record) => {
          totals[emotionalState(record)] += 1;
          return totals;
        },
        { Calm: 0, Joyful: 0, Caution: 0, Regret: 0 },
      ),
    [records],
  );

  return (
    <Card variant="secondary">
      <CardBody>
        <Box display="flex" flexWrap="wrap" gap="spacing.3" marginBottom="spacing.5">
          {Object.entries(counts).map(([state, count]) => (
            <Badge key={state} color={stateStyles[state].color} size="small">
              {`${state} · ${count}`}
            </Badge>
          ))}
        </Box>

        <Box
          display="flex"
          flexWrap="wrap"
          gap="spacing.3"
          padding="spacing.5"
          backgroundColor="surface.background.gray.subtle"
          borderRadius="large"
        >
          {records.map((record) => {
            const state = emotionalState(record);
            const isSelected = record.id === selectedId;
            return (
              <PopoverInteractiveWrapper
                key={record.id}
                accessibilityLabel={`Explain ${record.id}: ${state}, confidence ${asPercent(
                  record.confidence,
                )}`}
                onClick={() => onSelect(record.id)}
                width="spacing.4"
                height="spacing.4"
                padding="spacing.0"
                borderRadius="round"
                backgroundColor={stateStyles[state].dot}
                borderWidth={isSelected ? "thick" : "none"}
                borderColor="interactive.border.primary.default"
                cursor="pointer"
                testID={`record-dot-${record.id}`}
              />
            );
          })}
        </Box>
      </CardBody>
    </Card>
  );
}

function signalBars(record) {
  const scores = record?.signal_scores ?? {};
  const tier = String(record?.tier ?? "").toLowerCase();

  if (tier.includes("1")) {
    return [
      ["Amount within Tier 1 tolerance", 1],
      ["Date within settlement window", 1],
      ["Reference exact", 1],
    ];
  }

  const semanticCandidates = [
    scores.semantic_evidence,
    scores.semantic_similarity,
    scores.embedding_similarity,
    scores.reference_similarity,
  ]
    .map(clamp)
    .filter((value) => value !== null);

  const amountDelta = Number(scores.amount_delta);
  const timingDelta = Number(scores.timing_delta);

  return [
    ["Amount fit (1 − normalized delta)", Number.isFinite(amountDelta) ? clamp(1 - amountDelta) : null],
    ["Timing fit (1 − normalized delta)", Number.isFinite(timingDelta) ? clamp(1 - timingDelta) : null],
    ["Semantic evidence", semanticCandidates.length ? Math.max(...semanticCandidates) : null],
  ];
}

function rawSignalValue(value) {
  if (typeof value === "number") return numberFormatter.format(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value === null || value === undefined || value === "") return "not provided";
  return String(value);
}

function RecordDrillDown({ record, loading, error }) {
  if (loading) {
    return (
      <Card variant="secondary">
        <CardBody>
          <Box display="flex" justifyContent="center" paddingY="spacing.9">
            <Spinner accessibilityLabel="Loading record explanation" label="Loading explanation" />
          </Box>
        </CardBody>
      </Card>
    );
  }

  if (error) {
    return (
      <Alert
        title="Explanation unavailable"
        description={error}
        color="negative"
        isDismissible={false}
        isFullWidth
      />
    );
  }

  if (!record) {
    return (
      <Card variant="secondary">
        <CardBody>
          <Text color="surface.text.gray.muted">Select a record dot to inspect its evidence.</Text>
        </CardBody>
      </Card>
    );
  }

  const state = emotionalState(record);
  const rawSignals = Object.entries(record.signal_scores ?? {});

  return (
    <Card variant="secondary">
      <CardBody>
        <Box display="flex" flexWrap="wrap" justifyContent="space-between" gap="spacing.4">
          <Box>
            <Heading size="medium" wordBreak="break-all">
              {record.id}
            </Heading>
            <Text size="small" marginTop="spacing.2" color="surface.text.gray.muted">
              {`${record.source ?? "Unknown source"} · ${record.tier ?? "Unknown tier"} · ${
                record.txn_date ?? "Date unavailable"
              }`}
            </Text>
          </Box>
          <Box display="flex" flexWrap="wrap" gap="spacing.3" alignItems="flex-start">
            <Badge color={stateStyles[state].color}>{state}</Badge>
            <Badge color="neutral">{asPercent(record.confidence)}</Badge>
            {record.reason_code ? <Badge color="negative">{record.reason_code}</Badge> : null}
          </Box>
        </Box>

        <Box display="flex" flexWrap="wrap" gap="spacing.5" marginTop="spacing.6">
          <Box width={{ base: "100%", m: "31%" }}>
            <Text size="xsmall" color="surface.text.gray.muted">
              Amount
            </Text>
            <Text marginTop="spacing.2" weight="semibold">
              {currencyFormatter.format(Number(record.amount_inr ?? 0))}
            </Text>
          </Box>
          <Box width={{ base: "100%", m: "31%" }}>
            <Text size="xsmall" color="surface.text.gray.muted">
              Reference
            </Text>
            <Text marginTop="spacing.2" weight="semibold" wordBreak="break-all">
              {record.reference || "Not provided"}
            </Text>
          </Box>
          <Box width={{ base: "100%", m: "31%" }}>
            <Text size="xsmall" color="surface.text.gray.muted">
              Counterparty
            </Text>
            <Text marginTop="spacing.2" weight="semibold">
              {record.counterparty || "Not provided"}
            </Text>
          </Box>
        </Box>

        <Box marginTop="spacing.7" display="flex" flexDirection="column" gap="spacing.5">
          {signalBars(record).map(([label, value]) =>
            value === null ? (
              <Box key={label}>
                <Text size="small" color="surface.text.gray.muted">
                  {`${label}: not available`}
                </Text>
              </Box>
            ) : (
              <ProgressBar
                key={label}
                label={label}
                accessibilityLabel={`${label}: ${asPercent(value)}`}
                value={value * 100}
                min={0}
                max={100}
                color={value >= 0.9 ? "positive" : value >= 0.6 ? "notice" : "negative"}
                showPercentage
                size="medium"
              />
            ),
          )}
        </Box>

        <Box
          marginTop="spacing.7"
          padding="spacing.5"
          borderRadius="medium"
          backgroundColor="feedback.background.information.subtle"
        >
          <Text size="small" weight="semibold" color="feedback.text.information.intense">
            Grounded rationale
          </Text>
          <Text marginTop="spacing.3">{record.rationale || "No rationale returned."}</Text>
        </Box>

        <Box marginTop="spacing.7">
          <Text size="small" weight="semibold">
            Raw grounded signals
          </Text>
          {rawSignals.length ? (
            <Box display="flex" flexWrap="wrap" gap="spacing.3" marginTop="spacing.3">
              {rawSignals.map(([key, value]) => (
                <Box
                  key={key}
                  paddingX="spacing.3"
                  paddingY="spacing.2"
                  borderRadius="small"
                  backgroundColor="feedback.background.neutral.subtle"
                >
                  <Text size="xsmall">{`${key}=${rawSignalValue(value)}`}</Text>
                </Box>
              ))}
            </Box>
          ) : (
            <Text marginTop="spacing.3" size="small" color="surface.text.gray.muted">
              No raw signal payload was supplied for this record.
            </Text>
          )}
        </Box>
      </CardBody>
    </Card>
  );
}

function BudgetMeter({ budget }) {
  const calls = budget?.calls ?? {};
  const tokens = budget?.tokens ?? {};
  const items = [
    ["LLM calls", Number(calls.used ?? 0), Number(calls.limit ?? 0)],
    ["Tokens", Number(tokens.used ?? 0), Number(tokens.limit ?? 0)],
  ];

  return (
    <Card variant="secondary" width={{ base: "100%", l: "48%" }}>
      <CardBody>
        <Heading size="medium">Live budget meter</Heading>
        <Text marginTop="spacing.2" size="small" color="surface.text.gray.muted">
          The adjudicator checks both ceilings before every model call.
        </Text>
        <Box marginTop="spacing.6" display="flex" flexDirection="column" gap="spacing.6">
          {items.map(([label, used, limit]) => (
            <ProgressBar
              key={label}
              label={`${label}: ${numberFormatter.format(used)} of ${numberFormatter.format(limit)}`}
              accessibilityLabel={`${label} budget usage`}
              value={used}
              min={0}
              max={Math.max(limit, 1)}
              color={budgetColor(used, limit)}
              showPercentage
              size="medium"
            />
          ))}
        </Box>
      </CardBody>
    </Card>
  );
}

function RiskSplit({ exceptions }) {
  const leakage = exceptions?.leakage ?? {};
  const nonLeakage = exceptions?.non_leakage ?? {};

  return (
    <Card variant="secondary" width={{ base: "100%", l: "48%" }}>
      <CardBody>
        <Heading size="medium">Exception value split</Heading>
        <Text marginTop="spacing.2" size="small" color="surface.text.gray.muted">
          Values come directly from the server-side exception book classification.
        </Text>
        <Box display="flex" flexWrap="wrap" gap="spacing.5" marginTop="spacing.6">
          <Box
            width={{ base: "100%", m: "48%" }}
            padding="spacing.5"
            borderRadius="medium"
            backgroundColor="feedback.background.negative.subtle"
          >
            <Badge color="negative" size="small">
              Real leakage
            </Badge>
            <Display size="small" marginTop="spacing.4" color="feedback.text.negative.intense">
              {currencyFormatter.format(Number(leakage.total_amount_at_risk_inr ?? 0))}
            </Display>
            <Text marginTop="spacing.2" size="small">
              {`${numberFormatter.format(leakage.count ?? 0)} flagged entries`}
            </Text>
          </Box>

          <Box
            width={{ base: "100%", m: "48%" }}
            padding="spacing.5"
            borderRadius="medium"
            backgroundColor="feedback.background.notice.subtle"
          >
            <Badge color="notice" size="small">
              Human review
            </Badge>
            <Display size="small" marginTop="spacing.4" color="feedback.text.notice.intense">
              {currencyFormatter.format(Number(nonLeakage.total_amount_at_risk_inr ?? 0))}
            </Display>
            <Text marginTop="spacing.2" size="small">
              {`${numberFormatter.format(nonLeakage.count ?? 0)} non-leakage entries`}
            </Text>
          </Box>
        </Box>
      </CardBody>
    </Card>
  );
}

function ReproducibilityCheck({ result, isRunning, error, onRerun }) {
  return (
    <Card variant="secondary">
      <CardBody>
        <Box display="flex" flexWrap="wrap" justifyContent="space-between" gap="spacing.5">
          <Box flex="1 1 auto">
            <Heading size="medium">Reproducibility check</Heading>
            <Text marginTop="spacing.2" size="small" color="surface.text.gray.muted">
              Replay the frozen batch twice and compare complete per-record outcome digests.
            </Text>
          </Box>
          <Button onClick={onRerun} isLoading={isRunning} isDisabled={isRunning}>
            Re-run held-out batch
          </Button>
        </Box>

        {error ? (
          <Alert
            marginTop="spacing.6"
            title="Re-run failed loudly"
            description={error}
            color="negative"
            isDismissible={false}
            isFullWidth
          />
        ) : null}

        {result ? (
          <Box display="flex" flexWrap="wrap" gap="spacing.5" marginTop="spacing.6">
            <Box
              width={{ base: "100%", m: "31%" }}
              padding="spacing.5"
              borderRadius="medium"
              backgroundColor="surface.background.gray.subtle"
            >
              <Text size="small" color="surface.text.gray.muted">
                Previous run
              </Text>
              <Heading marginTop="spacing.3">{asPercent(result.previous?.match_rate)}</Heading>
              <Text marginTop="spacing.2" size="xsmall" color="surface.text.gray.muted">
                {result.previous?.run_id ?? "No prior run"}
              </Text>
            </Box>
            <Box
              width={{ base: "100%", m: "31%" }}
              padding="spacing.5"
              borderRadius="medium"
              backgroundColor="surface.background.gray.subtle"
            >
              <Text size="small" color="surface.text.gray.muted">
                Current run
              </Text>
              <Heading marginTop="spacing.3">{asPercent(result.current?.match_rate)}</Heading>
              <Text marginTop="spacing.2" size="xsmall" color="surface.text.gray.muted">
                {result.current?.run_id ?? "Run ID unavailable"}
              </Text>
            </Box>
            <Box
              width={{ base: "100%", m: "31%" }}
              padding="spacing.5"
              borderRadius="medium"
              backgroundColor={
                result.reproducible
                  ? "feedback.background.positive.subtle"
                  : "feedback.background.negative.subtle"
              }
            >
              <Badge color={result.reproducible ? "positive" : "negative"}>
                {result.reproducible ? "Pass" : "Fail"}
              </Badge>
              <Text marginTop="spacing.3" size="small">
                {`Match-rate delta: ${asPercent(result.match_rate_delta)}`}
              </Text>
            </Box>
          </Box>
        ) : null}
      </CardBody>
    </Card>
  );
}

export default function App() {
  const [summary, setSummary] = useState(null);
  const [records, setRecords] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [rerunResult, setRerunResult] = useState(null);
  const [rerunLoading, setRerunLoading] = useState(false);
  const [rerunError, setRerunError] = useState("");
  const [razorpayFeed, setRazorpayFeed] = useState(null);
  const [razorpayLoading, setRazorpayLoading] = useState(false);
  const [razorpayError, setRazorpayError] = useState("");

  async function loadDashboard() {
    setLoading(true);
    setLoadError("");
    try {
      const [summaryPayload, recordsPayload] = await Promise.all([
        requestJson("/api/summary"),
        requestJson("/api/records"),
      ]);
      const nextRecords = Array.isArray(recordsPayload)
        ? recordsPayload
        : Array.isArray(recordsPayload.records)
          ? recordsPayload.records
          : [];
      setSummary(summaryPayload);
      setRecords(nextRecords);
      setSelectedId((current) => current ?? nextRecords[0]?.id ?? null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Unable to load dashboard data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDashboard();
  }, []);

  async function loadRazorpayFeed(signal) {
    setRazorpayLoading(true);
    setRazorpayError("");
    try {
      const payload = await requestJson("/api/razorpay/recon", undefined, signal);
      setRazorpayFeed(payload);
    } catch (error) {
      if (error.name !== "AbortError") {
        setRazorpayError(
          error instanceof Error ? error.message : "Unable to load the Razorpay Test Mode feed.",
        );
      }
    } finally {
      if (!signal?.aborted) setRazorpayLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadRazorpayFeed(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelectedRecord(null);
      return undefined;
    }

    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError("");
    requestJson(`/api/records/${encodeURIComponent(selectedId)}`, undefined, controller.signal)
      .then(setSelectedRecord)
      .catch((error) => {
        if (error.name !== "AbortError") {
          setDetailError(error instanceof Error ? error.message : "Unable to load this record.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });

    return () => controller.abort();
  }, [selectedId]);

  async function handleRerun() {
    setRerunLoading(true);
    setRerunError("");
    setRerunResult(null);
    try {
      await requestJson("/api/rerun", { method: "POST" });
      const result = await requestJson("/api/rerun", { method: "POST" });
      setRerunResult(result);
      await loadDashboard();
    } catch (error) {
      setRerunError(error instanceof Error ? error.message : "The held-out re-run failed.");
    } finally {
      setRerunLoading(false);
    }
  }

  if (loading && !summary) {
    return (
      <Box minHeight="100vh" display="flex" alignItems="center" justifyContent="center">
        <Spinner
          size="large"
          accessibilityLabel="Loading Parity audit dashboard"
          label="Loading the held-out audit run"
          labelPosition="bottom"
        />
      </Box>
    );
  }

  if (loadError && !summary) {
    return (
      <Box minHeight="100vh" padding={{ base: "spacing.5", m: "spacing.8" }}>
        <Alert
          title="Parity could not load the audit run"
          description={loadError}
          color="negative"
          isDismissible={false}
          isFullWidth
          actions={{ primary: { text: "Try again", onClick: loadDashboard } }}
        />
      </Box>
    );
  }

  return (
    <Box
      as="main"
      minHeight="100vh"
      padding={{ base: "spacing.5", m: "spacing.8", l: "spacing.9" }}
      backgroundColor="surface.background.gray.subtle"
    >
      <Box
        as="header"
        padding={{ base: "spacing.6", m: "spacing.8" }}
        borderRadius="large"
        backgroundColor="surface.background.gray.intense"
        elevation="lowRaised"
      >
        <Box display="flex" alignItems="center" gap="spacing.5">
          <Avatar
            src="/brand/parity-logo-a1.png"
            alt="Parity ledger seal"
            name="Parity"
            size="xlarge"
            variant="square"
          />
          <Box>
            <Badge color="primary" emphasis="subtle">
              Frozen held-out audit
            </Badge>
            <Display as="h1" size="medium" marginTop="spacing.4">
              Parity
            </Display>
          </Box>
        </Box>
        <Text marginTop="spacing.4" color="surface.text.gray.subtle">
          A restrained financial-reconciliation investigator that finds evidence, enforces
          budgets, and flags exceptions without acting on merchant funds.
        </Text>
        <Box display="flex" flexWrap="wrap" gap="spacing.3" marginTop="spacing.5">
          <Badge color="positive">{`Precision ${asPercent(summary.precision)}`}</Badge>
          <Badge color="information">{`Recall ${asPercent(summary.recall)}`}</Badge>
          <Badge color="neutral">{summary.run_id ?? "Run ID unavailable"}</Badge>
        </Box>
      </Box>

      <Box marginTop="spacing.7">
        <SummaryStrip summary={summary} />
      </Box>

      <Box as="section" marginTop="spacing.9">
        <SectionHeading
          title="Live Razorpay connection"
          description="A real read-only Test Mode integration, shown separately from the frozen evaluation."
        />
        <RazorpayTestModeFeed
          feed={razorpayFeed}
          loading={razorpayLoading}
          error={razorpayError}
          onRefresh={() => loadRazorpayFeed()}
        />
      </Box>

      <Box as="section" marginTop="spacing.9">
        <SectionHeading
          title="Confidence scatter"
          description="Every record is selectable. Blade’s Calm, Joyful, Caution, and Regret feedback states map directly to reconciliation confidence."
        />
        <ConfidenceScatter records={records} selectedId={selectedId} onSelect={setSelectedId} />
      </Box>

      <Box as="section" marginTop="spacing.9">
        <SectionHeading
          title="Click to explain"
          description="The selected record’s normalized evidence is shown alongside every raw signal and its grounded rationale."
        />
        <RecordDrillDown
          record={selectedRecord}
          loading={detailLoading}
          error={detailError}
        />
      </Box>

      <Box as="section" marginTop="spacing.9">
        <SectionHeading
          title="Cost and exception exposure"
          description="Budget use and financial exposure stay separate, server-owned, and auditable."
        />
        <Box display="flex" flexWrap="wrap" gap="spacing.5">
          <BudgetMeter budget={summary.budget} />
          <RiskSplit exceptions={summary.exceptions} />
        </Box>
      </Box>

      <Box as="section" marginTop="spacing.9" marginBottom="spacing.9">
        <SectionHeading
          title="Prove it again"
          description="A fresh run must agree with the prior frozen-set result and respect the same hard budgets."
        />
        <ReproducibilityCheck
          result={rerunResult}
          isRunning={rerunLoading}
          error={rerunError}
          onRerun={handleRerun}
        />
      </Box>
    </Box>
  );
}
