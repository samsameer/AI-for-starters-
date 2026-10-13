import { choice, noul, score, TypeSafeClient } from "@typesafe-ai/sdk";

const client = new TypeSafeClient();

const questions = {
  team: choice("Which team should handle this ticket?", {
    billing: "Payments, invoices, and refunds",
    technical: "Bugs, outages, and integrations",
    other: "None of the above",
  }),
  refund: noul("Does the customer explicitly request a refund?"),
  urgency: score("How urgent is this ticket?", ["Can wait", "Today", "Right now"]),
};

type Action =
  | { kind: "queue"; team: "billing" | "technical" }
  | { kind: "page"; team: "billing" | "technical" }
  | { kind: "human_review"; reason: string };

export async function triage(ticket: string): Promise<Action> {
  const { answers } = await client.systemOne({ state: { ticket }, questions });

  const team = answers.team.choice;
  const p = answers.team.probabilities[team];

  if (team === "other" || p < 0.9) {
    return { kind: "human_review", reason: `team=${team} p=${p.toFixed(2)}` };
  }
  if (answers.urgency.score >= 1.5) {
    return { kind: "page", team };
  }
  return { kind: "queue", team };
}

const ticket = process.argv[2] ?? "I was charged twice. Please refund the extra payment.";
console.log(await triage(ticket));
