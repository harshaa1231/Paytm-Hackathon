# Demo script and speaker notes (Harsha)

Every number below is what the app shows from the seeded data. If you regenerate with a different seed, re-read
them from the screen.

## Before you go on stage
1. `docker run -p 8000:8000 pakkakhata` (or `uvicorn api.main:app --port 8000`), then open http://localhost:8000.
2. **Turn Wi-Fi off.** It runs from the recorded cache (replay mode); under **For judges** the header chip says **Offline mode**.
3. Press **Reset** (next to the phone). Test at 1366×768: the phone frame fits.
4. Backup: the 2-minute screen recording.

## 90 seconds
1. **The app.** Press **Next payment** (right of the phone). A notification drops in: *"₹450 received from Ramesh K"*, and the home screen shows the alert row *"₹450 from Ramesh K · Ramesh dudh wala's udhaar? · Confirm"*. Tap **Confirm** → Business Khata → the card *"Ramesh dudh wala paid ₹450"* with Groq's checked Hinglish *"PhonePe pe, ₹450 udhaar clear karna?"*. Tap **Clear ₹450**. Udhaar owed drops from **₹38,450 to ₹38,000**. Mention the Undo.
2. **Under the hood** (10 s). Click **For judges → Under the hood**. Point at the bank name **RAMESH K** vs the khata name **Ramesh dudh wala**. There are two Rameshes, both scoring 105, so the case is ambiguous and goes to the LLM (Groq picked Ramesh dudh wala: "amount matches open udhaar ₹450"; replayed from the recorded cache). Show the judge's two checks and the LangGraph strip: it paused at `ask_shopkeeper`, then resumed.
3. **Back to the app: the Lakshmi card** (Business Khata → Who you can trust). *"Lakshmi N paid you 26 times in the last 6 months and has no udhaar on record. Visits on a steady schedule and never away more than 9 days. Allow Lakshmi N udhaar up to ₹100?"* with *"✓ Agreed to share their payment record with this shop"*. Tap **Yes, allow ₹100**. It's recorded at ladder step 1 as a khata entry; nothing is sent to the customer.
4. **Forecast card.** *"About ₹20,300 of the ₹38,000 udhaar should come back in the next 7 days (likely ₹11,500 to ₹28,300)."*
5. **For judges → Evidence & proof.** Evidence (India first), then the bias chart, one sentence: *"Among equally reliable customers the shopkeeper's own choices favour his in-group by 11 points; our repayment-trained model's gap is zero. A model trained on his yes/no copies his bias as soon as behaviour hints at the group: up to 14 points in the sweep."* Then the **Learning loop** chart. Done.

Optional extras if asked: the remaining queue items show Sunita/Suneeta (partial ₹300 of ₹800), Raju's family paying from a nameless UPI ID (VPA memory), Irfan overpaying (advance or purchase?), a duplicate event (ignored), a FAILED payment (ignored) and a prompt-injection name (treated as data).

## Numbers to have ready
- Trust model: held-out AUC 0.69 (95% range 0.64–0.74 across held-out shops) vs oracle ceiling 0.77; it never sees names or groups. Threshold picked for ~90% precision on validation shops. On test shops, 83% of selected people with no credit history repaid on time (base 71%).
- Forecast: the 80% range covered the real total in 96% of 612 held-out shop-weeks (conservative).
- Matcher replay: 0 wrong customers proposed over 4 weeks; VPA memory takes over by week 3. 60 labelled Indian name pairs: 97.1% precision at auto-match, 5% false-match rate; near-identical names in one shop never auto-matched.
- Scale (India): AIDIS 2019 — 34% (rural) and 13% (urban) of households' outstanding cash debt is from non-institutional agencies. Never call this "shopkeeper credit".
- Foreign method checks only: UK retail data (feature method sanity check, not Indian, not repayment) AUC 0.80 vs 0.76; Taiwan credit data (audit method only).
- **Retrain button:** measured steps 0.691 → 0.685 → 0.692 held-out AUC. Each change is within noise (the 95% range across held-out shops is about ±0.05), and the page says so. It learns only from synthetic repayment batches; no shop's records go into the shared model.

## Judge Q&A (short answers)
- **What's new?** Other apps record who owes money. We decide who to trust next, start small, and learn only from repayments, so we don't copy the shopkeeper's bias. Show the bias chart.
- **What if Lakshmi doesn't pay?** The first offer is ₹100. It grows only after 3 on-time repayments; late steps it down; unpaid at 30 days freezes it. The shopkeeper decides every time. In the study, random borrowers at up to ₹100 were no riskier.
- **Is this a credit product? RBI?** No money moves through Paytm, and no payment or collect request is ever sent. It's the shop's own udhaar, which they already give. We only suggest. Paytm Postpaid would be a separate, opt-in, regulated product later.
- **Beyond 26 Mumbai shops?** We don't know yet. That's why the ask is a pilot: switch it on for some shops, compare with similar shops, and measure on-time repayment, returning customers, bad debt and opt-outs.
- **Your data is synthetic.** Yes, shaped on the study's published findings. Separately, each method was checked on real public data. Real Paytm QR data is the pilot.
- **Why an LLM? Why LangGraph?** Fuzzy rules fail on nicknames vs bank names. The LLM handles only the ambiguous ones, using that shop's own past matches as examples. LangGraph because the workflow has to stop for a human tap and resume exactly where it left off.
- **Privacy?** Only that shop's own payments, nothing shared across shops, masked UPI IDs, no sensitive attributes, and consent before a customer is offered credit.
- **Leakage?** The train/test split is by shop, and features use only data before the cutoff (tested).
- **LLM down?** Gemini fallback, then rules. Demo it with Wi-Fi off.
- **Northeast / South?** It needs only UPI into a Paytm QR. The screen is phone-first with one tap per decision, and languages are a translation file, so Assamese or Tamil is content work.
- **Implementable at Paytm?** Every input already exists (QR payments, Business Khata, merchant subscriptions). It's a scoring and matching layer on top, rolled out behind a per-merchant feature flag to a few hundred shops first.
- **Tools beyond the slide?** SQLite, Pydantic, NumPy, pytest, React/Tailwind/Recharts for the web app, fairlearn for the audit. **Update the deck's tech slide: Streamlit was replaced by a React web app served by FastAPI.**
