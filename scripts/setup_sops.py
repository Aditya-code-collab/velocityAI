"""
Seed Qdrant with IndiaMart Standard Operating Procedures.
Run once before starting the worker:  python3 setup_sops.py

The `description` field is what gets embedded for semantic search.
It concatenates the title, overview, all rules, and representative
call phrases so the vector captures real-world transcription vocabulary.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qdrant_helper import ensure_collection, upsert_sop

SOPS = [
    {
        "category": "catalog_addition",
        "title": "Catalog Addition SOP",
        "content": (
            "This SOP governs how IndiaMart sales agents must add new product catalogs "
            "for supplier accounts. The agent must verify supplier eligibility, confirm product "
            "details, and obtain explicit consent before activating any listing."
        ),
        "rules": [
            "Verify the supplier's registration and KYC status before initiating catalog addition.",
            "Confirm all product specifications: HSN code, minimum order quantity (MOQ), unit of measure.",
            "Ensure product images meet quality standards (minimum 500×500 px; white/neutral background preferred).",
            "Never add prohibited items — weapons, narcotics, counterfeit goods, or items banned under IT Act.",
            "Provide a complete product description including material, size, colour, and packaging details.",
            "Set a realistic price range validated against current market benchmarks.",
            "Explain all catalog addition charges and obtain verbal or written consent before proceeding.",
            "Inform the supplier of the expected approval timeline (24–48 business hours).",
            "Document the call outcome and catalog ID in the CRM before ending the call.",
        ],
        "keywords": ["catalog", "add product", "listing", "product", "new listing", "catalog addition"],
        "description": (
            "Catalog Addition SOP — Adding new product listings and catalogs for IndiaMart suppliers.\n\n"
            "Overview: This SOP governs how IndiaMart sales agents must add new product catalogs for "
            "supplier accounts. The agent must verify supplier eligibility, confirm product details, and "
            "obtain explicit consent before activating any listing.\n\n"
            "Rules:\n"
            "1. Verify the supplier's registration and KYC status before initiating catalog addition.\n"
            "2. Confirm all product specifications: HSN code, minimum order quantity (MOQ), unit of measure.\n"
            "3. Ensure product images meet quality standards (minimum 500×500 px; white/neutral background preferred).\n"
            "4. Never add prohibited items — weapons, narcotics, counterfeit goods, or items banned under IT Act.\n"
            "5. Provide a complete product description including material, size, colour, and packaging details.\n"
            "6. Set a realistic price range validated against current market benchmarks.\n"
            "7. Explain all catalog addition charges and obtain verbal or written consent before proceeding.\n"
            "8. Inform the supplier of the expected approval timeline (24–48 business hours).\n"
            "9. Document the call outcome and catalog ID in the CRM before ending the call.\n\n"
            "Typical call scenarios: supplier wants to add a new product, agent helping upload a listing, "
            "adding items to IndiaMart profile, creating a new catalog entry, setting up product page, "
            "uploading product images, specifying product price and MOQ, registering a new SKU, "
            "adding product details like weight material size colour, listing a product for the first time, "
            "I want to list my product on IndiaMart, help me add a new item to my catalog, "
            "can you add this product to my account, we want to start selling this new product."
        ),
    },
    {
        "category": "catalog_deletion",
        "title": "Catalog Deletion SOP",
        "content": (
            "This SOP governs the process for removing a product catalog from an IndiaMart "
            "supplier account. Deletion is irreversible for buyers who have previously saved the listing, "
            "so agents must follow strict verification and notice steps."
        ),
        "rules": [
            "Identify and document the valid reason for deletion: supplier request, policy violation, or duplicate listing.",
            "Notify the supplier at least 48 hours before deletion unless it is an emergency policy violation.",
            "Verify there are no pending or active buyer inquiries linked to the catalog before deletion.",
            "Never delete a catalog with an active order without written supervisor approval.",
            "Offer alternatives (suspension, price update, category change) before proceeding with deletion.",
            "Record the deletion reason and supervisor approval (if required) in CRM.",
            "Send a deletion confirmation to the supplier's registered email within 1 hour of deletion.",
        ],
        "keywords": ["delete catalog", "remove listing", "catalog removal", "deletion", "deactivate"],
        "description": (
            "Catalog Deletion SOP — Removing or deactivating product listings from IndiaMart supplier accounts.\n\n"
            "Overview: This SOP governs the process for removing a product catalog from an IndiaMart "
            "supplier account. Deletion is irreversible for buyers who have previously saved the listing, "
            "so agents must follow strict verification and notice steps.\n\n"
            "Rules:\n"
            "1. Identify and document the valid reason for deletion: supplier request, policy violation, or duplicate listing.\n"
            "2. Notify the supplier at least 48 hours before deletion unless it is an emergency policy violation.\n"
            "3. Verify there are no pending or active buyer inquiries linked to the catalog before deletion.\n"
            "4. Never delete a catalog with an active order without written supervisor approval.\n"
            "5. Offer alternatives (suspension, price update, category change) before proceeding with deletion.\n"
            "6. Record the deletion reason and supervisor approval (if required) in CRM.\n"
            "7. Send a deletion confirmation to the supplier's registered email within 1 hour of deletion.\n\n"
            "Typical call scenarios: supplier wants to remove a product, agent deleting a catalog entry, "
            "deactivating a listing, taking down a product from IndiaMart, removing an old SKU, "
            "I want to delete this product from my account, can you remove this item from my profile, "
            "please take down this listing, I no longer sell this product, discontinue this catalog, "
            "product is out of stock permanently and we want to remove it, delete duplicate listing."
        ),
    },
    {
        "category": "subscription_sales",
        "title": "Subscription Sales SOP",
        "content": (
            "This SOP governs how IndiaMart sales agents must pitch, explain, and close subscription "
            "packages. The focus is on transparent communication, no pressure tactics, and accurate "
            "representation of subscription benefits."
        ),
        "rules": [
            "Present all available subscription tiers and their pricing transparently before pitching any plan.",
            "Never guarantee a specific number of leads, orders, or revenue outcomes from any subscription.",
            "Explain the auto-renewal policy clearly, including the renewal date and cancellation window.",
            "Inform the supplier of the 48-hour cooling-off period during which they may cancel without penalty.",
            "Do not use pressure tactics such as false urgency ('offer expires today'), threats, or repeated cold-calls.",
            "Never misrepresent a subscription feature or imply a competitor's platform is illegal or fraudulent.",
            "Send a written subscription confirmation with all terms to the supplier's registered email within 2 hours of sale.",
            "Document all verbal commitments made during the call in CRM notes.",
            "Use only RBI-approved payment gateways; never request cash, wire transfer, or UPI to personal accounts.",
        ],
        "keywords": ["subscription", "plan", "package", "renew", "upgrade", "premium", "membership"],
        "description": (
            "Subscription Sales SOP — Selling, renewing, and upgrading IndiaMart subscription plans and packages.\n\n"
            "Overview: This SOP governs how IndiaMart sales agents must pitch, explain, and close subscription "
            "packages. The focus is on transparent communication, no pressure tactics, and accurate "
            "representation of subscription benefits.\n\n"
            "Rules:\n"
            "1. Present all available subscription tiers and their pricing transparently before pitching any plan.\n"
            "2. Never guarantee a specific number of leads, orders, or revenue outcomes from any subscription.\n"
            "3. Explain the auto-renewal policy clearly, including the renewal date and cancellation window.\n"
            "4. Inform the supplier of the 48-hour cooling-off period during which they may cancel without penalty.\n"
            "5. Do not use pressure tactics such as false urgency ('offer expires today'), threats, or repeated cold-calls.\n"
            "6. Never misrepresent a subscription feature or imply a competitor's platform is illegal or fraudulent.\n"
            "7. Send a written subscription confirmation with all terms to the supplier's registered email within 2 hours of sale.\n"
            "8. Document all verbal commitments made during the call in CRM notes.\n"
            "9. Use only RBI-approved payment gateways; never request cash, wire transfer, or UPI to personal accounts.\n\n"
            "Typical call scenarios: selling a membership plan, renewing an expired subscription, upgrading from "
            "basic to premium, pitching gold or platinum plan, offering a special subscription discount, "
            "I want to upgrade my plan, my subscription is expiring, how many leads will I get with this plan, "
            "agent promoting annual package, selling IndiaMart premium membership, subscription renewal call, "
            "offer for today only, limited time deal on subscription, take this plan and get more buyers, "
            "membership fee payment, plan upgrade with lead guarantee, closing a subscription deal."
        ),
    },
    {
        "category": "lead_management",
        "title": "Lead Management SOP",
        "content": (
            "This SOP governs how IndiaMart agents handle buyer leads, follow-ups, and buyer-seller "
            "interactions to ensure data privacy and service quality."
        ),
        "rules": [
            "Follow up on all assigned leads within 4 business hours of receipt.",
            "Never share buyer contact details (name, phone, email) with unauthorised third parties.",
            "Obtain explicit verbal consent from the buyer before recording the call.",
            "Log every buyer-seller interaction in CRM within 30 minutes of the call.",
            "Never make binding commitments about a buyer's purchase intent, volume, or timeline.",
            "Escalate unresponsive or hostile buyers to the team lead after two failed contact attempts.",
            "Do not contact a buyer who has opted out or is on the DND registry.",
        ],
        "keywords": ["lead", "buyer", "follow up", "contact", "inquiry", "RFQ", "buyer details"],
        "description": (
            "Lead Management SOP — Handling buyer inquiries, RFQs, and follow-up calls with buyers and suppliers.\n\n"
            "Overview: This SOP governs how IndiaMart agents handle buyer leads, follow-ups, and buyer-seller "
            "interactions to ensure data privacy and service quality.\n\n"
            "Rules:\n"
            "1. Follow up on all assigned leads within 4 business hours of receipt.\n"
            "2. Never share buyer contact details (name, phone, email) with unauthorised third parties.\n"
            "3. Obtain explicit verbal consent from the buyer before recording the call.\n"
            "4. Log every buyer-seller interaction in CRM within 30 minutes of the call.\n"
            "5. Never make binding commitments about a buyer's purchase intent, volume, or timeline.\n"
            "6. Escalate unresponsive or hostile buyers to the team lead after two failed contact attempts.\n"
            "7. Do not contact a buyer who has opted out or is on the DND registry.\n\n"
            "Typical call scenarios: following up on a buyer inquiry, sharing buyer contact details with supplier, "
            "buyer sent an RFQ and agent is responding, lead was assigned and agent is calling, "
            "I got a buyer lead let me connect you, someone enquired about your product, "
            "this buyer wants to purchase from you, sharing buyer phone number, buyer follow-up call, "
            "responding to an inquiry, buyer interested in bulk order, lead follow-up, connecting buyer and seller, "
            "buyer is asking about availability, RFQ response call, recording buyer interaction in system."
        ),
    },
    {
        "category": "payment_collection",
        "title": "Payment Collection SOP",
        "content": (
            "This SOP governs all payment collection activities by IndiaMart sales agents, "
            "ensuring compliance with RBI guidelines, GST regulations, and IndiaMart's internal "
            "financial controls."
        ),
        "rules": [
            "Verify the customer's identity (account ID + registered mobile OTP) before collecting any payment.",
            "Always generate an invoice or payment link in the IndiaMart system before requesting payment.",
            "Inform the customer of all applicable GST charges and the total amount due before accepting payment.",
            "Send a digital receipt (email + SMS) to the customer within 5 minutes of payment confirmation.",
            "Never accept cash payments exceeding ₹2,000 without completing Form 60 as required under Income Tax Act.",
            "Explain EMI and financing options for subscription amounts above ₹10,000.",
            "Never request payment to a personal bank account, personal UPI ID, or any non-IndiaMart payment channel.",
            "If a payment fails, do not retry more than twice without checking with the customer first.",
        ],
        "keywords": ["payment", "invoice", "collect", "cash", "UPI", "EMI", "GST", "receipt", "billing"],
        "description": (
            "Payment Collection SOP — Collecting subscription fees, invoicing, and handling payment transactions.\n\n"
            "Overview: This SOP governs all payment collection activities by IndiaMart sales agents, "
            "ensuring compliance with RBI guidelines, GST regulations, and IndiaMart's internal financial controls.\n\n"
            "Rules:\n"
            "1. Verify the customer's identity (account ID + registered mobile OTP) before collecting any payment.\n"
            "2. Always generate an invoice or payment link in the IndiaMart system before requesting payment.\n"
            "3. Inform the customer of all applicable GST charges and the total amount due before accepting payment.\n"
            "4. Send a digital receipt (email + SMS) to the customer within 5 minutes of payment confirmation.\n"
            "5. Never accept cash payments exceeding ₹2,000 without completing Form 60 as required under Income Tax Act.\n"
            "6. Explain EMI and financing options for subscription amounts above ₹10,000.\n"
            "7. Never request payment to a personal bank account, personal UPI ID, or any non-IndiaMart payment channel.\n"
            "8. If a payment fails, do not retry more than twice without checking with the customer first.\n\n"
            "Typical call scenarios: collecting payment for subscription, asking for UPI transfer, "
            "sending payment link to customer, generating invoice for renewal, customer paying membership fee, "
            "please pay on this number, pay via PhonePe or Google Pay, cash collection from supplier, "
            "payment failed let me retry, GST amount on your subscription, EMI option for annual plan, "
            "I will send you a payment link, pay to my personal account, bill amount due, "
            "subscription fee collection, asking for bank transfer, collecting outstanding dues."
        ),
    },
]


def main():
    print("Ensuring Qdrant collection exists...")
    ensure_collection()

    print(f"Upserting {len(SOPS)} SOPs...")
    for sop in SOPS:
        print(f"  → {sop['title']}")
        upsert_sop(
            category=sop["category"],
            title=sop["title"],
            content=sop["content"],
            rules=sop["rules"],
            keywords=sop["keywords"],
            description=sop["description"],
        )

    print("Done. SOPs loaded into Qdrant.")


if __name__ == "__main__":
    main()
