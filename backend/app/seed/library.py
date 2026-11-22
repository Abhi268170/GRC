"""Control library seed: the 25 domains (abbreviation, name, optional description). The library
starts with no controls; the super admin adds or imports them.

The last six domains come from the client's control workbook of 02-11-2026. Their abbreviations
were proposed in that workbook and are not confirmed by the client yet; an abbreviation can't
change once controls use it."""

DOMAINS: list[tuple[str, ...]] = [
    ("BC", "Business Continuity Management"),
    ("BM", "Backup Management"),
    ("CF", "Configuration Management"),
    ("CM", "Change Management"),
    ("IAM", "Identity & Access Management"),
    ("IM", "Information Security Management"),
    ("IN", "Incident Management"),
    ("IO", "Internal Organization"),
    ("OP", "Operational Procedures"),
    ("PM", "Project Management"),
    ("PS", "Physical Security Management"),
    ("RM", "Risk Management"),
    ("SE", "System & Network Security"),
    ("SP", "Supplier & Service Provider Management"),
    ("DPR", "Data Protection Regulations"),
    ("HR", "Human Resources"),
    ("ICS", "ICS & Finance"),
    ("SM", "Service Management"),
    ("QM", "Quality Management & Compliance"),
    ("LCM", "Legal & Compliance Management",
     "Ensures that applicable legal, regulatory, contractual, and internal requirements are identified, understood, implemented, and monitored. Covers compliance obligations, regulatory requirements, contractual commitments, internal policies, evidence of compliance, reviews, and management of non-compliance."),
    ("AM", "Asset Management",
     "Ensures that information, technology, physical, and other relevant assets are identified, inventoried, classified, assigned to responsible owners, and managed throughout their lifecycle. Covers asset inventories, ownership, classification, acceptable use, lifecycle management, and secure disposal or return."),
    ("HRS", "HR Security Management",
     "Ensures that security risks related to employees and other personnel are managed throughout the employment lifecycle. Covers pre-employment screening, security responsibilities, confidentiality obligations, awareness and training, changes in employment, disciplinary processes, and secure offboarding."),
    ("TVM", "Threat & Vulnerability Management",
     "Ensures that security threats and vulnerabilities are systematically identified, assessed, prioritized, monitored, and addressed to reduce risk to systems, applications, infrastructure, and information. Covers threat intelligence, vulnerability identification and assessment, remediation, risk-based prioritization, and ongoing monitoring."),
    ("SML", "Security Monitoring & Logging",
     "Ensures that security-relevant events and log data are centrally collected, correlated, analyzed, and monitored to enable timely detection, investigation, and response to potential security incidents. Covers logging requirements, log collection and protection, event correlation, alerting, monitoring, analysis, and retention."),
    ("ASM", "Application Security Management",
     "Ensures that applications are securely designed, developed, acquired, deployed, operated, maintained, and retired throughout their lifecycle. Covers security requirements, secure development practices, application architecture and design, security testing, application vulnerabilities, changes, third-party components, and ongoing application security."),
]
