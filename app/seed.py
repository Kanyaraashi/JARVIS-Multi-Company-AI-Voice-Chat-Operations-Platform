from sqlalchemy import select

from app.db import SessionLocal
from app.models import Company, Customer, Faq

COMPANIES = [
    {
        "slug": "smile-dental",
        "name": "Smile Dental Clinic",
        "agent_name": "Maya",
        "greeting": "Hello, thank you for calling Smile Dental Clinic. I'm Maya. How can I help you today?",
        "instructions": (
            "You are Maya, the friendly receptionist of Smile Dental Clinic. "
            "Answer only using clinic information. Never give medical advice. "
            "Offer a human receptionist if the caller asks."
        ),
        "faqs": [
            ("What are your opening hours?",
             "We are open Monday to Saturday, 9 AM to 6 PM. We are closed on Sundays."),
            ("What services do you offer?",
             "We offer checkups, teeth cleaning, fillings, root canals, braces and teeth whitening."),
            ("How much is a checkup?",
             "A routine checkup costs 500 rupees."),
        ],
        "customers": [
            ("Ravi Kumar", "+919000000001", "ravi@example.com"),
            ("Anita Rao", "+919000000002", "anita@example.com"),
        ],
    },
    {
        "slug": "shopeasy",
        "name": "ShopEasy Online Store",
        "agent_name": "Ria",
        "greeting": "Hi, welcome to ShopEasy. I'm Ria. How can I help you today?",
        "instructions": (
            "You are Ria, the customer support assistant of ShopEasy. "
            "Answer only using store policies. Never promise refunds yourself. "
            "Offer a human agent if the customer asks."
        ),
        "faqs": [
            ("What is your delivery policy?",
             "Standard delivery takes 3 to 5 business days. Orders above 999 rupees ship free."),
            ("What is your return policy?",
             "Most items can be returned within 7 days of delivery if unused and in original packaging."),
            ("When will I get my refund?",
             "Refunds go to the original payment method within 5 to 7 business days after we receive the return."),
        ],
        "customers": [
            ("Priya Sharma", "+919000000003", "priya@example.com"),
            ("Arjun Mehta", "+919000000004", "arjun@example.com"),
        ],
    },
]

with SessionLocal() as db:
    for item in COMPANIES:
        existing = db.scalar(select(Company).where(Company.slug == item["slug"]))
        if existing:
            print(f"Skipping {item['slug']} (already exists)")
            continue

        company = Company(
            slug=item["slug"],
            name=item["name"],
            agent_name=item["agent_name"],
            greeting=item["greeting"],
            instructions=item["instructions"],
        )
        db.add(company)
        db.flush()  # assigns company.id so we can use it below

        for question, answer in item["faqs"]:
            db.add(Faq(company_id=company.id, question=question, answer=answer))
        for full_name, phone, email in item["customers"]:
            db.add(
                Customer(
                    company_id=company.id,
                    full_name=full_name,
                    phone=phone,
                    email=email,
                )
            )
        print(f"Added {item['slug']}")

    db.commit()