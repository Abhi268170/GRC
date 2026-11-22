# Control workbook conversion report

- Controls: 49
- Requirements: 228
- Action and risk templates: 456
- Framework mappings converted: 678 (CH-DPO 11, CH-FADP 62, GDPR 88, ISO-27001 251, ISO-27005 26, NIST-CSF 240)
- References left out because they don't exist in the framework: 0
- References whose title differs from the official title: 44
- References to a paragraph of an article, linked to the whole article: 30
- References to a heading that groups other clauses: 28

This check only compares each reference with the official list of clauses and titles. It can't tell whether a clause is the right one for its requirement.

## Notes

- Columns left out on purpose: Control Language, Domain Question, Roles
- IM01.0001: “Company risk exposure” holds a note, not a value; left blank.

## References kept, but the title differs from the official one

The reference exists, so it was converted. A different title is usually a paraphrase, but it can mean a different clause was meant.

| Reference | Title in the workbook | Official title | Used in |
|---|---|---|---|
| CH-DPO:Art. 15 | Notification of data security breaches | Report of breaches of data security | DPR04.0001-R2, DPR04.0001-R3 |
| CH-FADP:Art. 10 | Data protection adviser | Data protection officer | DPR01.0001-R1, DPR01.0001-R5 |
| CH-FADP:Art. 12 | Register of processing activities | Record of processing activities | DPR01.0001-R2, DPR05.0001-R5 |
| CH-FADP:Art. 16 | Disclosure of personal data abroad - principles | Principles | DPR05.0001-R4, SP03.0001-R4 |
| CH-FADP:Art. 17 | Disclosure of personal data abroad - exceptions | Exceptions | DPR05.0001-R4 |
| CH-FADP:Art. 19 | Duty to inform when collecting personal data | Duty to provide information when collecting personal data | DPR03.0001-R1 |
| CH-FADP:Art. 21 | Duty to inform about automated individual decisions | Duty to provide information in the case of an automated individual decision | DPR03.0001-R4 |
| CH-FADP:Art. 24 | Notification of data security breaches | Notifications of data security breaches | IO02.0001-R3, DPR04.0001-R1, DPR04.0001-R2, DPR04.0001-R3 and 3 more |
| CH-FADP:Art. 25 | Right of access | Right to information | DPR03.0001-R2, DPR03.0001-R5 |
| CH-FADP:Art. 32 | Legal claims | Legal rights | DPR03.0001-R2 |
| CH-FADP:Art. 7 | Data protection by design and by default | Data protection by design and data protection by default | DPR02.0001-R1, DPR06.0001-R5, IAM02.0001-R4, ASM02.0001-R1 and 1 more |
| GDPR:Art. 12 | Transparent information and communication | Transparent information, communication and modalities for the exercise of the rights of the data subject | DPR03.0001-R1, DPR03.0001-R5 |
| GDPR:Art. 13 | Information to be provided when data are collected from the data subject | Information to be provided where personal data are collected from the data subject | DPR03.0001-R1 |
| GDPR:Art. 14 | Information to be provided when data have not been obtained from the data subject | Information to be provided where personal data have not been obtained from the data subject | DPR03.0001-R1 |
| GDPR:Art. 15 | Right of access | Right of access by the data subject | DPR03.0001-R2 |
| GDPR:Art. 17 | Right to erasure | Right to erasure (‘right to be forgotten’) | DPR03.0001-R2 |
| GDPR:Art. 22 | Automated individual decision-making | Automated individual decision-making, including profiling | DPR03.0001-R4 |
| ISO-27001:6.1.1 | Actions to address risks and opportunities - General | General | RM01.0001-R1 |
| ISO-27001:8.2 | Information security risk assessment (operation) | Information security risk assessment | RM02.0001-R1, RM02.0001-R5, RM04.0001-R2 |
| ISO-27001:8.3 | Information security risk treatment (operation) | Information security risk treatment | RM03.0001-R4 |
| ISO-27005:7.4 | Evaluating information security risks | Evaluating the information security risks | RM02.0001-R4 |
| ISO-27005:8.2 | Selecting appropriate risk treatment options | Selecting appropriate information security risk treatment options | IM02.0001-R4, RM03.0001-R1 |
| ISO-27005:8.3 | Determining all controls that are necessary | Determining all controls that are necessary to implement the information security risk treatment options | RM03.0001-R2, IAM02.0001-R6 |
| ISO-27005:8.4 | Comparing determined controls with ISO/IEC 27001 Annex A | Comparing the controls determined with those in ISO/IEC 27001:2022, Annex A | RM03.0001-R2 |

## References to a paragraph of an article

The app links whole articles, so the paragraph detail is not kept.

| Article | Paragraph in the workbook | Used in |
|---|---|---|
| GDPR:Art. 32 | (1) Security of processing | DPR06.0001-R5, IAM01.0001-R3, IAM02.0001-R2, IAM02.0001-R5 and 6 more |
| GDPR:Art. 32 | (1)(d) Security of processing - regular testing and evaluation | IAM02.0001-R7 |
| GDPR:Art. 32 | (4) Security of processing - persons acting under authority | IAM02.0001-R3, IAM02.0001-R8, HRS01.0001-R2, HRS01.0001-R3 |
| GDPR:Art. 5 | (1)(c) Data minimisation | DPR02.0001-R1, DPR06.0001-R1, IAM02.0001-R4, HRS01.0001-R1 and 3 more |
| GDPR:Art. 5 | (1)(d) Accuracy | DPR06.0001-R4 |
| GDPR:Art. 5 | (1)(e) Storage limitation | LCM01.0001-R4, DPR06.0001-R2, DPR06.0001-R3, BM01.0001-R5 |
| GDPR:Art. 5 | (1)(f) Integrity and confidentiality | IM04.0001-R1 |
| GDPR:Art. 5 | (2) Accountability | DPR03.0001-R5, IAM02.0001-R7 |

## References to headings

These point at a heading that groups other clauses. They are kept, but framework coverage only counts clauses that can be assessed, so pointing at the specific sub-clause is better.

- ISO-27001:7.5: 3 mappings
- ISO-27001:9.2: 2 mappings
- ISO-27001:9.3: 3 mappings
- ISO-27005:10: 3 mappings
- ISO-27005:6: 2 mappings
- ISO-27005:6.4: 1 mapping
- ISO-27005:7: 2 mappings
- ISO-27005:7.2: 5 mappings
- ISO-27005:7.3: 2 mappings
- ISO-27005:7.4: 1 mapping
- ISO-27005:8: 1 mapping
- ISO-27005:8.6: 1 mapping
- ISO-27005:9: 2 mappings
