"""The ONLY external numbers PakkaKhata may show (plan section 3).

Anything not in this dict must not appear as a claim in the UI, README or pitch.
Every synthetic-world parameter in config.py that is shaped on the study points back to a key here.
"""

FACTS = {
    "study": "Sungu, Alhorr & Srivastava (2026), field experiment in 26 Mumbai grocery stores, via LBS Wheeler Institute ('Between Trust and Trade')",
    "credit_customers_share_of_revenue": "~12% of customers take credit and bring 30%+ of revenue",
    "exclusive": "78% of credit customers shop only at that store",
    "no_records": "about half of owners keep no written records",
    "hours_chasing": "about 8 hours a week spent chasing repayments",
    "in_group_favouritism": "owners were about 42% more likely to offer credit to customers from their own social group",
    "random_borrowers": "randomly assigned borrowers (loans up to ₹100) were no riskier and repaid 3.5 days faster",
    "revisits": "customer revisits rose from 74% to 92%",
    "owner_lending": "owners' own lending rose from 17% to about 70%",
    "paytm_merchants": "1.64 crore subscription merchants (Paytm Q2 FY27 results)",
    "paytm_fs_revenue": "financial services revenue ₹912 cr last quarter, +49% (Paytm Q2 FY27)",
    "postpaid": "Paytm Postpaid relaunched Sept 2025 with Suryoday SFB, limits up to ₹60,000",
    # NEVER present this as "shopkeeper credit": the press note does not break non-institutional credit down by shopkeepers.
    "aidis_2019": "NSO All India Debt & Investment Survey 2019 (NSS 77th round), MoSPI press note 24 Aug 2021: of households' outstanding cash debt, 34% in rural India and 13% in urban India came from non-institutional credit agencies (institutional: 66% rural, 87% urban). Source: https://www.mospi.gov.in/sites/default/files/press_release/press_note-AIDIS-240821.pdf",
}

SYNTHETIC_FOOTER = "Synthetic demo data shaped on Sungu et al. 2026 (published findings only). Not real customers."
