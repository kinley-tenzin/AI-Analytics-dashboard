# Usability evaluation: protocol, materials and status (Milestone 8, Task 7)

**Status:**
- **Protocol ready.**
- **Automated task walkthrough done.** It proves each task can be completed and shows correct data; results are in §5.
- **No participant sessions have been run yet**, so there are no participant results. Nothing in this document is a user rating. The results table in §4 is empty until the team runs the sessions.

## 1. Method

| Item | Choice | Why |
|---|---|---|
| Design | Task-based usability test with think-aloud, then a short questionnaire | Shows *where* users struggle, not only *whether* they finish |
| Participants | 5 to 8 people; ideally DrukSmart staff in HR, Accounts and management roles, otherwise CST students briefed on the roles | About 5 users find most major usability problems in formative tests |
| Setting | One participant at a time, on the reference machine with the local platform. A team member moderates and another takes notes | Same data and environment for everyone |
| Data | Sandbox/synthetic data only. **No real DrukSmart data** | Privacy; the prototype is not connected to DrukSmart ERPs |
| Accounts | Demo users with the role matching the task (`demo_hr`, `demo_accounts`, `demo_executive`) | Tests the role-specific views |
| Measures per task | Completed (yes / with help / no), time in seconds, errors, number of hints, a quote | Effectiveness, efficiency, problems |
| After all tasks | System Usability Scale (SUS, 10 items, 1 to 5), plus 3 open questions (below) | Standard, comparable satisfaction score |
| Ethics | Verbal consent; participants may stop at any time; no recording of faces; notes are anonymised (P1, P2, …) | CST project ethics |

Moderator script (read aloud):

> "We are testing the system, not you. Please think aloud while you work. I can't help with the
> tasks, but you can stop at any time."

Give the task card, then start the timer when the participant starts reading.

## 2. Tasks

Each card states the goal in business terms. It never names the UI element to use.

| # | Task card (read to participant) | Role / tool | Success criterion |
|---|---|---|---|
| T1 | "How many employees are currently active?" | HR Viewer, Superset | Reads the Active headcount card; the number matches the dashboard |
| T2 | "How many active employees work in Sales?" | HR Viewer, Superset | Applies the Department filter (Sales) and reads the updated card |
| T3 | "How much do customers owe us right now?" | Accounts Viewer, Superset | Reads Outstanding receivables, **with the as-of date** |
| T4 | "Which overdue categories hold the most money?" | Accounts Viewer, Superset | Names the largest overdue ageing bucket from the ageing chart |
| T5 | "Send the open balances per branch to a colleague as a spreadsheet." | Accounts Viewer, Superset | Downloads the CSV of the branch table |
| T6 | "Ask the assistant how much is overdue, and explain the answer in your own words." | Executive, Django assistant | Reports both ledgers, the as-of date and currency, and says it came from warehouse data |
| T7 (optional) | As HR Viewer: "Ask the assistant for the outstanding receivables." | HR Viewer, Django assistant | Understands the "not authorised" message |

## 3. Questionnaire (after the tasks)

**SUS.** Score 1 (strongly disagree) to 5 (strongly agree):
1. I think that I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think that I would need the support of a technical person to be able to use this system.
5. I found the various functions in this system were well integrated.
6. I thought there was too much inconsistency in this system.
7. I would imagine that most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot of things before I could get going with this system.

SUS score = 2.5 × (Σ(odd items − 1) + Σ(5 − even items)), giving a range of 0 to 100. About 68 is commonly cited as average.

**Open questions:**
- a) Which KPI or view was most useful for your work, and why?
- b) What was confusing (wording, numbers, dates, filters)?
- c) Would you trust the assistant's answers? What would increase your trust?

## 4. Results (to be filled in by the team; currently EMPTY)

| Participant | Role background | T1 | T2 | T3 | T4 | T5 | T6 | SUS | Main comments |
|---|---|---|---|---|---|---|---|---|---|
| P1 | | | | | | | | | |
| P2 | | | | | | | | | |
| P3 | | | | | | | | | |
| P4 | | | | | | | | | |
| P5 | | | | | | | | | |

In each task cell, record ✓ / ✓h (completed with a hint) / ✗ and the seconds taken, e.g. `✓ 35 s`.

**Summary to report:**
- completion rate per task;
- median time per task;
- mean SUS (with n);
- the 3 to 5 most frequent problems, each with severity (high / medium / low) and the proposed change.

## 5. Automated walkthrough (done, 2026-10-25)

`python evaluation/usability_walkthrough.py` performs T1 to T6 through the real UI (headless Edge)
as the matching demo role. It checks the completion criterion and compares the number shown with
the warehouse facts. Results are in `docs/evaluation/results/usability_walkthrough.json` and the
evaluation report.

What it shows:
- every task **can** be completed through the intended UI by the intended role;
- the number the user would read is correct;
- how many user actions the shortest (expert) path takes.

What it **cannot** show:
- whether real users find the path;
- whether they understand the wording;
- whether they trust the numbers.

That is what the participant sessions in §1 to §4 are for.

## 6. Usability observations from development (not user data)

The developers noticed these while testing. They are hypotheses for the participant sessions to
confirm or reject:
- **Ageing labels.** In Superset the bucket names carry a sort prefix ("1 1-30 days overdue"). The assistant hides it; the Superset chart does not.
- **KPI card currency.** Superset KPI cards show amounts without the currency code (tables show "BTN").
- **Apply filters step.** Native filters require clicking **Apply filters**. Users may expect immediate filtering.
- **Brittle phrasing.** The assistant's deterministic interpreter is phrasing-sensitive (see docs/backend/EVALUATION.md). Users may need the example questions.
- **Two logins.** There are separate accounts for Superset and the assistant (no single sign-on).
