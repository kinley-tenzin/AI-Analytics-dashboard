import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ANSWERS } from "../test/fixtures";
import { json, mockBackend, renderApp, USERS } from "../test/render";

function askCalls(fetchMock: ReturnType<typeof mockBackend>) {
  return fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/v1/ask/"));
}

function answerFor(body: string) {
  const q = (JSON.parse(body) as { question: string }).question.toLowerCase();
  if (q.includes("overdue")) return json(200, ANSWERS.overdue);
  if (q.includes("department")) return json(200, ANSWERS.departments);
  return json(200, ANSWERS.clarify);
}

function backend(user = USERS.executive!, ask?: () => Response) {
  const fetchMock = mockBackend({ user, routes: {} });
  const base = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).startsWith("/api/v1/ask/")) return ask ? ask() : answerFor(String(init?.body));
    return base(input, init);
  });
  return fetchMock;
}

async function type(question: string) {
  const box = await screen.findByLabelText("Your question");
  await userEvent.type(box, `${question}{Enter}`);
}

describe("Ask AI", () => {
  it("sends the question to the assistant API with the CSRF token and shows the answer", async () => {
    document.cookie = "csrftoken=tok789";
    const fetchMock = backend();
    renderApp("/ask");

    await type("How much is overdue?");

    expect(await screen.findByText(/receivables BTN 149,700.00/)).toBeInTheDocument();
    const [, init] = askCalls(fetchMock)[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ question: "How much is overdue?" });
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok789");
    expect(screen.getByText("Answer from warehouse data")).toBeInTheDocument();
    expect(screen.getByText("Deterministic rules, no language model")).toBeInTheDocument();
  });

  it("shows the KPI, date, freshness and a link to the related dashboard", async () => {
    backend();
    renderApp("/ask");

    await type("How much is overdue?");

    const answer = await screen.findByRole("article", { name: "Assistant answer" });
    expect(within(answer).getByText(/Overdue balances · X/)).toBeInTheDocument();
    expect(within(answer).getByText("As of 25 Oct 2026")).toBeInTheDocument();
    expect(within(answer).getByText(/Refreshed 4 h ago/)).toBeInTheDocument();
    expect(within(answer).getByRole("link", { name: /Explore in Accounts Analytics/ })).toHaveAttribute(
      "href",
      "/app/accounts",
    );
  });

  it("charts a breakdown and offers the figures as a table", async () => {
    backend();
    renderApp("/ask");

    await type("How many employees work in each department?");

    const answer = await screen.findByRole("article", { name: "Assistant answer" });
    const chart = within(answer).getByRole("figure", { name: /Active headcount/ });
    expect([...chart.querySelectorAll(".bars__label")].map((e) => e.textContent)).toEqual([
      "Finance & Accounts",
      "Sales",
      "Operations",
    ]);
    await userEvent.click(within(answer).getByText(/Show the figures as a table/));
    expect(within(answer).getAllByRole("table").at(-1)).toHaveTextContent("Sales5");
  });

  it("offers clarification options as one-click questions", async () => {
    const fetchMock = backend();
    renderApp("/ask");

    await type("what is the weather");
    await userEvent.click(await screen.findByRole("button", { name: "How much is overdue?" }));

    expect(await screen.findByText(/receivables BTN 149,700.00/)).toBeInTheDocument();
    expect(askCalls(fetchMock)).toHaveLength(2);
  });

  it("asks a suggested question with one click", async () => {
    const fetchMock = backend();
    renderApp("/ask");

    const suggestions = await screen.findByRole("complementary", { name: /Suggestions/ });
    await userEvent.click(within(suggestions).getByRole("button", { name: /How much is overdue\?/ }));

    expect(await screen.findByText(/receivables BTN 149,700.00/)).toBeInTheDocument();
    expect(JSON.parse(String((askCalls(fetchMock)[0]![1] as RequestInit).body)).question).toBe("How much is overdue?");
  });

  it("suggests only questions of the user's modules", async () => {
    backend(USERS.hr!);
    renderApp("/ask");

    const suggestions = await screen.findByRole("complementary", { name: /Suggestions/ });
    expect(within(suggestions).queryByText("How much is overdue?")).not.toBeInTheDocument();
    expect(within(suggestions).getByText("How many active employees are there?")).toBeInTheDocument();
  });

  it("shows a refusal as the assistant's answer, without data", async () => {
    backend(USERS.hr!, () => json(200, ANSWERS.forbidden));
    renderApp("/ask");

    await type("How much is overdue?");

    expect(await screen.findByText("Not authorised")).toBeInTheDocument();
    expect(screen.getByText("Your role does not include Accounts data.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a loading state and blocks a second question until the answer arrives", async () => {
    let release: (r: Response) => void = () => undefined;
    const fetchMock = backend(USERS.executive!);
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).startsWith("/api/v1/ask/") ? new Promise<Response>((r) => (release = r)) : base(input, init),
    );
    renderApp("/ask");

    await type("How much is overdue?");

    expect(await screen.findByText("Looking up approved KPIs…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await act(async () => release(json(200, ANSWERS.overdue)));
    expect(await screen.findByText(/receivables BTN 149,700.00/)).toBeInTheDocument();
    expect(screen.queryByText("Looking up approved KPIs…")).not.toBeInTheDocument();
  });

  it("explains a server failure and lets the user ask again", async () => {
    let fail = true;
    const fetchMock = backend(USERS.executive!, () =>
      fail ? json(503, { status: "error", message: "The warehouse is not reachable right now." }) : json(200, ANSWERS.overdue),
    );
    renderApp("/ask");

    await type("How much is overdue?");
    expect(await screen.findByRole("alert")).toHaveTextContent("The warehouse is not reachable right now.");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: /Ask again/ }));

    expect(await screen.findByText(/receivables BTN 149,700.00/)).toBeInTheDocument();
    expect(askCalls(fetchMock)).toHaveLength(2);
  });

  it("keeps the conversation while moving between pages and can clear it", async () => {
    backend();
    const { router } = renderApp("/ask");
    await type("How much is overdue?");
    await screen.findByText(/receivables BTN 149,700.00/);

    await act(async () => {
      await router.navigate("/reports");
    });
    await act(async () => {
      await router.navigate("/ask");
    });

    expect(await screen.findByText(/receivables BTN 149,700.00/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Clear conversation/ }));
    await waitFor(() => expect(screen.queryByText(/receivables BTN 149,700.00/)).not.toBeInTheDocument());
  });

  it("does not send empty questions and limits the length", async () => {
    const fetchMock = backend();
    renderApp("/ask");

    const box = await screen.findByLabelText("Your question");
    await userEvent.type(box, "   {Enter}");
    expect(askCalls(fetchMock)).toHaveLength(0);
    expect(box).toHaveAttribute("maxLength", "500");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("says honestly that no language model is used", async () => {
    backend();
    renderApp("/ask");

    expect(await screen.findByText(/deterministic rules \(no language model\)/)).toBeInTheDocument();
  });
});
