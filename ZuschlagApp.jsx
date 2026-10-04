import React, { useEffect, useMemo, useState } from "react";
import {
  LayoutDashboard,
  Inbox,
  FileText,
  Package,
  RefreshCw,
  Settings,
  Sparkles,
  Mail,
  Paperclip,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  ChevronRight,
  Search,
  Bell,
  Hammer,
  Layers,
  Wrench,
  Database,
  RotateCcw,
  Info,
  Clock,
  Building2,
  Download,
  ShieldCheck,
  Circle,
  Factory,
  FileSearch,
  Calculator,
  Cpu,
  ArrowRight,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/* Dummy data                                                          */
/* ------------------------------------------------------------------ */

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "inbound", label: "Inbound Requests", icon: Inbox, badge: 7 },
  { id: "quotes", label: "Quotes", icon: FileText },
  { id: "catalog", label: "Parts Catalog", icon: Package },
  { id: "erp", label: "ERP Sync", icon: RefreshCw },
  { id: "settings", label: "Settings", icon: Settings },
];

const INBOX = [
  {
    id: "REQ-2026-0412",
    from: "Markus Weber",
    company: "Rechenzentrum Nord GmbH",
    subject: "RFQ: 15 stainless server racks",
    time: "09:14",
    active: true,
  },
  {
    id: "REQ-2026-0411",
    from: "Anja Krüger",
    company: "Brenner Lebensmitteltechnik",
    subject: "Edelstahl-Arbeitstische, 8 Stk.",
    time: "08:52",
  },
  {
    id: "REQ-2026-0409",
    from: "Tom Hansen",
    company: "Nordwind Marine AG",
    subject: "Spec sheet – console housings (PDF)",
    time: "Yesterday",
  },
];

const EMAIL = {
  from: "Markus Weber",
  fromEmail: "m.weber@rz-nord.de",
  role: "Head of IT Infrastructure",
  company: "Rechenzentrum Nord GmbH",
  to: "vertrieb@mueller-metallbau.de",
  subject: "RFQ: 15 stainless server racks – Hamburg expansion",
  received: "Mon, 05 Oct 2026, 09:14",
  attachments: [{ name: "hall-B_floorplan.pdf", size: "1.2 MB" }],
  body: `Hi team,

we're expanding our colocation hall in Hamburg and need a quote for 15 custom stainless steel server racks with extra cooling vents and heavy-duty casters. Needs to support 500lbs each.

Rough dimensions: standard 19" width, 42U, about 600 x 1000 mm footprint. Front and rear doors should be lockable. We'd like fans in the top panel if possible – our last racks ran hot.

Delivery ideally by end of KW 48. Can you send something over by Friday?

Thanks,
Markus`,
};

// Phrases the "AI" extracts from the email – highlighted after analysis.
const EXTRACTED_PHRASES = [
  "15 custom stainless steel server racks",
  "extra cooling vents",
  "heavy-duty casters",
  "500lbs each",
  "42U",
  "600 x 1000 mm",
  "lockable",
  "fans in the top panel",
  "KW 48",
];

const EXTRACTED_SPECS = [
  { label: "Quantity", value: "15 units" },
  { label: "Material", value: "1.4301 (AISI 304)" },
  { label: "Load rating", value: "227 kg / unit" },
  { label: "Format", value: '19" · 42U · 600×1000' },
  { label: "Cooling", value: "Vents + top fans" },
  { label: "Delivery", value: "KW 48 / 2026" },
];

const AI_STEPS = [
  {
    label: "Parsing request",
    detail: "Extracting quantities, dimensions & constraints from email",
    icon: FileSearch,
  },
  {
    label: "Normalising units",
    detail: "500 lbs → 227 kg · 19\" / 42U → 600×1000×2000 mm",
    icon: Calculator,
  },
  {
    label: "Generating BOM structure",
    detail: "Frame, panels, doors, ventilation, mobility, internals",
    icon: Layers,
  },
  {
    label: "Matching SAP catalog parts",
    detail: "Querying MARA / MM01 · 14,382 active materials",
    icon: Database,
  },
  {
    label: "Calculating labor costs",
    detail: "Routing: laser → bending → TIG welding → assembly → QA",
    icon: Hammer,
  },
  {
    label: "Applying price rules",
    detail: "Customer group B · Steel surcharge (Legierungszuschlag) Q4",
    icon: Cpu,
  },
];

const GENERATED_BOM = [
  {
    id: 1,
    type: "Material",
    sap: "RM-1430-SH20",
    description: "Stainless sheet 1.4301, 2.0 mm, 2000×1000, brushed",
    note: "Side panels, doors, roof · 6 sheets/rack",
    qty: 90,
    unit: "sheet",
    unitCost: 148.5,
    confidence: 97,
  },
  {
    id: 2,
    type: "Material",
    sap: "RM-1430-TQ40",
    description: "Square tube 1.4301, 40×40×3 mm, 6 m bar",
    note: "Welded frame · 4 bars/rack",
    qty: 60,
    unit: "bar",
    unitCost: 96.2,
    confidence: 95,
  },
  {
    id: 3,
    type: "Material",
    sap: "RM-1430-PL15",
    description: "Perforated sheet 1.4301, 1.5 mm, Rv 5-8 (vent panels)",
    note: "Extra cooling vents · front + rear door inserts",
    qty: 30,
    unit: "sheet",
    unitCost: 132.0,
    confidence: 91,
  },
  {
    id: 4,
    type: "Part",
    sap: "PT-CAS-125HD",
    description: "Heavy-duty swivel caster Ø125 mm, 150 kg, with brake",
    note: "4/rack · 600 kg rated capacity vs. 227 kg + 95 kg tare",
    qty: 60,
    unit: "pc",
    unitCost: 38.9,
    confidence: 93,
    warning: "Low inventory warning – check SAP MM (12 on hand, 60 required)",
  },
  {
    id: 5,
    type: "Part",
    sap: "PT-HNG-SS180",
    description: "Concealed hinge, stainless, 180° opening",
    note: "Front + rear doors · 4/rack",
    qty: 60,
    unit: "pc",
    unitCost: 12.4,
    confidence: 98,
  },
  {
    id: 6,
    type: "Part",
    sap: "PT-FAN-EC120",
    description: "EC axial fan 120 mm, 230 V, 170 m³/h",
    note: "Roof fan tray · 4/rack",
    qty: 60,
    unit: "pc",
    unitCost: 27.8,
    confidence: 88,
  },
  {
    id: 7,
    type: "Part",
    sap: "PT-RAIL-42U",
    description: '19" mounting rail pair, 42U, zinc-plated',
    note: "Adjustable depth",
    qty: 15,
    unit: "set",
    unitCost: 64.0,
    confidence: 99,
  },
  {
    id: 8,
    type: "Part",
    sap: "PT-LCK-SWH",
    description: "Swing handle lock, keyed alike",
    note: "Lockable front + rear doors",
    qty: 30,
    unit: "pc",
    unitCost: 22.5,
    confidence: 96,
  },
  {
    id: 9,
    type: "Part",
    sap: "PT-FST-A2KIT",
    description: "Fastener kit A2-70 (screws, nuts, cage nuts)",
    note: "Standard rack kit",
    qty: 15,
    unit: "kit",
    unitCost: 18.6,
    confidence: 99,
  },
  {
    id: 10,
    type: "Labor",
    sap: "WC-LAS-01",
    description: "Laser cutting & press-brake bending",
    note: "Work center LASER-01 · 3.0 h/rack",
    qty: 45,
    unit: "h",
    unitCost: 85.0,
    confidence: 92,
  },
  {
    id: 11,
    type: "Labor",
    sap: "WC-WLD-TIG",
    description: "TIG welding, stainless frame",
    note: "Work center WELD-03 · 4.0 h/rack",
    qty: 60,
    unit: "h",
    unitCost: 92.0,
    confidence: 89,
  },
  {
    id: 12,
    type: "Labor",
    sap: "WC-SRF-PKL",
    description: "Pickling & passivation of welds",
    note: "External service · per rack",
    qty: 15,
    unit: "pc",
    unitCost: 45.0,
    confidence: 86,
  },
  {
    id: 13,
    type: "Labor",
    sap: "WC-ASM-02",
    description: "Assembly & fan wiring",
    note: "Work center ASM-02 · 2.5 h/rack",
    qty: 37.5,
    unit: "h",
    unitCost: 68.0,
    confidence: 94,
  },
  {
    id: 14,
    type: "Labor",
    sap: "WC-QA-LOAD",
    description: "QA: 227 kg static load test & final inspection",
    note: "Incl. test protocol per unit",
    qty: 15,
    unit: "h",
    unitCost: 75.0,
    confidence: 97,
  },
];

const AI_NOTES = [
  "Interpreted \"stainless steel\" as 1.4301 (AISI 304) – standard for indoor IT environments.",
  "Converted 500 lbs → 227 kg; casters dimensioned with 2.6× safety factor.",
  "No door style specified: assumed perforated inserts to satisfy \"extra cooling vents\".",
  "Floorplan PDF attached but not required for pricing.",
];

const VAT_RATE = 0.19;

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

const eur = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const num = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });

const TYPE_STYLES = {
  Material: { cls: "bg-sky-50 text-sky-700 ring-sky-600/20", icon: Layers },
  Part: { cls: "bg-violet-50 text-violet-700 ring-violet-600/20", icon: Wrench },
  Labor: { cls: "bg-amber-50 text-amber-700 ring-amber-600/20", icon: Hammer },
};

function confidenceStyle(c) {
  if (c >= 95) return "bg-emerald-50 text-emerald-700 ring-emerald-600/20";
  if (c >= 90) return "bg-lime-50 text-lime-700 ring-lime-600/20";
  return "bg-amber-50 text-amber-700 ring-amber-600/20";
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function HighlightedText({ text, phrases, active }) {
  if (!active) return text;
  const re = new RegExp(`(${phrases.map(escapeRegExp).join("|")})`, "gi");
  const lower = phrases.map((p) => p.toLowerCase());
  return text.split(re).map((part, i) =>
    lower.includes(part.toLowerCase()) ? (
      <mark
        key={i}
        className="rounded bg-orange-100 px-0.5 text-orange-900 ring-1 ring-orange-200 transition-colors"
      >
        {part}
      </mark>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    )
  );
}

/* ------------------------------------------------------------------ */
/* Layout pieces                                                       */
/* ------------------------------------------------------------------ */

function Sidebar({ active, onSelect }) {
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-slate-50/60 md:flex">
      <div className="flex h-14 items-center gap-2.5 border-b border-slate-200 px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 shadow-sm">
          <Factory className="h-4 w-4 text-orange-400" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight text-slate-900">
            Zuschlag<span className="text-orange-600">.ai</span>
          </div>
          <div className="text-xs text-slate-500">Müller Metallbau GmbH</div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 p-3">
        {NAV_ITEMS.map(({ id, label, icon: Icon, badge }) => {
          const isActive = active === id;
          return (
            <button
              key={id}
              onClick={() => onSelect(id)}
              className={`group flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-white font-medium text-slate-900 shadow-sm ring-1 ring-slate-200"
                  : "text-slate-600 hover:bg-white/70 hover:text-slate-900"
              }`}
            >
              <Icon
                className={`h-4 w-4 ${
                  isActive ? "text-orange-600" : "text-slate-400 group-hover:text-slate-600"
                }`}
              />
              <span className="flex-1 text-left">{label}</span>
              {badge && (
                <span className="rounded-full bg-orange-100 px-1.5 py-0.5 text-xs font-medium text-orange-700">
                  {badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="m-3 rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-700">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          SAP S/4HANA connected
        </div>
        <div className="mt-1 text-xs text-slate-500">Last sync 4 min ago · Mandant 100</div>
      </div>

      <div className="flex items-center gap-3 border-t border-slate-200 p-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700">
          JS
        </div>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-sm font-medium text-slate-800">Julia Schmidt</div>
          <div className="truncate text-xs text-slate-500">Vertriebsinnendienst</div>
        </div>
      </div>
    </aside>
  );
}

function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-slate-500">Inbound Requests</span>
        <ChevronRight className="h-4 w-4 text-slate-300" />
        <span className="font-medium text-slate-900">REQ-2026-0412</span>
        <span className="ml-2 rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-inset ring-orange-600/20">
          New RFQ
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="hidden items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-400 lg:flex">
          <Search className="h-4 w-4" />
          <span className="w-48">Search quotes, parts…</span>
          <kbd className="rounded border border-slate-200 bg-white px-1.5 text-xs text-slate-500">⌘K</kbd>
        </div>
        <button className="relative rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800">
          <Bell className="h-4 w-4" />
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-orange-500" />
        </button>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Left panel – customer request                                       */
/* ------------------------------------------------------------------ */

function RequestPanel({ status, onGenerate }) {
  const analysed = status === "result";
  const loading = status === "loading";

  return (
    <section className="flex min-h-0 flex-1 flex-col border-r border-slate-200 bg-white">
      {/* mini inbox */}
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Inbox</h2>
          <span className="text-xs text-slate-400">7 open</span>
        </div>
        <div className="space-y-1">
          {INBOX.map((m) => (
            <div
              key={m.id}
              className={`flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 transition-colors ${
                m.active ? "bg-orange-50/60 ring-1 ring-orange-200" : "hover:bg-slate-50"
              }`}
            >
              <div
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${m.active ? "bg-orange-500" : "bg-slate-300"}`}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-slate-800">{m.company}</span>
                  <span className="shrink-0 text-xs text-slate-400">{m.time}</span>
                </div>
                <div className="truncate text-xs text-slate-500">{m.subject}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* email */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
              MW
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-slate-900">
                {EMAIL.from}{" "}
                <span className="font-normal text-slate-500">&lt;{EMAIL.fromEmail}&gt;</span>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                <Building2 className="h-3.5 w-3.5" />
                {EMAIL.role}, {EMAIL.company}
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
            <Clock className="h-3.5 w-3.5" />
            {EMAIL.received}
          </div>
        </div>

        <h3 className="mb-1 text-base font-semibold tracking-tight text-slate-900">{EMAIL.subject}</h3>
        <div className="mb-4 flex items-center gap-1.5 text-xs text-slate-500">
          <Mail className="h-3.5 w-3.5" /> to {EMAIL.to}
        </div>

        <div className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50/50 p-4 text-sm leading-relaxed text-slate-700">
          <HighlightedText text={EMAIL.body} phrases={EXTRACTED_PHRASES} active={analysed} />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {EMAIL.attachments.map((a) => (
            <div
              key={a.name}
              className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 transition-colors hover:border-slate-300"
            >
              <Paperclip className="h-3.5 w-3.5 text-slate-400" />
              {a.name}
              <span className="text-slate-400">{a.size}</span>
            </div>
          ))}
        </div>

        {analysed && (
          <div className="mt-5 rounded-lg border border-orange-200 bg-orange-50/40 p-4">
            <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-orange-700">
              <Sparkles className="h-3.5 w-3.5" />
              Extracted specification
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5">
              {EXTRACTED_SPECS.map((s) => (
                <div key={s.label}>
                  <dt className="text-xs text-slate-500">{s.label}</dt>
                  <dd className="text-sm font-medium text-slate-900">{s.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      {/* action */}
      <div className="border-t border-slate-200 bg-white p-4">
        <button
          onClick={onGenerate}
          disabled={loading}
          className={`group flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold shadow-sm transition-all ${
            loading
              ? "cursor-not-allowed bg-slate-100 text-slate-400"
              : analysed
              ? "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50"
              : "bg-slate-900 text-white hover:bg-slate-800 hover:shadow-md active:scale-95"
          }`}
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Generating…
            </>
          ) : analysed ? (
            <>
              <RotateCcw className="h-4 w-4" /> Regenerate Quote
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4 text-orange-400 transition-transform group-hover:rotate-12" />
              ✨ Generate Quote with AI
            </>
          )}
        </button>
        <p className="mt-2 text-center text-xs text-slate-400">
          Uses your SAP material master, routings & price conditions
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Right panel – states                                                */
/* ------------------------------------------------------------------ */

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <div className="relative mb-6">
        <div className="grid grid-cols-3 gap-1.5 opacity-60">
          {Array.from({ length: 9 }).map((_, i) => (
            <div
              key={i}
              className={`h-8 w-14 rounded border border-dashed ${
                i % 4 === 0 ? "border-orange-300 bg-orange-50" : "border-slate-300 bg-white"
              }`}
            />
          ))}
        </div>
        <div className="absolute -bottom-3 -right-3 flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-md ring-1 ring-slate-200">
          <Sparkles className="h-5 w-5 text-orange-500" />
        </div>
      </div>
      <h3 className="text-base font-semibold text-slate-900">No quote generated yet</h3>
      <p className="mt-1.5 max-w-sm text-sm text-slate-500">
        Zuschlag.ai will read the request, build a Bill of Materials from your SAP catalog and price
        it with your labor rates – usually in under 10 seconds.
      </p>
      <div className="mt-6 flex items-center gap-2 text-xs text-slate-400">
        <span className="rounded border border-slate-200 bg-white px-2 py-1">Email / PDF</span>
        <ArrowRight className="h-3.5 w-3.5" />
        <span className="rounded border border-slate-200 bg-white px-2 py-1">Structured BOM</span>
        <ArrowRight className="h-3.5 w-3.5" />
        <span className="rounded border border-slate-200 bg-white px-2 py-1">Priced Angebot</span>
      </div>
    </div>
  );
}

function LoadingState({ step }) {
  const progress = Math.min(100, Math.round((step / AI_STEPS.length) * 100));
  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-lg bg-slate-900">
            <Sparkles className="h-5 w-5 animate-pulse text-orange-400" />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">Building your quote</div>
            <div className="text-xs text-slate-500">REQ-2026-0412 · Rechenzentrum Nord GmbH</div>
          </div>
          <div className="ml-auto font-mono text-sm tabular-nums text-slate-500">{progress}%</div>
        </div>

        <div className="mb-6 h-1 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-gradient-to-r from-orange-500 to-amber-400 transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>

        <ol className="space-y-1">
          {AI_STEPS.map((s, i) => {
            const done = i < step;
            const active = i === step;
            const Icon = s.icon;
            return (
              <li
                key={s.label}
                className={`flex items-start gap-3 rounded-lg px-3 py-2.5 transition-all duration-300 ${
                  active ? "bg-white shadow-sm ring-1 ring-slate-200" : ""
                } ${!done && !active ? "opacity-40" : ""}`}
              >
                <div className="mt-0.5">
                  {done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  ) : active ? (
                    <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
                  ) : (
                    <Circle className="h-4 w-4 text-slate-300" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                    {s.label}
                    {active && <span className="text-slate-400">…</span>}
                  </div>
                  <div className="truncate font-mono text-xs text-slate-500">{s.detail}</div>
                </div>
                <Icon className={`mt-0.5 h-4 w-4 ${active ? "text-slate-500" : "text-slate-300"}`} />
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function TypeBadge({ type }) {
  const { cls, icon: Icon } = TYPE_STYLES[type];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}
    >
      <Icon className="h-3 w-3" />
      {type}
    </span>
  );
}

function WarningFlag({ text }) {
  return (
    <span className="group relative inline-flex">
      <AlertTriangle className="h-3.5 w-3.5 cursor-help text-amber-500" />
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-56 -translate-x-1/2 rounded-md bg-slate-900 px-2.5 py-1.5 text-xs font-normal leading-snug text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
        {text}
      </span>
    </span>
  );
}

function ResultState({ items, onQtyChange, margin, setMargin, syncState, onSync }) {
  const [filter, setFilter] = useState("All");

  const subtotal = items.reduce((s, it) => s + it.qty * it.unitCost, 0);
  const byType = ["Material", "Part", "Labor"].map((t) => ({
    type: t,
    total: items.filter((i) => i.type === t).reduce((s, i) => s + i.qty * i.unitCost, 0),
  }));
  const zuschlag = subtotal * (margin / 100);
  const net = subtotal + zuschlag;
  const vat = net * VAT_RATE;
  const gross = net + vat;
  const perUnit = net / 15;
  const avgConfidence = Math.round(items.reduce((s, i) => s + i.confidence, 0) / items.length);
  const visible = filter === "All" ? items : items.filter((i) => i.type === filter);
  const synced = syncState === "done";

  return (
    <div className="space-y-5 p-6">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight text-slate-900">Angebot AN-2026-1187</h2>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
                synced
                  ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                  : "bg-slate-100 text-slate-600 ring-slate-500/20"
              }`}
            >
              {synced ? "Synced to SAP" : "Draft"}
            </span>
          </div>
          <p className="mt-0.5 text-sm text-slate-500">
            15 × Stainless server rack 42U, 600×1000 mm, ventilated, mobile
          </p>
        </div>
        <button className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-slate-50">
          <Download className="h-4 w-4" /> PDF preview
        </button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Line items", value: items.length, sub: "auto-generated" },
          { label: "Avg. AI confidence", value: `${avgConfidence}%`, sub: "1 item needs review" },
          { label: "Price per rack", value: eur.format(perUnit), sub: "net, incl. Zuschlag" },
          { label: "Est. lead time", value: "5 weeks", sub: "fits KW 48 ✓" },
        ].map((k) => (
          <div key={k.label} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="text-xs text-slate-500">{k.label}</div>
            <div className="mt-1 text-lg font-semibold tabular-nums tracking-tight text-slate-900">
              {k.value}
            </div>
            <div className="text-xs text-slate-400">{k.sub}</div>
          </div>
        ))}
      </div>

      {/* BOM table */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-900">Bill of Materials</h3>
            <span className="text-xs text-slate-400">· quantities editable</span>
          </div>
          <div className="flex rounded-md bg-slate-100 p-0.5 text-xs">
            {["All", "Material", "Part", "Labor"].map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  filter === f ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="whitespace-nowrap border-b border-slate-200 bg-slate-50/70 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
                <th className="px-4 py-2.5">Item Type</th>
                <th className="px-4 py-2.5">Description</th>
                <th className="px-4 py-2.5 text-right">Quantity</th>
                <th className="px-4 py-2.5 text-right">Unit Cost</th>
                <th className="px-4 py-2.5 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visible.map((it) => (
                <tr
                  key={it.id}
                  className={`transition-colors hover:bg-slate-50 ${it.warning ? "bg-amber-50/40" : ""}`}
                >
                  <td className="whitespace-nowrap px-4 py-3 align-top">
                    <TypeBadge type={it.type} />
                  </td>
                  <td className="px-4 py-3 align-top">
                    <div className="font-medium text-slate-800">
                      {it.description}
                      {it.warning && (
                        <span className="ml-1.5 inline-flex align-middle">
                          <WarningFlag text={it.warning} />
                        </span>
                      )}
                      <span
                        title="AI match confidence against SAP material master"
                        className={`ml-1.5 inline-flex items-center gap-1 whitespace-nowrap rounded-full align-middle px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${confidenceStyle(
                          it.confidence
                        )}`}
                      >
                        <Sparkles className="h-3 w-3" />
                        {it.confidence}%
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-500">
                      <span className="font-mono text-slate-400">{it.sap}</span>
                      <span>{it.note}</span>
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right align-top">
                    <div className="inline-flex items-center gap-1">
                      <input
                        type="number"
                        min="0"
                        step={it.unit === "h" ? 0.5 : 1}
                        value={it.qty}
                        disabled={synced}
                        onChange={(e) => onQtyChange(it.id, e.target.value)}
                        className="w-16 rounded border border-transparent bg-transparent px-1.5 py-0.5 text-right tabular-nums text-slate-800 transition-colors hover:border-slate-200 focus:border-orange-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-100 disabled:hover:border-transparent"
                      />
                      <span className="w-8 text-left text-xs text-slate-400">{it.unit}</span>
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right align-top tabular-nums text-slate-600">
                    {eur.format(it.unitCost)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right align-top font-medium tabular-nums text-slate-900">
                    {eur.format(it.qty * it.unitCost)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* bottom: notes + summary */}
      <div className="grid gap-5 xl:grid-cols-5">
        <div className="space-y-4 xl:col-span-2">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Info className="h-4 w-4 text-slate-400" /> AI assumptions
            </div>
            <ul className="space-y-2">
              {AI_NOTES.map((n) => (
                <li key={n} className="flex gap-2 text-xs leading-relaxed text-slate-600">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-400" />
                  {n}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 text-sm font-semibold text-slate-900">Cost breakdown</div>
            <div className="mb-3 flex h-2 overflow-hidden rounded-full bg-slate-100">
              {byType.map((b) => (
                <div
                  key={b.type}
                  className={`h-full transition-all duration-300 ${
                    b.type === "Material" ? "bg-sky-500" : b.type === "Part" ? "bg-violet-500" : "bg-amber-500"
                  }`}
                  style={{ width: `${subtotal ? (b.total / subtotal) * 100 : 0}%` }}
                />
              ))}
            </div>
            <div className="space-y-1.5">
              {byType.map((b) => (
                <div key={b.type} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 text-slate-600">
                    <span
                      className={`h-2 w-2 rounded-sm ${
                        b.type === "Material" ? "bg-sky-500" : b.type === "Part" ? "bg-violet-500" : "bg-amber-500"
                      }`}
                    />
                    {b.type}
                  </span>
                  <span className="tabular-nums text-slate-800">
                    {eur.format(b.total)}{" "}
                    <span className="text-slate-400">
                      ({subtotal ? num.format((b.total / subtotal) * 100) : 0}%)
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white xl:col-span-3">
          <div className="space-y-3 p-5">
            <Row label="Subtotal (Herstellkosten)" value={eur.format(subtotal)} />

            <div className="rounded-lg border border-orange-200 bg-orange-50/50 p-4">
              <div className="mb-2 flex items-center justify-between">
                <label htmlFor="zuschlag" className="text-sm font-semibold text-slate-900">
                  Zuschlag <span className="font-normal text-slate-500">(margin / markup)</span>
                </label>
                <div className="flex items-baseline gap-2">
                  <span className="text-lg font-semibold tabular-nums text-orange-700">{margin}%</span>
                  <span className="text-sm tabular-nums text-slate-600">+{eur.format(zuschlag)}</span>
                </div>
              </div>
              <input
                id="zuschlag"
                type="range"
                min="0"
                max="45"
                step="1"
                value={margin}
                disabled={synced}
                onChange={(e) => setMargin(Number(e.target.value))}
                className="w-full cursor-pointer accent-orange-600 disabled:cursor-not-allowed"
              />
              <div className="mt-1 flex justify-between text-xs text-slate-400">
                <span>0%</span>
                <span className={margin < 12 ? "font-medium text-red-600" : ""}>
                  {margin < 12 ? "Below floor (12%)" : "Target 18–25%"}
                </span>
                <span>45%</span>
              </div>
              <div className="mt-3 flex gap-1.5">
                {[12, 18, 22, 30].map((p) => (
                  <button
                    key={p}
                    disabled={synced}
                    onClick={() => setMargin(p)}
                    className={`rounded border px-2 py-0.5 text-xs font-medium transition-colors ${
                      margin === p
                        ? "border-orange-400 bg-white text-orange-700"
                        : "border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:text-slate-800"
                    }`}
                  >
                    {p}%
                  </button>
                ))}
                <span className="ml-auto self-center text-xs text-slate-400">
                  Last 5 deals w/ this customer: Ø 21%
                </span>
              </div>
            </div>

            <Row label="Net total (Netto)" value={eur.format(net)} />
            <Row label="VAT / MwSt. 19%" value={eur.format(vat)} muted />
            <div className="flex items-center justify-between border-t border-slate-200 pt-3">
              <span className="text-sm font-semibold text-slate-900">Gross total (Brutto)</span>
              <span className="text-2xl font-semibold tabular-nums tracking-tight text-slate-900">
                {eur.format(gross)}
              </span>
            </div>
          </div>

          <div className="border-t border-slate-200 bg-slate-50/60 p-4">
            {synced ? (
              <div className="flex items-center gap-3 rounded-lg bg-emerald-50 p-3 ring-1 ring-emerald-200">
                <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
                <div className="text-sm">
                  <div className="font-medium text-emerald-900">Quotation 20004711 created in SAP SD</div>
                  <div className="text-xs text-emerald-700">
                    VA21 · Sold-to 300184 · PDF sent to m.weber@rz-nord.de for review
                  </div>
                </div>
              </div>
            ) : (
              <button
                onClick={onSync}
                disabled={syncState === "syncing"}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-orange-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-all hover:bg-orange-700 hover:shadow-md active:scale-95 disabled:cursor-wait disabled:bg-orange-400"
              >
                {syncState === "syncing" ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Syncing to SAP S/4HANA…
                  </>
                ) : (
                  <>
                    <ShieldCheck className="h-4 w-4" /> Approve & Sync to ERP
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, muted }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className={muted ? "text-slate-500" : "text-slate-700"}>{label}</span>
      <span className={`tabular-nums ${muted ? "text-slate-500" : "font-medium text-slate-900"}`}>{value}</span>
    </div>
  );
}

function PlaceholderPage({ label }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <Package className="mb-3 h-8 w-8 text-slate-300" />
      <h2 className="text-base font-semibold text-slate-900">{label}</h2>
      <p className="mt-1 text-sm text-slate-500">
        Not part of this prototype – open <span className="font-medium">Inbound Requests</span> to try the AI quoting flow.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* App                                                                 */
/* ------------------------------------------------------------------ */

export default function ZuschlagApp() {
  const [nav, setNav] = useState("inbound");
  const [status, setStatus] = useState("empty"); // empty | loading | result
  const [step, setStep] = useState(0);
  const [items, setItems] = useState([]);
  const [margin, setMargin] = useState(22);
  const [syncState, setSyncState] = useState("idle"); // idle | syncing | done

  // Drive the fake AI pipeline one step at a time.
  useEffect(() => {
    if (status !== "loading") return;
    if (step >= AI_STEPS.length) {
      const t = setTimeout(() => {
        setItems(GENERATED_BOM.map((i) => ({ ...i })));
        setStatus("result");
      }, 400);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setStep((s) => s + 1), 650 + Math.random() * 450);
    return () => clearTimeout(t);
  }, [status, step]);

  useEffect(() => {
    if (syncState !== "syncing") return;
    const t = setTimeout(() => setSyncState("done"), 1600);
    return () => clearTimeout(t);
  }, [syncState]);

  const generate = () => {
    setStep(0);
    setSyncState("idle");
    setMargin(22);
    setStatus("loading");
  };

  const updateQty = (id, value) => {
    const q = Math.max(0, Number(value) || 0);
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, qty: q } : i)));
  };

  const rightPanel = useMemo(() => {
    if (status === "loading") return <LoadingState step={step} />;
    if (status === "result")
      return (
        <ResultState
          items={items}
          onQtyChange={updateQty}
          margin={margin}
          setMargin={setMargin}
          syncState={syncState}
          onSync={() => setSyncState("syncing")}
        />
      );
    return <EmptyState />;
  }, [status, step, items, margin, syncState]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-white font-sans text-slate-900 antialiased">
      <Sidebar active={nav} onSelect={setNav} />
      <main className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        {nav === "inbound" ? (
          <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-5">
            <div className="flex min-h-0 flex-col lg:col-span-2">
              <RequestPanel status={status} onGenerate={generate} />
            </div>
            <div className="min-h-0 overflow-y-auto bg-slate-50 lg:col-span-3">{rightPanel}</div>
          </div>
        ) : (
          <div className="flex-1 bg-slate-50">
            <PlaceholderPage label={NAV_ITEMS.find((n) => n.id === nav)?.label} />
          </div>
        )}
      </main>
    </div>
  );
}
