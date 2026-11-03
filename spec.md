# Specification: Family Finance Dashboard --- Module 1

-   **Document status:** Initial draft
-   **Module:** Monthly Asset Summary and Dashboard
-   **Language:** Thai-first interface (English labels may be used where
    useful)
-   **Version:** 0.1

## 1. Purpose

Build a family finance dashboard based on the user's existing Excel
workflow. The first module focuses only on recording month-end balances
across accounts, calculating the change in total assets compared with
the previous month, and presenting the information clearly.

The system must preserve the simplicity of the existing workbook. It is
not intended to be a daily bookkeeping application.

## 2. Scope

### Included in Module 1

-   Maintain a list of financial accounts.
-   Organize accounts into four purpose-based groups.
-   Enter and edit each account's month-end balance.
-   Retain historical monthly balances.
-   Calculate total assets for each month.
-   Calculate the difference between the current month's total and the
    previous month's total.
-   Present the monthly data in a table resembling the existing Excel
    layout.
-   Provide a dashboard view that summarizes the recorded information.
-   Allow older months to be edited, with dependent totals and
    month-to-month changes recalculated.

### Explicitly out of scope for this module

-   Daily transaction recording.
-   Full income-and-expense accounting.
-   Mortgage repayment simulations or scenario calculations.
-   Detailed mortgage principal and interest calculations.
-   Automatic bank account synchronization.
-   Investment performance calculations or live market-price feeds.

These may be considered in later modules. Module 1 should be structured
so that future modules can connect without requiring the existing data
to be rebuilt.

## 3. Existing workflow to preserve

The current workbook is a monthly balance snapshot:

1.  At the end of a month, enter the actual balance of each account.
2.  Sum the account balances to obtain that month's total.
3.  Compare the current month's total with the previous month's total.
4.  Show the difference as the increase or decrease in total assets.

The existing calculation is intentionally simple. There are no complex
formulas for income, expenses, or cash flow in the original table.

**Core calculation:**

`Monthly change = Current month's total assets - Previous month's total assets`

For the first recorded month, show the total assets. Do not calculate a
month-to-month change unless a previous month exists.

The system must not reinterpret this difference as income, savings,
spending, or profit. It is only the change in the total of the recorded
account balances.

## 4. Account groups

Accounts are organized by their purpose, not merely by the financial
institution or account type.

### Group A --- Expense-management and earmarked accounts

Examples: - Annual-expense reserve, funded with approximately THB 27,000
per month for planned periodic costs such as insurance and appliances. -
Husband's monthly spending account. - User's monthly spending account.

The two personal spending accounts are topped up at the beginning of the
month based on their budgets. Their balances may reflect spending
through cash and credit cards, according to the user's existing tracking
method.

### Group B --- Bank deposits and savings

Examples may include savings accounts and other bank deposit accounts
that are not primarily used for monthly spending.

### Group C --- Investments and low-frequency assets

Examples: - Stocks. - Cooperative savings or shares. - Gold held in an
online account.

These balances may not be updated every month. The system should allow a
balance to remain unchanged until the user enters a new valuation, while
making the last-updated period visible where useful. Do not imply that
an unchanged value is a freshly verified market valuation.

### Group D --- Flexible mortgage reserve

Examples: - LH account. - Other funds the user keeps available for
possible additional home-loan payments.

The exact account names and ordering are configurable and should not be
treated as final at this stage.

## 5. Account management

The user must be able to:

-   Add an account.
-   Edit an account's display name.
-   Move an account between groups.
-   Change the display order of accounts within a group.
-   Add or edit an optional note.
-   Deactivate an account that is no longer in use, without deleting its
    history.

### Account identity and name changes

Every account must have a persistent, unique internal Account ID that is
independent of its display name.

Changing an account name is a label correction or display-name edit for
the **same account**. It must not create a new account or break the
relationship between that account and its historical balances.

After a name change: - All historical balances remain associated with
the same Account ID. - Historical reports and calculations continue to
work. - References to the account use the updated display name. - No
historical data is deleted or duplicated.

Moving an account to another group or changing its display order must
also preserve its history.

## 6. Monthly balance entry

The primary data-entry view should resemble the existing Excel table.

Expected layout: - Accounts displayed as rows. - Months displayed as
columns, or an equally clear month-by-month table layout. - Accounts
visually grouped under the four categories in Section 4. - Group and
account ordering controlled by the user. - Monthly total assets shown
clearly. - Monthly change from the previous month shown clearly.

For each account and month, store: - Account ID. - Month / reporting
period. - Balance entered by the user. - Optional note, if needed.

The user should be able to add a new month without overwriting prior
months and edit a previously entered month.

If an account was not yet in use during an earlier period, the system
should distinguish "not applicable / not yet added" from a confirmed
zero balance. The exact display behavior can be finalized during
implementation.

## 7. Calculations and historical integrity

For each reporting month:

`Total assets = Sum of the recorded balances included in that month's asset total`

`Monthly change = Current month's total assets - Previous month's total assets`

Requirements: - Recalculate totals when a balance is added or edited. -
Recalculate month-to-month changes when a historical month is edited. -
Recalculate subsequent months' comparisons when an earlier month's total
changes. - Preserve all other historical entries. - Do not silently
replace missing values with zero. - Make the reporting period used for
each total clear.

The initial module should not infer the reason for an increase or
decrease. It should report the actual difference in recorded balances
without inventing an explanation.

## 8. Dashboard

The dashboard should make the monthly financial position easier to
understand while keeping the original table as the main data-entry view.

Potential dashboard elements: - Total assets for the selected month. -
Increase or decrease compared with the previous month. - A historical
trend of total assets. - Balances by the four account groups. - A clear
view of the balances in the flexible mortgage reserve. - The date or
month of the latest recorded balance.

The dashboard must distinguish a total asset figure from money that is
immediately available to spend. Grouping accounts by purpose helps
communicate that distinction; do not label all assets as freely
available cash.

Avoid alarming visual treatment of a negative monthly change. Use
neutral, factual presentation and make the comparison period explicit.

## 9. Data integrity, backup, and auditability

Financial history is more important than visual polish.

The system should: - Preserve historical monthly entries. - Avoid
destructive edits. - Keep account identity stable. - Validate that
balances are numeric and reporting periods are valid. - Provide a
backup/export path before significant structural changes. - Make it
possible to export the recorded data in a common format such as CSV or
Excel. - Avoid deleting historical records when an account is
deactivated or renamed.

Any future database migration or change to calculation logic should be
tested against existing records before being applied.

## 10. Future extensibility

The architecture should leave room for future modules, but they are not
part of the current implementation.

### Future Module 2 --- Mortgage repayment table

The user already maintains a separate mortgage workbook with its own
repayment and scenario logic. A future module may connect to it, but
Module 1 must not redesign, replace, or alter that existing logic.

### Future Module 3 --- Income and expense ledger

A future module may record income and expenses in more detail and help
explain changes in account balances. It should be designed separately
and connected to the asset summary only when its rules are agreed.

### Integration principle

Keep the monthly asset snapshot as its own reliable data set. Future
modules may reference or reconcile with it, but must not change the
meaning of the existing monthly total or monthly-change calculation
without explicit agreement.

## 11. Open decisions for a later design pass

The following details are intentionally not assumed: - Exact account
names and final ordering. - Whether all account balances are entered
every month or some are updated only when available. - How credit-card
outstanding amounts are represented in the current workbook. - Whether
the existing total includes assets only or also deducts any
liabilities. - Exact dashboard charts and visual layout. - Import format
and migration approach from the existing Excel workbook.

These should be confirmed from the actual workbook or during the next
design step.

## 12. Acceptance criteria

Module 1 is ready for initial use when:

1.  The user can create and organize accounts in the four purpose-based
    groups.
2.  The user can enter month-end balances in a table-like view similar
    to the existing workbook.
3.  The system calculates the total of recorded account balances for
    each month.
4.  The system calculates the difference between the current and
    previous month's totals.
5.  Editing an older month's balance updates the affected totals and
    subsequent month-to-month changes.
6.  Renaming an account preserves its Account ID and all historical
    balances.
7.  Deactivating an account preserves its historical records.
8.  The dashboard shows the selected month's total and its change from
    the previous month without presenting the change as a detailed
    income/expense result.
9.  Data can be backed up or exported.
10. The design leaves a clear path for future mortgage and
    income/expense modules without implementing them now.
