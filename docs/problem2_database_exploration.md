# Problem 2: Campus Customs database exploration

**Source:** `data (4).zip` from Professor Zaman, containing one file, `data/campus_customs.db` (53,248 bytes).
**Method:** read-only SQLite queries using `mode=ro&immutable=1`, run against the untouched original. No records were
changed.

Labels used in this report:
- **Verified:** read directly from a query result.
- **Interpretation:** a preliminary reading that the next problems must confirm or correct.

---

## 1. Files

| Role | Path (relative to `Homework 5/`) | SHA-256 |
|---|---|---|
| Original archive (read-only) | `data/archive/hw5_data_original.zip` | `df5f6381…deb99b` |
| Original database (read-only, never modify) | `data/campus_customs.db` | `23686a90…21f360a` |
| Working database (agents may modify it from Problem 3 on) | `data/campus_customs_new.db` | `23686a90…21f360a` (identical to the original at creation) |

Everything under `data/` is excluded from Git. To reset the working copy, copy the original over it again.

---

## 2. Schema overview (verified)

`PRAGMA integrity_check` = `ok`. `PRAGMA foreign_key_check` = no violations. There are 9 tables, and no views,
triggers or explicit indexes.

| Table | Rows | Primary key | Purpose |
|---|---:|---|---|
| `desk` | 1 | none | The shop's "today" (`date_today`) and free-text desk notes |
| `tickets` | 3 | `id` | Incoming operational requests the agents must handle |
| `inventory` | 10 | (`sku`, `size`) | Stock on hand for each product and size, with its aisle location |
| `pricing` | 4 | `sku` | Unit cost and list price for each product |
| `vendors` | 3 | `id` | Suppliers and couriers, with lead times |
| `invoices` | 1 | `id` | Amounts owed to vendors (accounts payable) |
| `leases` | 1 | `id` | The shop's rented space and its rent schedule |
| `cash_accounts` | 1 | `name` | Cash available to pay obligations |
| `payments` | 0 | `id` | Ledger of payments made. It's empty, so it's ready for agents to write to |

### Columns

| Table | Columns (type, constraints) |
|---|---|
| `desk` | `date_today` TEXT NOT NULL · `notes` TEXT |
| `tickets` | `id` INTEGER PK · `type` TEXT NN · `requester` TEXT NN · `subject` TEXT NN · `sku` TEXT · `size` TEXT · `qty` INTEGER · `lease_id` INTEGER FK→`leases.id` · `invoice_id` INTEGER FK→`invoices.id` · `status` TEXT NN · `notes` TEXT · `created_at` TEXT NN |
| `inventory` | `sku` TEXT NN · `name` TEXT NN · `size` TEXT NN · `qty` INTEGER NN · `location` TEXT NN · PK(`sku`,`size`) |
| `pricing` | `sku` TEXT PK · `unit_cost` REAL NN · `list_price` REAL NN |
| `vendors` | `id` INTEGER PK · `name` TEXT NN · `specialty` TEXT NN · `lead_days` INTEGER NN |
| `invoices` | `id` INTEGER PK · `vendor_id` INTEGER NN FK→`vendors.id` · `amount` REAL NN · `due_date` TEXT NN · `status` TEXT NN · `description` TEXT |
| `leases` | `id` INTEGER PK · `space_name` TEXT NN · `landlord` TEXT NN · `monthly_rent` REAL NN · `next_due` TEXT NN · `notes` TEXT |
| `cash_accounts` | `name` TEXT PK · `balance` REAL NN · `date` TEXT NN |
| `payments` | `id` INTEGER PK · `kind` TEXT NN · `ref_id` INTEGER · `amount` REAL NN · `account` TEXT NN · `paid_at` TEXT NN · `approved_by` TEXT NN |

### Relationships

These are declared as foreign keys (verified):
- `invoices.vendor_id` → `vendors.id`
- `tickets.invoice_id` → `invoices.id`
- `tickets.lease_id` → `leases.id`

These are implied by matching values but are **not** declared as foreign keys (verified that the values match):
- `tickets.(sku, size)` → `inventory.(sku, size)`. Both ticket SKU and size pairs exist.
- `inventory.sku` ↔ `pricing.sku`. Both tables have exactly the same 4 SKUs.
- `payments.account` → `cash_accounts.name`. Interpretation: no payments exist yet.
- `payments.ref_id` with `payments.kind` → an invoice or lease id. Interpretation: this is a link that can point to
  more than one table, so no foreign key is possible.

```
vendors 1──* invoices 1──* tickets *──1 leases
                              │
                        (sku,size) ··· inventory (sku) ··· pricing
payments ··· (kind, ref_id) ··· invoices | leases
payments.account ··· cash_accounts.name
desk (standalone: current business date)
```

---

## 3. Operational reference data (verified)

- **Business date:** `desk.date_today` = **2026-08-31**. `desk.notes` = NULL.
- **Cash:** `checking` = **$3,400.00** as of 2026-08-31. This is the only cash account.
- **Payments:** 0 rows.

**Inventory and pricing**

| SKU | Name | S | M | L | XL | OS | Location | Unit cost | List price |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| CC-HOOD-NAVY | Basic Hoodie Big Yale | 4 | **8** | 14 | 6 | – | Aisle A | 22.00 | 58.00 |
| CC-TEE-WHITE | Classic Bulldog Tee | **0** | 5 | 3 | 2 | – | Aisle B | 8.00 | 28.00 |
| CC-HAT-BLUE | Yale Cap | – | – | – | – | 40 | Aisle C | 6.00 | 22.00 |
| CC-MUG-CREST | Crest Mug | – | – | – | – | **0** | Aisle D | 3.50 | 14.00 |

**Vendors:**
- (1) Bulldog Print Co: apparel reprint, 5-day lead time
- (2) Elm City Gifts: mugs and small goods, 3-day lead time
- (3) QuickShip CT: local courier, 1-day lead time

**Invoice 501:** vendor 1 (Bulldog Print Co), **$840.00**, due **2026-08-28**, status `open`, "Rush reprint
CC-TEE-WHITE S".

**Lease 1:** Chapel Street shop, landlord Elm City Properties, **$2,400.00 per month**, next due **2026-09-02**.

---

## 4. The three tickets

All three tickets have status `open` and were created on 2026-08-31, the business date.

### Ticket 101: `customer_order`, "Bulldog tee"

- **Requester:** Tauhid Zaman. Notes: "Needs a tee in size S." Created 09:15 (UTC−4).
- **Request:** CC-TEE-WHITE, size S, quantity 1. Linked to invoice 501.
- **Verified facts:**
  - Stock of CC-TEE-WHITE size S is **0**, in Aisle B.
  - The list price is $28.00 and the unit cost is $8.00.
  - Invoice 501 is the Bulldog Print Co rush reprint of exactly this item: **$840.00, open, 3 days past due**.
  - Bulldog Print Co's lead time is 5 days.
  - Other tee sizes are in stock: M 5, L 3, XL 2.
- **Tables involved:** `tickets`, `inventory`, `pricing`, `invoices`, `vendors`, and later possibly `payments` and
  `cash_accounts`.
- **Missing or ambiguous:**
  - There's no customer, order or sales table, and no customer contact details.
  - The invoice doesn't say how many units it covers or whether the reprint has been delivered.
  - Whether paying the invoice restocks size S, and when.
  - Interpretation: paying the overdue invoice may be what unblocks the reprint. If the 5-day lead time counts from
    payment, size S wouldn't be in stock until about 2026-09-05.
- **Concerns:**
  - The order can't be filled from stock.
  - Paying the invoice uses cash that the rent also needs (see ticket 102).
  - An agent must not reduce the stock below 0 or invent a delivery.

### Ticket 102: `rent_notice`, "Rent due"

- **Requester:** Elm City Properties. Notes: "Email: shop rent due in 2 days." Created 11:05.
- **Linked to:** lease 1.
- **Verified facts:**
  - Rent is **$2,400.00**, due **2026-09-02**, which is 2 days after the business date. That matches the email.
  - The landlord on the ticket matches the lease.
  - Checking has $3,400.00, which covers the rent.
- **Tables involved:** `tickets`, `leases`, `cash_accounts`, and later `payments`.
- **Missing or ambiguous:**
  - No approval policy says who can authorize a payment, even though `payments.approved_by` is required.
  - There's no payment method or landlord bank details.
  - Whether rent should be paid now or on the due date.
  - The source is an email notice, so it isn't independently verified.
- **Concerns:**
  - Interpretation: paying both the rent and invoice 501 costs $3,240.00 and leaves **$160.00** in checking.
    That's feasible but tight, so the order of payments and the approval step both matter.
  - After the rent is paid, `leases.next_due` would need to move forward. Nothing in the schema says how
    (interpretation: probably one month, to 2026-10-02).

### Ticket 103: `price_override`, "Bulk hoodie discount"

- **Requester:** Yale AI Club. Notes: "Student org wants 20 hoodies, size M, asking for a bulk discount."
  Created 16:55.
- **Request:** CC-HOOD-NAVY, size M, quantity 20. No invoice or lease is linked.
- **Verified facts:**
  - Stock of size M is **8**, so the order is **12 units short**.
  - Total hoodie stock across all sizes is 32 (S 4, M 8, L 14, XL 6).
  - At list price, 20 hoodies cost $1,160.00. At unit cost they cost $440.00. The gross margin at list price is
    62.1%.
- **Tables involved:** `tickets`, `inventory`, `pricing`, possibly `vendors` (a reprint from Bulldog Print Co, with
  its 5-day lead time) and `invoices`.
- **Missing or ambiguous:**
  - There's no discount policy, maximum discount or approval rule.
  - No price-override table or column exists, so a discount could only be recorded by changing `pricing`, which
    would affect every customer. That would be risky.
  - There's no deadline for the order.
  - Interpretation: any price below the $22.00 unit cost would lose money.
- **Concerns:**
  - The request can't be fully filled from stock.
  - A discount decision needs human approval.
  - Ordering a reprint would create a new invoice and add pressure on cash.

---

## 5. Constraints and data issues (verified unless noted)

1. **Foreign keys aren't enforced by default** (`PRAGMA foreign_keys` = 0). Any connection that writes must turn
   them on itself.
2. **There are no CHECK constraints.** `inventory.qty` could become negative. `status` and `kind` are free text,
   with no allowed values defined. Every status in the data so far is `open`.
3. **Money is stored as REAL** (floating point). Calculations should round to cents.
4. **Dates are stored as TEXT in mixed formats.** `tickets.created_at` includes a time-zone offset; the other date
   columns are plain `YYYY-MM-DD`. The shop's "today" is `desk.date_today` (2026-08-31), not the system clock.
5. **`payments.ref_id` has no foreign key.** Its meaning depends on `kind`, so agents must use a consistent set of
   `kind` values.
6. **`payments.approved_by` is required**, but no table of approvers or roles exists.
7. **Unusual records:**
   - Invoice 501 is already **past due**.
   - A customer-order ticket is linked to a **supplier invoice**.
   - CC-MUG-CREST is out of stock (OS = 0), but no ticket mentions it.
   - `inventory.name` is repeated on every size row.
   - There are no customer or order tables. A requester is just a name.
8. Nothing tracks when changes happen. Recording what changed and when would have to be built in later problems.

---

## 6. Likely tables and fields for the agents (interpretation)

| Need | Tables and fields |
|---|---|
| Read the ticket queue and close tickets | `tickets.status`, `tickets.notes`, `type`, `sku`, `size`, `qty`, `lease_id`, `invoice_id` |
| Check stock and pricing | `inventory.qty`, `inventory.location`, `pricing.unit_cost`, `pricing.list_price` |
| Plan supplier orders | `vendors.lead_days`, `vendors.specialty`, `invoices.*` |
| Pay obligations | `cash_accounts.balance`, `invoices.status`/`amount`/`due_date`, `leases.monthly_rent`/`next_due`, insert into `payments` |
| Business date | `desk.date_today` |

## 7. Challenges for later problems

- Keep every write on `data/campus_customs_new.db` and leave `data/campus_customs.db` read-only.
- Decide when an agent may act and when it must ask a human: payments, discounts and price changes.
- Make each payment a single all-or-nothing transaction: insert into `payments`, reduce `cash_accounts.balance`,
  and update the invoice or lease status, so a failure halfway through leaves nothing half-done.
- Guard against overdrawing cash and against negative stock.
- Agree on values for `status` and `kind`, since the schema doesn't define them.

### Queries used

Run against the original (then at `data/original/campus_customs.db`, now `data/campus_customs.db`) with `mode=ro&immutable=1`:

- `PRAGMA integrity_check`, `PRAGMA foreign_keys`, `PRAGMA foreign_key_check`
- `SELECT sql FROM sqlite_master`; `PRAGMA foreign_key_list(<table>)`; `SELECT COUNT(*)` for each table
- `SELECT *` from every table (all 24 rows)
- Cross-checks, for example:
  - `SELECT sku FROM inventory EXCEPT SELECT sku FROM pricing`
  - ticket (`sku`, `size`) left-joined to `inventory`
  - `typeof()` on the quantity and money columns
- Calculated values:
  - days overdue: `julianday('2026-08-31') - julianday(due_date)`
  - cash after both payments: 3400 − 840 − 2400 = 160
  - the ticket 103 shortfall and totals, from a join of `tickets`, `inventory` and `pricing`
