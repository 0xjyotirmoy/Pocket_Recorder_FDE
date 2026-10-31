`python manage.py setup` creates (on Windows) two spoken mock meetings here (vendor call, team stand-up) plus `manifest.json`.
Replace them with the provided samples on build day. Then click **Import samples** on the Recordings page
(or `curl -X POST http://localhost:8000/import`). Importing twice is safe.

Test questions for the Ask page:

| Question | Expected |
|---|---|
| What did we promise the vendor? | Send the purchase order by Thursday + confirm delivery address; source: Vendor call |
| When is the review call? | 5 November, 3 pm |
| Who is blocked and on what? | Meera, payment API keys; Priya sends them tomorrow morning |
| When is the client demo? | Next Monday (from the stand-up) |
| What is the price per unit? | Not in recordings |
| Who is the CEO? | Not in recordings |
| Schedule the review call on 5 Nov at 3pm with Ravi | Confirm card, then event on Calendar |
| Draft a follow-up email to Ravi about the purchase order | Confirm card, then draft on Drafts |
