# Authorization matrix

Generated from the route table by `python -m app.authz` (do not edit by hand; a test
fails when it is out of date). Enforcement is in the backend; the UI only hides
affordances. ✓ = allowed. *Any user* = any signed-in user (content may still be
filtered by role, e.g. dashboard sections, search groups, own notifications).
Service-level rules not visible here: segregation of duties (requesters never approve
their own requests), finance-manager-only voids of posted bills, masking of sensitive
fields for roles that do not need them, and record-level checks on approvals (visible
to the requester, holders of the approver role and oversight roles; decisions need the
approver role; auditors are read-only).

| Method | Path | admin | billing_clerk | insurance_officer | accountant | finance_manager | auditor |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/accounts` | ✓ |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/accounts` | ✓ |  |  | ✓ |  |  |
| GET | `/api/v1/accounts/{account_id}` | ✓ |  |  | ✓ | ✓ | ✓ |
| PATCH | `/api/v1/accounts/{account_id}` | ✓ |  |  | ✓ |  |  |
| GET | `/api/v1/approvals` | *any user* |  |  |  |  |  |
| GET | `/api/v1/approvals/pending-count` | *any user* |  |  |  |  |  |
| GET | `/api/v1/approvals/policies` | ✓ |  |  | ✓ | ✓ | ✓ |
| PATCH | `/api/v1/approvals/policies/{kind}` | ✓ |  |  |  | ✓ |  |
| GET | `/api/v1/approvals/{approval_id}` | *any user* |  |  |  |  |  |
| POST | `/api/v1/approvals/{approval_id}/comments` | *any user* |  |  |  |  |  |
| POST | `/api/v1/approvals/{approval_id}/decision` | *any user* |  |  |  |  |  |
| GET | `/api/v1/ar/aging` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/ar/dunning` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/ar/dunning/run` |  | ✓ |  |  | ✓ |  |
| GET | `/api/v1/ar/write-offs` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/ar/write-offs` |  | ✓ |  |  | ✓ |  |
| GET | `/api/v1/audit-log` | ✓ |  |  |  | ✓ | ✓ |
| GET | `/api/v1/audit-log/facets` | ✓ |  |  |  | ✓ | ✓ |
| POST | `/api/v1/auth/login` | public |  |  |  |  |  |
| POST | `/api/v1/auth/logout` | public |  |  |  |  |  |
| GET | `/api/v1/auth/me` | *any user* |  |  |  |  |  |
| POST | `/api/v1/auth/refresh` | public |  |  |  |  |  |
| GET | `/api/v1/budgets` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/budgets` |  |  |  |  | ✓ |  |
| GET | `/api/v1/budgets/alerts` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/budgets/alerts/check` |  |  |  |  | ✓ |  |
| GET | `/api/v1/budgets/{budget_id}` |  |  |  | ✓ | ✓ | ✓ |
| PATCH | `/api/v1/budgets/{budget_id}` |  |  |  |  | ✓ |  |
| POST | `/api/v1/budgets/{budget_id}/status` |  |  |  |  | ✓ |  |
| GET | `/api/v1/budgets/{budget_id}/variance` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/claims` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/claims` |  | ✓ | ✓ |  |  |  |
| GET | `/api/v1/claims/counts` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/claims/preview` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/claims/run-mock-insurer` |  |  | ✓ |  |  |  |
| GET | `/api/v1/claims/{claim_id}` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/claims/{claim_id}/accept-short-pay` |  |  | ✓ |  |  |  |
| POST | `/api/v1/claims/{claim_id}/adjudicate` |  |  | ✓ |  |  |  |
| POST | `/api/v1/claims/{claim_id}/appeal` |  |  | ✓ |  |  |  |
| POST | `/api/v1/claims/{claim_id}/attachments` |  |  | ✓ |  |  |  |
| GET | `/api/v1/claims/{claim_id}/attachments/{attachment_id}` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/claims/{claim_id}/cancel` |  | ✓ | ✓ |  |  |  |
| POST | `/api/v1/claims/{claim_id}/close` |  |  | ✓ |  |  |  |
| POST | `/api/v1/claims/{claim_id}/notes` |  | ✓ | ✓ |  |  |  |
| POST | `/api/v1/claims/{claim_id}/submit` |  |  | ✓ |  |  |  |
| GET | `/api/v1/cost-centers` | *any user* |  |  |  |  |  |
| POST | `/api/v1/cost-centers` | ✓ |  |  |  |  |  |
| GET | `/api/v1/dashboard` | *any user* |  |  |  |  |  |
| GET | `/api/v1/denial-codes` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/departments` | *any user* |  |  |  |  |  |
| POST | `/api/v1/departments` | ✓ |  |  |  |  |  |
| GET | `/api/v1/exports/ar-aging` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/exports/audit-log` | ✓ |  |  |  | ✓ | ✓ |
| GET | `/api/v1/exports/balance-sheet` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/exports/budgets/{budget_id}/variance` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/exports/income-statement` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/exports/invoices` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/exports/trial-balance` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/fiscal-periods` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/fiscal-periods` |  |  |  | ✓ | ✓ |  |
| POST | `/api/v1/fiscal-periods/{period_id}/close` |  |  |  | ✓ | ✓ |  |
| GET | `/api/v1/fiscal-periods/{period_id}/close-check` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/health` | public |  |  |  |  |  |
| GET | `/api/v1/insurers` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/insurers` | ✓ |  | ✓ |  |  |  |
| PATCH | `/api/v1/insurers/{insurer_id}` | ✓ |  | ✓ |  |  |  |
| GET | `/api/v1/invoices` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/invoices` |  | ✓ |  |  |  |  |
| GET | `/api/v1/invoices/{invoice_id}` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| PATCH | `/api/v1/invoices/{invoice_id}` |  | ✓ |  |  |  |  |
| POST | `/api/v1/invoices/{invoice_id}/apply-deposit` |  | ✓ |  |  |  |  |
| POST | `/api/v1/invoices/{invoice_id}/issue` |  | ✓ |  |  |  |  |
| GET | `/api/v1/invoices/{invoice_id}/payments` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/invoices/{invoice_id}/pdf` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/invoices/{invoice_id}/void` |  | ✓ |  |  | ✓ |  |
| GET | `/api/v1/journal-entries` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/journal-entries` |  |  |  | ✓ |  |  |
| GET | `/api/v1/journal-entries/{entry_id}` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/journal-entries/{entry_id}/approve` |  |  |  |  | ✓ |  |
| POST | `/api/v1/journal-entries/{entry_id}/reject` |  |  |  |  | ✓ |  |
| POST | `/api/v1/journal-entries/{entry_id}/reverse` |  |  |  | ✓ |  |  |
| GET | `/api/v1/notifications` | *any user* |  |  |  |  |  |
| POST | `/api/v1/notifications/read-all` | *any user* |  |  |  |  |  |
| GET | `/api/v1/notifications/unread-count` | *any user* |  |  |  |  |  |
| POST | `/api/v1/notifications/{notification_id}/read` | *any user* |  |  |  |  |  |
| GET | `/api/v1/patients` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/patients` |  | ✓ |  |  |  |  |
| GET | `/api/v1/patients/{patient_id}` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| PATCH | `/api/v1/patients/{patient_id}` |  | ✓ |  |  |  |  |
| GET | `/api/v1/payments` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/payments` |  | ✓ |  |  |  |  |
| GET | `/api/v1/payments/{payment_id}` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| GET | `/api/v1/payments/{payment_id}/receipt` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/payments/{payment_id}/refunds` |  | ✓ |  |  |  |  |
| GET | `/api/v1/payroll/employees` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/payroll/employees` |  |  |  | ✓ |  |  |
| GET | `/api/v1/payroll/employees/{employee_id}` |  |  |  | ✓ | ✓ | ✓ |
| PATCH | `/api/v1/payroll/employees/{employee_id}` |  |  |  | ✓ |  |  |
| GET | `/api/v1/payroll/employees/{employee_id}/payslips` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/payroll/employees/{employee_id}/terminate` |  |  |  | ✓ |  |  |
| GET | `/api/v1/payroll/payslips/{payslip_id}/pdf` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/payroll/runs` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/payroll/runs` |  |  |  | ✓ |  |  |
| GET | `/api/v1/payroll/runs/{run_id}` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/payroll/runs/{run_id}/approve` |  |  |  |  | ✓ |  |
| POST | `/api/v1/payroll/runs/{run_id}/pay` |  |  |  | ✓ |  |  |
| POST | `/api/v1/payroll/runs/{run_id}/recalculate` |  |  |  | ✓ |  |  |
| POST | `/api/v1/payroll/runs/{run_id}/reject` |  |  |  |  | ✓ |  |
| POST | `/api/v1/payroll/runs/{run_id}/submit` |  |  |  | ✓ |  |  |
| POST | `/api/v1/payroll/tax-preview` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/payroll/tax-slabs/{year}` |  |  |  | ✓ | ✓ | ✓ |
| PUT | `/api/v1/payroll/tax-slabs/{year}` |  |  |  | ✓ | ✓ |  |
| GET | `/api/v1/policies` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/policies` |  | ✓ | ✓ |  |  |  |
| POST | `/api/v1/policies/{policy_id}/status` |  | ✓ | ✓ |  |  |  |
| GET | `/api/v1/price-lists` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/price-lists` | ✓ |  |  |  | ✓ |  |
| GET | `/api/v1/price-lists/{price_list_id}/items` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/price-lists/{price_list_id}/items` | ✓ |  |  |  | ✓ |  |
| GET | `/api/v1/purchase-orders` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/purchase-orders` |  |  |  | ✓ |  |  |
| GET | `/api/v1/purchase-orders/{po_id}` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/purchase-orders/{po_id}/cancel` |  |  |  | ✓ |  |  |
| POST | `/api/v1/purchase-orders/{po_id}/issue` |  |  |  | ✓ |  |  |
| POST | `/api/v1/purchase-orders/{po_id}/receive` |  |  |  | ✓ |  |  |
| GET | `/api/v1/refunds` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/refunds/{refund_id}/approve` |  |  |  |  | ✓ |  |
| POST | `/api/v1/refunds/{refund_id}/reject` |  |  |  |  | ✓ |  |
| GET | `/api/v1/remittances` |  |  | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/remittances` |  |  | ✓ |  |  |  |
| GET | `/api/v1/remittances/{remittance_id}` |  |  | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/remittances/{remittance_id}/post` |  |  | ✓ |  |  |  |
| GET | `/api/v1/reports/account-ledger/{account_id}` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/reports/balance-sheet` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/reports/income-statement` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/reports/trial-balance` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/search` | *any user* |  |  |  |  |  |
| GET | `/api/v1/services` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/services` | ✓ |  |  |  | ✓ |  |
| PATCH | `/api/v1/services/{service_id}` | ✓ |  |  |  | ✓ |  |
| GET | `/api/v1/users` | ✓ |  |  |  |  | ✓ |
| POST | `/api/v1/users` | ✓ |  |  |  |  |  |
| GET | `/api/v1/users/roles` | ✓ |  |  |  |  | ✓ |
| GET | `/api/v1/users/{user_id}` | ✓ |  |  |  |  | ✓ |
| PATCH | `/api/v1/users/{user_id}` | ✓ |  |  |  |  |  |
| GET | `/api/v1/vendor-bills` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/vendor-bills` |  |  |  | ✓ |  |  |
| POST | `/api/v1/vendor-bills/payment-run` |  |  |  | ✓ |  |  |
| GET | `/api/v1/vendor-bills/{bill_id}` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/vendor-bills/{bill_id}/pay` |  |  |  | ✓ |  |  |
| POST | `/api/v1/vendor-bills/{bill_id}/schedule` |  |  |  | ✓ |  |  |
| POST | `/api/v1/vendor-bills/{bill_id}/submit` |  |  |  | ✓ |  |  |
| POST | `/api/v1/vendor-bills/{bill_id}/void` |  |  |  | ✓ | ✓ |  |
| GET | `/api/v1/vendor-payments` |  |  |  | ✓ | ✓ | ✓ |
| GET | `/api/v1/vendors` |  |  |  | ✓ | ✓ | ✓ |
| POST | `/api/v1/vendors` |  |  |  | ✓ |  |  |
| PATCH | `/api/v1/vendors/{vendor_id}` |  |  |  | ✓ |  |  |
| GET | `/api/v1/visits` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/visits` |  | ✓ |  |  |  |  |
| GET | `/api/v1/visits/{visit_id}` |  | ✓ | ✓ | ✓ | ✓ | ✓ |
| POST | `/api/v1/visits/{visit_id}/status` |  | ✓ |  |  |  |  |

161 operations; 157 require authentication.
