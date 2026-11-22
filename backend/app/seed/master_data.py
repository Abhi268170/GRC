"""Predefined master data. (category, code, label, numeric_value, description)

Organisational roles have their own table and seed file (organisational_roles.json)."""

MASTER_DATA: dict[str, list[tuple[str, str, float | None, str | None]]] = {
    # --- control classification ---
    "area": [
        ("strategy", "Strategy", None, None),
        ("governance_policy", "Governance & Policy", None, None),
        ("processes_procedures", "Processes & Procedures", None, None),
        ("organisation", "Organisation", None, None),
        ("training_awareness", "Training & Awareness", None, None),
        ("monitoring", "Monitoring", None, None),
        ("testing", "Testing", None, None),
        ("tools", "Tools", None, None),
        ("technical_settings", "Technical Settings / Secure Configuration", None, None),
    ],
    "control_type": [
        ("preventive", "Preventive", None, "Stops an unwanted event from happening."),
        ("detective", "Detective", None, "Notices an unwanted event while or after it happens."),
        ("corrective", "Corrective", None, "Limits the damage and restores normal operation after an event."),
    ],
    "protection_domain": [  # the NIST CSF 2.0 functions
        ("govern", "Govern", None, None),
        ("identify", "Identify", None, None),
        ("protect", "Protect", None, None),
        ("detect", "Detect", None, None),
        ("respond", "Respond", None, None),
        ("recover", "Recover", None, None),
    ],
    "security_capability": [
        ("governance_ecosystem", "Governance & Ecosystem", None, None),
        ("protection", "Protection", None, None),
        ("defence", "Defence", None, None),
        ("resilience", "Resilience", None, None),
    ],
    "protection_objective": [
        ("confidentiality", "Confidentiality", None, None),
        ("integrity", "Integrity", None, None),
        ("availability", "Availability", None, None),
        ("authenticity", "Authenticity", None, None),
        ("non_repudiation", "Non-repudiation", None, None),
        ("anonymity", "Anonymity", None, None),
    ],
    "use_case": [
        ("critical_information", "Critical Information, Systems & Processes", None, None),
        ("application_database", "Application & Database", None, None),
        ("ai", "Artificial Intelligence (AI)", None, None),
        ("cloud_virtual", "Cloud & Virtual Systems/Services", None, None),
        ("data_center", "Data Center", None, None),
        ("information_records", "Information / Records / Data Collection", None, None),
        ("it_infrastructure", "IT Infrastructure", None, None),
        ("middleware", "Middleware", None, None),
        ("network_infrastructure", "Network Infrastructure", None, None),
        ("operating_system", "Operating System / Platform", None, None),
        ("storage_system", "Storage System", None, None),
        ("third_party", "Third Party", None, None),
        ("user_device", "User Device", None, None),
        ("web_application", "Web Application", None, None),
    ],
    "company_risk_exposure": [
        ("low", "Low", 1, None),
        ("medium", "Medium", 2, None),
        ("high", "High", 3, None),
    ],
    # --- assessment & scoring ---
    "maturity_level": [
        ("na", "Not applicable", None,
         "The control doesn't apply to the company. A reason must be given."),
        ("0", "Non-existent", 0,
         "Nothing is in place. Things happen only when someone happens to act."),
        ("1", "Partial / Initial / Ad hoc", 1,
         "Some activities exist, but they're informal and depend on individual people."),
        ("2", "Defined / Risk informed", 2,
         "Processes and responsibilities are written down, but not followed the same way "
         "everywhere, and there's little monitoring."),
        ("3", "Managed / Implemented / Repeatable", 3,
         "Processes are approved and followed across the company, with enough resources, "
         "and their performance is monitored."),
        ("4", "Optimized / Adaptive", 4,
         "The company keeps measuring and improving its processes and learns from experience."),
    ],
    "risk_category": [
        ("security", "Information Security", None, None),
        ("compliance", "Compliance / Regulatory", None, None),
        ("operational", "Operational", None, None),
        ("third_party", "Third Party", None, None),
        ("data_privacy", "Data Privacy", None, None),
    ],
    "likelihood": [
        ("rare", "Rare", 1, None),
        ("unlikely", "Unlikely", 2, None),
        ("possible", "Possible", 3, None),
        ("likely", "Likely", 4, None),
        ("almost_certain", "Almost certain", 5, None),
    ],
    "impact": [
        ("negligible", "Negligible", 1, None),
        ("minor", "Minor", 2, None),
        ("moderate", "Moderate", 3, None),
        ("major", "Major", 4, None),
        ("severe", "Severe", 5, None),
    ],
    "action_priority": [
        ("low", "Low", 1, None),
        ("medium", "Medium", 2, None),
        ("high", "High", 3, None),
        ("critical", "Critical", 4, None),
    ],
}
