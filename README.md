# Zuschlag.ai – interactive prototype

AI quoting for the German Mittelstand: turn an unstructured customer request (email, spec sheet) into a structured Bill of Materials and a priced quote (Angebot), then sync it to SAP.

`ZuschlagApp.jsx` is one self-contained React component (default export). It uses only:

- React (hooks)
- Tailwind CSS utility classes
- `lucide-react` icons

Paste it into a Claude Artifact (React), or drop it into any Vite/Next app with Tailwind and `lucide-react` installed.

## Demo flow

1. **Inbound Requests**: the raw RFQ email from *Rechenzentrum Nord GmbH* (15 stainless server racks, extra cooling vents, heavy-duty casters, 500 lbs load).
2. Click **✨ Generate Quote with AI**. The right panel walks through the AI pipeline (parsing → unit normalisation → BOM → SAP catalog match → labor → price rules), and the extracted phrases are highlighted in the email.
3. **Result**: a 14-line BOM (Material / Part / Labor) with an AI confidence score on each line, editable quantities, type filters, and a low-inventory warning on the casters (hover the ⚠ icon).
4. Drag the **Zuschlag** slider (or use the presets) to set the margin. Net, 19% MwSt. and gross totals update live.
5. Click **Approve & Sync to ERP** to simulate creating SAP SD quotation 20004711.

## Run locally

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # static site in dist/
```

## Live demo (GitHub Pages)

`.github/workflows/pages.yml` builds the site and deploys it to GitHub Pages on every push.

One-time setup: **Settings → Pages → Build and deployment → Source: GitHub Actions**. Then re-run the workflow, or push again.

Live URL: https://shen2083.github.io/Zuschlag/
