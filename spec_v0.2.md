# Specification: Family Finance Dashboard --- Module 1

-   **Document status:** Updated draft
-   **Version:** 0.2
-   **Module:** Monthly Asset Summary and Dashboard
-   **Primary language:** Thai

## 1. Purpose

Build a family finance dashboard based on the user's existing Excel
workflow. Module 1 manages account balances at two points in each month
--- **ต้นเดือน (beginning of month)** and **ปลายเดือน (end of month)** ---
and summarizes the remaining balances by account, group, and overall
total.

The system should preserve the familiar table-based workflow and remain
simple to use. It is not intended to become a daily bookkeeping
application.

## 2. Scope

### Included in Module 1

-   Maintain account groups and accounts within those groups.
-   Allow the user to rename and reorder groups and accounts.
-   Record balances twice per month: beginning and end of month.
-   Ask for the month's income before beginning-of-month balances are
    prepared.
-   Calculate suggested transfers for the three designated Group A
    accounts and the LH account.
-   Carry forward prior month-end balances as the next month's beginning
    balances for other accounts.
-   Allow automatically carried-forward values to be edited.
-   Calculate end-of-month remaining balances by account and group.
-   Calculate the total asset balance and compare it with the previous
    period/month.
-   Retain and allow editing of historical data, with dependent
    calculations updated accordingly.
-   Provide a table-based data-entry view and a dashboard summary.

### Explicitly out of scope for this module

-   Daily transaction recording.
-   A full income-and-expense ledger.
-   Mortgage repayment scenarios or mortgage interest/principal
    calculations.
-   Automatic bank synchronization.
-   Live investment prices or investment-performance analysis.

Future mortgage and income/expense modules may connect later. They are
not to be designed or implemented as part of this update.

## 3. Period and balance model

Each calendar month has two balance snapshots:

1.  **ต้นเดือน** --- the balance available at the beginning of the month,
    after the planned transfers/top-ups have been made.
2.  **ปลายเดือน** --- the actual balance recorded at the end of the
    month.

Each snapshot stores a balance for each account. The system must retain
both snapshots independently.

The main data-entry view should continue to resemble the user's existing
Excel table, with accounts as rows and periods as columns or clearly
separated beginning/end sections.

## 4. Account groups and account management

Accounts are grouped by purpose. The initial suggested groups are:

-   **Group A --- Expense-management and earmarked accounts**
    -   A-1: annual-expense reserve; suggested monthly transfer is THB
        27,000.
    -   A-2: husband's monthly spending account; target balance is THB
        36,600.
    -   A-3: user's monthly spending account; target balance is THB
        24,000.
-   **Group B --- Bank deposits and savings**
-   **Group C --- Investments and low-frequency assets**
    -   Examples: stocks, cooperative savings/shares, and gold held in
        an online account.
-   **Group D --- Flexible mortgage reserve**
    -   Includes the LH account used for flexible funds and potential
        additional mortgage payments.

These group names and examples are starting labels, not fixed system
constants. The user must be able to change them.

### Group management

The user must be able to: - Add a group. - Rename a group. - Change the
display order of groups. - Optionally add or edit a group note. -
Deactivate a group without deleting its historical data, subject to its
accounts being moved or otherwise handled safely.

### Account management

The user must be able to: - Add an account. - Edit its display name. -
Move it to another group. - Change the display order of accounts within
a group. - Add or edit an optional note. - Deactivate an account without
deleting its history.

### Identity and renaming rules

Each group and account must have a persistent internal ID independent of
its display name.

Renaming a group or account changes only its display label. It must not
create a new group/account, detach historical records, or reset
balances.

Reordering or moving an account between groups must preserve its
historical records. Historical reports should show the current display
names unless a future requirement explicitly calls for historical name
snapshots.

## 5. Beginning-of-month workflow

### 5.1 Income prompt

Before the user enters or confirms the beginning-of-month balances for a
month, the system must ask:

**"รายรับของเดือนนี้เท่าไร?"**

Store the entered amount against that month. The income value is used by
the transfer calculation in Section 5.2. This is not yet a full income
ledger.

### 5.2 Suggested transfer calculations

After the user enters the month's income, calculate and display the
following suggested transfer amounts:

  Destination                                       Calculation
  ------------- -----------------------------------------------
  A-1                                                THB 27,000
  A-2             THB 36,600 − A-2's previous month-end balance
  A-3             THB 24,000 − A-3's previous month-end balance
  LH                      This month's income − A-1 − A-2 − A-3

Definitions: - A-1, A-2, and A-3 refer to the designated accounts in
Group A, identified by their persistent account IDs rather than their
editable display names. - "Previous month-end balance" means the
recorded **ปลายเดือน** balance of the same account in the immediately
preceding month. - The LH transfer is the remainder of the month's
income after the three Group A transfers have been allocated.

The system must show the calculation and its inputs so the user can
review the suggested amounts before using them.

Do not silently clamp negative results to zero or alter the formulas. If
a calculated transfer is negative, show it clearly and flag it for the
user's review. The user must be able to correct the input data before
confirming the beginning-of-month balances.

If there is no previous month-end balance for A-2 or A-3, the system
must not silently assume one. It should request a value or clearly
indicate that the calculation cannot yet be completed.

### 5.3 Populate beginning-of-month balances

After the user reviews/confirms the calculated transfers:

-   Enter the calculated A-1, A-2, and A-3 transfer amounts into the
    corresponding accounts' **ต้นเดือน** values for the current month.
-   Enter the calculated LH amount into the LH account's **ต้นเดือน**
    value for the current month.
-   For all other accounts, carry forward the previous month's
    **ปลายเดือน** balance into the current month's **ต้นเดือน** value.
-   Automatically carried-forward values are editable by the user.
-   The user must be able to review and confirm the complete set of
    beginning-of-month balances before proceeding.

The transfer calculation must use the previous month's end balance, not
a value from a different account or period.

## 6. End-of-month workflow

At the end of the month, the user enters the actual **ปลายเดือน** balance
for each account.

After the end-of-month data is entered, calculate and display:

-   End-of-month remaining balance for each account.
-   Total remaining balance for each group.
-   Overall total assets for the month.

For the initial implementation, "เงินคงเหลือ" means the recorded
**ปลายเดือน** balance. Group remaining balance is the sum of the
end-of-month balances of accounts in that group. Overall total assets is
the sum of the included account end balances.

The system may also show the difference between each account's beginning
and end balances as supplementary information, but it must label this as
a balance change, not as a complete measure of spending. The same
applies to group-level changes.

## 7. Monthly and historical calculations

For each month:

`Group end balance = Sum of end-of-month balances of accounts in that group`

`Total assets at month-end = Sum of end-of-month balances of all included accounts`

`Monthly change = Current month's total assets - Previous month's total assets`

The original month-to-month comparison remains in place. It must not be
redefined as income, expenses, savings, or profit.

Requirements: - Recalculate group totals and overall totals when an
account balance changes. - Recalculate account/group comparisons when
applicable. - If a historical beginning or end balance is edited, update
all dependent calculations. - If a prior month-end balance changes,
update the next month's automatically carried-forward beginning balance
only according to a clearly defined carry-forward rule. Do not overwrite
a user-edited beginning balance without warning. - Recalculate
subsequent month-to-month total-asset changes when a historical
month-end total changes. - Preserve all other historical entries. -
Distinguish missing/not-yet-entered values from confirmed zero balances.

## 8. Table and dashboard

### 8.1 Data-entry table

The primary view should remain similar to the existing Excel layout:

-   Groups appear in the user's chosen order.
-   Accounts appear under their respective groups in the user's chosen
    order.
-   Each month has distinct **ต้นเดือน** and **ปลายเดือน** values.
-   The monthly income input and calculated transfer suggestions are
    visible in the beginning-of-month workflow.
-   Group totals and overall totals are clearly displayed.
-   Historical months remain accessible and editable.

### 8.2 Dashboard

Potential dashboard elements: - Selected month's overall end-of-month
total assets. - Total assets change compared with the previous month. -
End-of-month remaining balance by group. - End-of-month remaining
balance by account. - Beginning-to-end balance changes, clearly labelled
as balance changes. - Monthly income and the calculated
allocation/transfer summary. - Historical trend of total assets.

The dashboard must distinguish total assets from funds that are
immediately available to spend. Avoid presenting all assets as freely
available cash.

Use neutral, factual presentation for increases and decreases. Always
identify the period being compared.

## 9. Data integrity, backup, and historical editing

Financial history must be preserved.

The system should: - Store beginning and end balances as separate
records/fields for each account and month. - Store the monthly income
input and the calculated transfer results, including the inputs used in
the calculation. - Preserve account and group IDs when names or display
order change. - Preserve historical data when accounts or groups are
deactivated. - Validate numeric balances and income values. - Provide
backup and export options, such as CSV or Excel. - Avoid destructive
edits. - Warn before an edit causes dependent values to change.

For automatic carry-forward, retain whether a beginning balance is: -
Automatically copied from the previous month-end balance; or - Manually
edited/overridden by the user.

This allows the system to update automatic values safely without
unexpectedly replacing manual corrections.

## 10. Future extensibility

The following modules are planned for the future but are not part of
Module 1 implementation:

### Future Module 2 --- Mortgage repayment table

The user already maintains a separate mortgage workbook with its own
repayment and scenario logic. A future module may connect to it. Module
1 must not redesign, replace, or modify that existing mortgage logic.

### Future Module 3 --- Income and expense ledger

A future module may record detailed income and expenses and help explain
changes in account balances. The monthly income prompt in Module 1 is
only a single monthly input used for the transfer calculation; it is not
a substitute for that future ledger.

### Integration principle

Keep the monthly balance snapshots and their calculations reliable and
independent. Future modules may connect to them, but must not change the
meaning of the recorded balances or existing total-asset calculation
without explicit agreement.

## 11. Open decisions for a later design pass

The following details remain to be confirmed: - Whether the three Group
A transfer formulas should always use the stated fixed amounts or be
configurable by the user. - How to handle the first month when no
previous month-end balance exists for A-2 or A-3. - Whether the system
should allow a month to proceed when the LH calculation is negative. -
Whether the beginning-to-end difference should be shown as a prominent
figure or only as supplementary information. - Whether the monthly
income prompt should accept one total amount only, or later support
multiple income sources. - Exact treatment of accounts that are not
updated every month, particularly investment/low-frequency accounts. -
Whether any liabilities or credit-card outstanding amounts are included
in the current asset totals. - Exact dashboard visual design and the
method for importing existing Excel history.

These decisions should be confirmed before implementation of the
relevant behavior. Do not invent additional financial rules.

## 12. Acceptance criteria

Module 1 is ready for initial use when:

1.  The user can add, rename, and reorder groups.
2.  The user can add, rename, move, and reorder accounts within groups.
3.  Renaming groups/accounts preserves their IDs and all historical
    records.
4.  The user can record both **ต้นเดือน** and **ปลายเดือน** balances for
    each month.
5.  Before beginning-of-month balances are prepared, the system asks for
    that month's income.
6.  The system calculates A-1 = THB 27,000.
7.  The system calculates A-2 = THB 36,600 minus the previous month-end
    balance of A-2.
8.  The system calculates A-3 = THB 24,000 minus the previous month-end
    balance of A-3.
9.  The system calculates LH = monthly income minus the three calculated
    Group A transfers.
10. After confirmation, the calculated transfer amounts populate the
    relevant current-month beginning balances.
11. Other accounts' previous month-end balances are carried forward into
    the current month's beginning balances and remain editable.
12. After end-of-month entry, the system shows remaining balances by
    account and group, plus the overall total.
13. Editing historical data updates dependent calculations without
    deleting or silently overwriting manually edited values.
14. The original month-to-month total-asset comparison remains available
    and retains its original meaning.
15. The system provides a backup/export path and leaves room for future
    mortgage and income/expense modules.
