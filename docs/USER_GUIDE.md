# DrukSmart Analytics: user guide

For the HR Manager, the Accounts Manager, branch managers, executives and the administrator. The website is
meant for managers and senior management, not for every employee.

Everything is in **one website**: <http://127.0.0.1:8000/app/> in the local demonstration
installation; your administrator gives you the address and your account.

> **About the data.**
> - **Source and refresh.** All figures come from the company ERPs (Odoo and ERPNext), refreshed
>   automatically once a day (02:00).
> - **Checks before publication.** A refresh is published only after it passes automatic quality
>   checks; otherwise you keep seeing the previous, correctly dated figures.
> - **Demonstration installation.** In the demonstration installation, the ERPs contain **test data**,
>   and a fallback mode can show a **fictional (synthetic) dataset**, always labelled as such
>   (a red "Synthetic demonstration data" label).

## 1. Sign in and what you can see

1. Open the website and sign in with your **username** and **password**. The eye button shows the password while you type.
2. After **5 wrong passwords in 15 minutes**, the account is locked for 15 minutes; the administrator can unlock it.
3. You stay signed in for up to 8 hours. **Sign out** is at the top right.
4. If your session ends, the website asks you to sign in again and then returns to the page you were on.

| Role | Overview | HR Analytics | Accounts Analytics | Ask AI, Reports about |
|---|---|---|---|---|
| **HR Manager** | HR figures | ✓ + builds and publishes HR dashboards | — | headcount, departments, leave |
| **Accounts Manager** | Accounts figures | — | ✓ + builds and publishes Accounts dashboards | receivables, payables, overdue, ageing |
| Executive | both | ✓ | ✓ | everything above |
| Branch Manager | both, **own branch only** | ✓ own branch | ✓ own branch | everything above, own branch only |
| Administrator | both | ✓ | ✓ | everything, plus **Administration** |

- The menu on the left shows only your pages. On a phone, open it with **☰**.
- You never see individual employees' personal details, salaries, bank details or identity data. They are not in the analytical data at all.

## 2. Overview

The first page shows your most important figures, as of the latest validated data:
- **HR:**
  - **Active employees**;
  - **Departments with active staff**;
  - **Employees on approved leave** in the current month (with requests and days);
  - a chart of active employees **by department**.
- **Accounts:**
  - **Outstanding receivables** (owed to us) and **payables** (owed by us), with the number of open documents;
  - **Overdue** receivables and payables;
  - charts of balances **by ageing** (how long amounts are overdue). *Unapplied credit* (negative) is a payment or credit note not yet matched to an invoice.

**Labels at the top:**
- **Data as of** (the date the figures describe) and **Refreshed … ago** (when the data was last published).
- **Data may be out of date** (orange): the daily refresh may have failed. Treat the figures with care and tell the administrator.
- **Limited to your branch** (branch managers).

Each chart has **Chart / Table** buttons; *Table* shows the exact numbers. Amounts are in each company's currency and are never added across currencies.

## 3. HR Analytics and Accounts Analytics (dashboards)

These pages show the governed dashboards (made with Apache Superset) inside the website. You do not need a separate login.

- **Filters** (left panel), for example *Snapshot date*, *Leave period*, *Organisation*, *Branch*, *Department*, *Currency*:
  1. choose values;
  2. click **Apply filters**;
  3. *Clear all* resets them.
- **Point-in-time figures:** headcount and balances are **as of one date** (the newest date is pre-selected). Never add up figures from different dates.
- **Cross-filter:** click a bar or slice to filter the other charts by it; click again to remove it.
- **Drill by:** right-click a value and choose a dimension (e.g. Department) to break it down.
- **Chart menu ⋮:**
  - **View as table**, **Enter fullscreen**;
  - **Download → Export to .CSV / Excel / image**. Downloads contain only what you are allowed to see; branch restrictions apply.
- **Data freshness:** the table on each dashboard shows the date and age of the data per ERP.
- **Several dashboards:** if the administrator published more than one for your module, choose it with the tabs above the dashboard.

**HR Manager and Accounts Manager: building your own dashboards.**
1. Click **Edit in Superset (separate sign-in)** (or **Manage dashboards → Build in Superset**). Superset opens in a new tab; sign in with your **Superset** account. This second sign-in is a known limitation of this version.
2. Create a **new** dashboard (*Dashboards → + Dashboard*) and charts with your module's data, using the certified metrics (✓). The official dashboards are protected: you cannot change or copy them.
3. Back in the website, open **Manage dashboards**:
   - enter the dashboard's number (from its Superset address, e.g. …/superset/dashboard/**12**/) and **Publish** it on your module's page; the website refuses a dashboard that uses another module's data;
   - switch it from *Hidden* to **Visible**. It then appears as a tab on your module's page for everyone who can see that module.

## 4. Ask AI

1. Type a question, or click a **suggested question** on the right, then press **Ask** (or Enter).
2. The answer shows:
   - a status label;
   - the sentence;
   - the KPI, date, refresh age and any filters;
   - a chart for breakdowns;
   - **Show the figures as a table**;
   - **Explore in … Analytics** to open the matching dashboard.
3. The conversation stays while you use other pages. **Clear conversation** removes it; signing out also clears it.

### Questions you can ask
- How many active employees are there? / How many employees work in each department? (or *per branch*)
- How many people work in Sales? / … in the Phuentsholing branch?
- How many employees are on approved leave? (counted in the month the leave **starts**; default: the latest month)
- How many leave days were approved in October 2026?
- What is the outstanding receivables balance? / … payables balance?
- How much is overdue? / Show overdue balances by ageing category. / Show the ageing of receivables.
- What was the headcount on 2026-10-23?

### What the answer labels mean

| Label | Meaning | What to do |
|---|---|---|
| **Answer from warehouse data** (green) | Correct figure from the validated data | — |
| **Needs clarification** | The question can mean several things | Click one of the suggested questions |
| **Check your filter** | A name or date was not found | Use one of the listed valid values |
| **No matching data** | Valid question, but no data for that date or filter | Pick another date |
| **Not authorised** | The KPI belongs to a module or branch outside your role | Ask the administrator if you need access |
| **Not supported** | Personal data, lists of people, changes to data, forecasts, other business areas | Ask an aggregated KPI question |
| **Data may be out of date** | The figures are older than the daily refresh should allow | Treat with care; tell the administrator |
| **Synthetic demonstration data** | Fictional demonstration data, not from an ERP | Demonstration only |
| **Service unavailable** | The database is not reachable | Try again later |

The assistant only reports approved KPIs. It **never** guesses numbers, shows individual people,
or changes ERP data. The answer says which interpreter was used. In this version it is
"Deterministic rules, no language model", so unusual phrasings may get *Needs clarification* or
*Not supported*. Rephrase, or use a suggested question.

## 5. Reports

1. Each report is one approved KPI broken down in a fixed way, for example *Active headcount by department* or *Ageing of open balances*.
2. Optionally choose **As of** (a date), or **From/To** (a period) for leave reports. Empty means the latest data.
3. **Preview** shows a chart and a table. **Download CSV** saves the file (Excel opens it).

Reports contain only your modules and, for branch managers, only your branch. Files of synthetic
data are labelled in the file name and in every row.

## 6. Administration (administrator only)

- **Platform status:**
  - whether the warehouse is reachable and whether live or synthetic data is shown;
  - when HR and Accounts data were last published, per ERP;
  - whether Superset and the embedding service account work;
  - which assistant interpreter is active.
- **Dashboard visibility:** the **Manage dashboards** page, for both modules (the HR and Accounts Managers have the same page for their own module):
  - show or hide each dashboard;
  - publish a dashboard built in Superset (the website enables embedding and refuses data of another module); it starts hidden;
  - *Remove* takes a dashboard out of the website (it stays in Superset). Official dashboards can only be hidden.
- **Users and roles:** every user's role, modules and branches. To add users or change roles and branches, use **Add or edit users, roles and branches (Django admin)**.
  - Give each person **one** DrukSmart role, and give branch managers their branches. A branch manager without a branch sees nothing.
  - HR and Accounts Managers also need a Superset account with the same role (for building dashboards).
  - Unlock a locked account by deleting its *Login failures* in Django admin.

## 7. Common problems

| Problem | Solution |
|---|---|
| "Username or password is incorrect" | Check the spelling. After 5 failures, wait 15 minutes or ask the administrator |
| "Your session has ended" | Sign in again; you return to the same page |
| A dashboard says "not available to you" | Your role or branch does not include it; ask the administrator |
| "The dashboard service is not reachable" | Superset is not running; click *Try again* later or tell the administrator |
| A chart says *No results were returned* | Your filters (or your branch restriction) leave no data. Clear the filters |
| Figures look old | Check the *Refreshed … ago* label; the daily refresh may have failed. Tell the administrator |
| Branch manager sees an empty Accounts dashboard | ERPNext invoices have no branch yet (open business decision DS-AC-05) |
| Superset asks for a login when I click "Edit in Superset" | Expected: building dashboards uses your separate Superset account |
