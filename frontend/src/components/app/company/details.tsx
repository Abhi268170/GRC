"use client";

import { Field } from "@/components/app/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { CompanyDetails, CompanyProfile } from "@/lib/types";

/** The details as a form holds them: every field a string, empty when there is no value. */
export type DetailsForm = Record<keyof CompanyDetails, string>;

export const EMPLOYEE_RANGES = ["1-10", "11-50", "51-200", "201-1000", "1000+"];

export const EMPTY_DETAILS: DetailsForm = {
  registration_number: "", legal_form: "", street: "", house_number: "", zip: "", city: "", region: "", country: "", website: "", description: "",
};

export function toForm(details: Partial<CompanyDetails> | null | undefined): DetailsForm {
  const form = { ...EMPTY_DETAILS };
  for (const key of Object.keys(form) as (keyof CompanyDetails)[]) form[key] = details?.[key] ?? "";
  return form;
}

/** What the commercial register (and Wikidata) know about a company, as a starting point the user can change. */
export function fromRegister(company: CompanyProfile): DetailsForm {
  return toForm({
    registration_number: company.uid,
    legal_form: company.legal_form,
    street: company.address.street,
    house_number: company.address.house_number,
    zip: company.address.zip,
    city: company.address.city,
    region: company.canton,
    country: "Switzerland",
    website: company.website,
    description: company.purpose?.slice(0, 4000) ?? null,
  });
}

/** What must be filled in before an admin can confirm the details (the server checks the same list). */
export function missingToConfirm(details: DetailsForm, hasIndustry: boolean): string[] {
  const needed: [boolean, string][] = [
    [details.description.trim() !== "", "What the company does"],
    [hasIndustry, "Industry"],
    [details.street.trim() !== "", "Street"],
    [details.zip.trim() !== "", "Postcode"],
    [details.city.trim() !== "", "City"],
    [details.country.trim() !== "", "Country"],
  ];
  return needed.filter(([filled]) => !filled).map(([, label]) => label);
}

export function addressLine(d: DetailsForm): string {
  const street = [d.street, d.house_number].filter(Boolean).join(" ");
  const town = [d.zip, d.city].filter(Boolean).join(" ");
  return [street, town, d.country].filter(Boolean).join(", ");
}

export function hostname(url: string): string {
  try {
    return new URL(url.includes("://") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** The editable company details. `wide` lays the short fields out side by side where the screen
 *  allows; without it everything fits a narrow column. */
export function DetailsFields({ value, onChange, disabled = false, wide = false, idPrefix = "company" }: {
  value: DetailsForm;
  onChange: (value: DetailsForm) => void;
  disabled?: boolean;
  wide?: boolean;
  idPrefix?: string;
}) {
  const input = (key: keyof CompanyDetails, label: string, props: React.ComponentProps<"input"> = {}) => (
    <Field label={label} htmlFor={`${idPrefix}-${key}`}>
      <Input id={`${idPrefix}-${key}`} disabled={disabled} value={value[key]} onChange={(e) => onChange({ ...value, [key]: e.target.value })} {...props} />
    </Field>
  );
  const pair = wide ? "grid gap-4 sm:grid-cols-2" : "space-y-4";
  return (
    <div className="space-y-4">
      <div className={pair}>
        {input("legal_form", "Legal form", { maxLength: 100, placeholder: "e.g. Corporation, LLC" })}
        {input("registration_number", "Company registration number", { maxLength: 50 })}
      </div>
      <div className="grid grid-cols-[1fr_6rem] gap-3">
        {input("street", "Street", { maxLength: 200, autoComplete: "address-line1" })}
        {input("house_number", "Number", { maxLength: 20 })}
      </div>
      <div className="grid grid-cols-[7rem_1fr] gap-3">
        {input("zip", "Postcode", { maxLength: 20, autoComplete: "postal-code" })}
        {input("city", "City", { maxLength: 100, autoComplete: "address-level2" })}
      </div>
      <div className={wide ? "grid gap-4 sm:grid-cols-2" : "grid grid-cols-2 gap-3"}>
        {input("region", "Canton or region", { maxLength: 100, autoComplete: "address-level1" })}
        {input("country", "Country", { maxLength: 100, autoComplete: "country-name" })}
      </div>
      {input("website", "Website", { maxLength: 500, inputMode: "url", placeholder: "example.com", autoComplete: "url" })}
    </div>
  );
}

/** The employee range as a row of buttons. */
export function SizePicker({ value, onChange, disabled = false }: { value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return (
    <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-5">
      {EMPLOYEE_RANGES.map((range) => (
        <button
          type="button"
          key={range}
          disabled={disabled}
          aria-pressed={value === range}
          onClick={() => onChange(range)}
          className={`h-10 whitespace-nowrap rounded-lg px-1 text-xs transition disabled:cursor-not-allowed sm:text-sm ${value === range ? "bg-primary text-primary-foreground" : "bg-muted enabled:hover:bg-muted/70 disabled:opacity-60"}`}
        >
          {range}
        </button>
      ))}
    </div>
  );
}

/** "What the company does", kept apart because sign-up asks for it in its own step. */
export function DescriptionField({ value, onChange, disabled = false, id = "company-description", hint }: {
  value: string; onChange: (value: string) => void; disabled?: boolean; id?: string; hint?: string;
}) {
  return (
    <Field label="What the company does" htmlFor={id} hint={hint}>
      <Textarea id={id} disabled={disabled} maxLength={4000} className="max-h-56 overflow-y-auto" value={value} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}
