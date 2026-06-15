Use playwright to download receipts etc for me from various websites, using playwright mcp.
Download them as PDF, using a telling name, with expense type and date in the name.
If authentication is required, stop and ask me to authenticate, then continue. 
Download the receipts to ~/Downloads/receipts, creating that directory if needed (FIRST check if it exists, BEFORE trying to create it)
If there are .zip files, unzip them.
Before declaring victory, CHECK that the file actually exists in the destination directory.

Here's the info on the receipt to download: $ARGUMENTS

IMPORTANT: If the vendor is not listed below, find the correct billing URL by navigating the site, then after successfully downloading the receipt, add the vendor's URL and steps to this skill file (/home/james/.claude/commands/expenses.md).

Use the following source-specific instructions:
# Slack
https://motley-ai.slack.com/admin/billing/history

# Anthropic
The receipts can be either at 
https://claude.ai/settings/billing 
or at
https://platform.claude.com/settings/billing
In both cases, click View > Download receipt to download. 

# OpenAI
https://platform.openai.com/settings/organization/billing/history
Click View > Download receipt to download. 

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
(Must run with dangerouslyDisableSandbox: true)

# SonarSource / SonarCloud (sonarsource.com)
https://sonarcloud.io/organizations/motleyai/billing
Click "Edit in customer portal" — this opens a Stripe billing portal at billing.sonarsource.com.
Find the invoice row matching the date/amount and click it to open the Stripe invoice page.
On the Stripe invoice page, click "Download receipt".

# GitKraken
https://gitkraken.dev/subscription
Click "View billing history", then click "Download" on the relevant invoice row.

# Google GSuite and similar
https://admin.google.com/
Click on View Transactions/Invoices, then pick the one you need.
IMPORTANT: The payment date is the 1st of the month, but the invoice is for the PREVIOUS month's usage.
For example, a charge on Mar 2 corresponds to the February billing period invoice.
Always download the invoice from the period BEFORE the payment date month.
