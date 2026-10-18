Use playwright to download receipts etc for me from various websites, using playwright mcp.
Download them as PDF, using a telling name, with expense type, date, and amount in the name (e.g. github_actions-usage_2026-07-04_usd3.23_receipt.pdf).
If authentication is required, stop and ask me to authenticate, then continue. 
Download the receipts to ~/Downloads/receipts, creating that directory if needed (FIRST check if it exists, BEFORE trying to create it)
If there are .zip files, unzip them.
Before declaring victory, CHECK that the file actually exists in the destination directory.

Here's the info on the receipt to download: $ARGUMENTS

IMPORTANT: If the vendor is not listed below, find the correct billing URL by navigating the site, then after successfully downloading the receipt, add the vendor's URL and steps to this skill file (/home/james/.claude/commands/expenses.md).

Use the following source-specific instructions:
# Slack
https://motley-ai.slack.com/admin/billing/history
Find the row matching the amount (statement date can be a day after the charge date on the bank statement).
The "Statement #SBIE-..." link points to /admin/billing/<id>/pdf — despite the name this returns a ZIP,
containing slack_invoice_<stmt>.pdf (the receipt) and slack_fair_billing_statement_<stmt>.pdf.
Don't navigate to it; use the same blob-download JS as for GitHub (fetch with credentials, a.download click),
saving with a .zip name, then unzip and move/rename both PDFs into ~/Downloads/receipts.
If a second download silently never lands (JS reports 200 but no file), Chrome is blocking multiple
automatic downloads from slack.com — ask the user to allow "Automatic downloads" for motley-ai.slack.com.

# Anthropic
The receipts can be either at 
https://claude.ai/settings/billing 
or at
https://platform.claude.com/settings/billing
In both cases, click View > Download receipt to download. 
claude.ai notes: the URL redirects to /new#settings/billing and opens a settings modal (screenshot it;
get_page_text shows only the chat page). The Max plan invoices are dated the 10th of the month and post
to the bank statement a day later. The Invoices table now has "Download PDF" instead of "View" — that gives
the unpaid-style INVOICE, not the receipt; don't use it. Instead grab the row's link href via javascript_tool
([role=dialog] tr containing the date → a.href = pay.stripe.com/invoice/<acct>/<live_token>/pdf?s=ap) and open
https://invoice.stripe.com/i/<acct>/<live_token> in a new tab. Click its "Download receipt" button by
coordinates (ref-click silently does nothing); lands in ~/Downloads as Receipt-<number>.pdf, then mv/rename.
platform.claude.com notes: requires its own sign-in (ask the user). $108.10 charges ($100 + 8.1% VAT) are
API credit grants — see Organization settings > Billing > "Invoice history" (dates in UTC), click View on
the matching row; same Stripe invoice page / "Download receipt" flow as claude.ai.

# OpenAI — API (statement shows "Openai" without chatgpt)
https://platform.openai.com/settings/organization/billing/history
Click View > Download receipt to download. 

# OpenAI — ChatGPT subscription (statement shows "Openai *chatgpt Subscr")
https://chatgpt.com/#settings/Billing
NOTE: the sub is NOT on the egor@motley.ai ChatGPT account (that one is Free) — it's on the
personal account (billing email egor.kraev@gmail.com, profile "gyg", ChatGPT Pro). Ask the user
to switch accounts if the bottom-left profile says Free. /admin/billing just redirects (no workspace).
In Settings > Billing, "Transaction history" lists payments (dated a day before the statement).
Click the ">" chevron at the far right of the matching row (clicking the row body does nothing) —
opens the OpenAI Ireland Stripe invoice page in a new tab; click "Download receipt" (by coordinates; the
first click on the new tab may only focus it — if nothing lands after ~10s, click again).
Lands in ~/Downloads as Receipt-<n>.pdf; then mv/rename.
(The #settings/Billing URL now redirects to a full page at chatgpt.com/settings/billing; if Chrome shows
the logged-out "Welcome back" dialog, ask the user to sign in.)

# Augment Code
https://app.augmentcode.com/account/subscription
Go to Payment History (will open a new tab), then click on the relevant row

# Cerebras (cerebras.ai LLM inference)
https://cloud.cerebras.ai/
Sign in, then if billing access is restricted on the default org, click "Switch to Motley AI" (or whichever org has Billing Active).
Navigate to Billing > Payment. Under "Invoice history", find the row matching the charge date/amount and click View.
The Invoice Details dialog has a "Download PDF" link pointing at pay.stripe.com/invoice/.../pdf — fetch that URL with curl.

# Meetup (meetup.com)
https://www.meetup.com/payments/meetup_plus_payments_made/
Click the "Meetup+ receipts" tab. Find the matching row and click the download icon.
This opens an HTML invoice on S3 (invoicestaxamo.s3.amazonaws.com). Convert to PDF with:
  google-chrome --headless --disable-gpu --print-to-pdf="<dest>.pdf" --no-sandbox "<s3-url>"
(Works inside the sandbox — no need to bypass it.)
Shortcut: instead of clicking the icon, grab the row's link href via javascript_tool
(document.querySelectorAll('a') filtered on 'taxamo'; rows are in date order, hrefs end in
base64-encoded INV numbers) — an invoice.taxamo.com/api/v1/transactions/.../invoice URL that
headless Chrome can render to PDF directly, no new tab needed.

# Doubleword (statement shows "Doubleword (tytn Ltd)"; LLM inference credits)
https://app.doubleword.ai/billing
Requires sign-in at auth.doubleword.ai (Google/GitHub/email + hCaptcha; ask the user).
The Billing page is a transaction history; filter type "All types" > Credits to find the
"Stripe payment" row matching the amount (statement date can be a day after; rows are not clickable).
Open the chevron next to "+ Add credits" > "Manage payment methods" — opens the Stripe billing
portal at payments.doubleword.ai in the same tab. Under "Invoice history" click the matching row
(ref-click works here) — opens the Stripe invoice page in a new tab; click "Download receipt".
Lands in ~/Downloads as Receipt-<n>.pdf; then mv/rename.

# SonarSource / SonarCloud (sonarsource.com)
https://sonarcloud.io/organizations/motleyai/billing
Requires sign-in (GitHub SSO — clicking the GitHub button on /login can pass through silently with an
active GitHub session; only ask the user if GitHub prompts). Dismiss the cookie banner (Reject All) first
if shown, or clicks won't register.
If the page stays blank white (empty #root, no console errors): check read_network_requests — JS chunks
(vendor/lodash/utils-*.js) can return cached 503s. Fix in javascript_tool: fetch each failed chunk with
{cache:'reload'}, then location.reload().
"Edit in customer portal" is a button under the "Payment settings" TAB (not Plan overview) — it opens the
Stripe billing portal at billing.sonarsource.com in the same tab (wait for the dimmed loading state to finish).
Find the invoice row matching the date/amount and click it (click the amount text, not via ref) — it opens
the Stripe invoice page in a new tab. If that tab hangs on its spinner, location.reload() fixes it.
Click "Download receipt" there; lands in ~/Downloads as Receipt-<n>.pdf.

# Gamma (statement shows "gamma.app"; Pro Monthly, €24, charged ~22nd, posts to statement a day later)
https://gamma.app/settings/billing (Settings > Workspace > Billing; dismiss any promo modal on gamma.app first)
Click "Manage subscription in Stripe" — opens the Stripe billing portal at billing.gamma.app in a new tab.
Under "Invoice history" click the amount text of the matching row (by coordinates) — opens the Stripe
invoice page in another new tab; click "Download receipt" (by coordinates).
Lands in ~/Downloads as Receipt-<n>.pdf; then mv/rename (e.g. gamma_pro-subscription_<date>_eur24.00_receipt.pdf).

# GitKraken
https://gitkraken.dev/subscription
Click "View billing history", then click "Download" on the relevant invoice row.

# GitHub (github.com)
Personal-account history: https://github.com/account/billing/history
Org (MotleyAI) history: https://github.com/organizations/MotleyAI/billing/history
Small odd amounts (e.g. $3.23) are usually metered usage (Actions etc.) billed to the MotleyAI org, monthly around the 4th.
The statement date can be a day later than GitHub's payment date (timezone shift).
Find the matching row; the Receipt column links to /organizations/<org>/billing/receipt/ch_<id>.pdf.
Do NOT navigate to that URL (opens the un-attachable PDF viewer) and don't curl it (needs session cookies).
Instead, on the history page run in javascript_tool (retry once if "Failed to fetch"):
  const resp = await fetch('<receipt .pdf path>', {credentials:'include'});
  const blob = await resp.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = '<dest-name>.pdf';
  document.body.appendChild(a); a.click();
This saves to ~/Downloads; then mv it into ~/Downloads/receipts.

# Google Cloud (GCP; statement shows "Google Cloud <code>")
https://console.cloud.google.com/billing — pick the billing account (Motley.ai billing account,
ID 01627A-5FAE5C-9E3AF7; the other "My Billing Account" is unused), then sidebar Payments > Invoices.
(/documents in the URL 404s; use /billing/<account-id>/invoices.)
Like GSuite, a charge on the ~2nd of a month is the PREVIOUS month's invoice (issue date = last day of
that month). Tick the checkbox on the matching row, click "Download selected", keep "PDF invoices" checked
in the dialog, click Download. Lands in ~/Downloads as <invoice-number>.pdf; then mv/rename.

# Google GSuite / Workspace (statement shows "Google Workspace_motle")
https://admin.google.com/ac/billing/subscriptions
(May demand password re-verification even with an active Google session — ask the user.)
Click "View invoices" on the Google Workspace Business Standard row — lands on Payment accounts >
Transactions, grouped by month (older months start collapsed — click the "1 – 31 <Mon>" header row to
expand). In the billing-period month's section, expand "Documents", click the
"PDF Invoice <number> (Created: ...)" link — a small dropdown opens; click "Download".
Lands in ~/Downloads as <invoice-number>.pdf; then mv/rename.
IMPORTANT: The payment date is the 1st of the month, but the invoice is for the PREVIOUS month's usage.
For example, a charge on Mar 2 corresponds to the February billing period invoice.
Always download the invoice from the period BEFORE the payment date month.
