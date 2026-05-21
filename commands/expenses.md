Use playwright to download receipts etc for me from various websites, using playwright mcp.
Download them as PDF, using a telling name, with expense type and date in the name.
If authentication is required, stop and ask me to authenticate, then continue. 
Download the receipts to ~/Downloads/receipts, creating that directory if needed (FIRST check if it exists, BEFORE trying to create it)
If there are .zip files, unzip them.
Before declaring victory, CHECK that the file actually exists in the destination directory.

Here's the info on the receipt to download: $ARGUMENTS

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

# Google GSuite and similar
https://admin.google.com/
Click on View Transactions/Invoices, then pick the one you need.
IMPORTANT: The payment date is the 1st of the month, but the invoice is for the PREVIOUS month's usage.
For example, a charge on Mar 2 corresponds to the February billing period invoice.
Always download the invoice from the period BEFORE the payment date month.
