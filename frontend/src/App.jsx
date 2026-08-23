import React, { useEffect, useState } from "react";
import { Box, Text, Heading, Card, CardBody } from "@razorpay/blade/components";

/**
 * Scaffolded shell -- confirms the Blade + FastAPI wiring works end to end.
 * The five real views (confidence scatter, drill-down, budget meter,
 * leak/non-leak split, reproducibility check) are Phase 4 Subagent C's job
 * -- see docs/codex_prompts/04_audit_observability_agent.md.
 */
export default function App() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: "unreachable" }));
  }, []);

  return (
    <Box padding="spacing.7" maxWidth="600px" margin="0 auto">
      <Heading size="large">Parity</Heading>
      <Text marginTop="spacing.3" color="surface.text.gray.subtle">
        Autonomous financial reconciliation investigator — backend status:{" "}
        {health ? health.status : "checking..."}
      </Text>
      <Card marginTop="spacing.6">
        <CardBody>
          <Text>
            TODO (Phase 4, Subagent C): confidence scatter, click-to-explain
            drill-down, live budget meter, leak vs. non-leak split, and the
            reproducibility check replace this placeholder.
          </Text>
        </CardBody>
      </Card>
    </Box>
  );
}
